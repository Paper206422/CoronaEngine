from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .intent_understanding import get_intent_understanding_service


_DIRECT_GENERATE_WORDS = (
    "直接生成", "现在生成", "马上生成", "开始生成", "确认开始", "按这个方案",
    "按方案开始", "开始搭建", "开始布置", "先生成", "直接搭建",
)

_PLAN_WORDS = (
    "我有一个计划", "我想做", "我想要做", "帮我规划", "设计一个",
    "我们来做", "建立一个", "搭建一个", "规划一个",
)

_GENERATION_DELTA_WORDS = (
    "后面", "接下来", "后续", "再加", "增加", "补充", "多一点",
    "不要再", "别再", "少一点", "移除后续",
)

_LAYOUT_CONSTRAINT_WORDS = (
    "靠墙", "不要挡", "别挡", "入口", "门口", "不要太挤", "别太挤",
    "不要太空", "中间", "活动区", "外面", "轴线", "留空", "开阔",
)

_EDIT_WORDS = (
    "放大", "缩小", "变大", "变小", "贴地", "穿模", "抬高", "底座",
    "移远", "靠左", "靠右", "往前", "往后", "删除", "删掉", "移除",
)

_PLAN_SUPPLEMENT_WORDS = (
    "补充", "再加", "增加", "我希望", "希望", "更", "不要", "别", "不能",
    "风格", "统一", "一致", "温暖", "灯光", "灯笼", "休息区", "暗黑风",
    "不要太恐怖", "不太恐怖", "适合", "整体",
)

_DISCLOSURE_CANDIDATE_TERMS = (
    "草原", "天空", "森林", "树林", "地形", "地面", "地板", "墙面", "天花板",
    "床", "柜", "桌", "椅", "灯", "灯笼", "台灯", "雕像", "玩偶", "摊位",
    "导视牌", "展示架", "绿植", "植物", "地毯", "沙发", "小狗", "狗", "猫",
    "入口", "通道", "主街", "边界", "休息区",
)

MODE_DISCUSSING = "DISCUSSING"
MODE_PLANNING = "PLANNING"
MODE_EXECUTING = "EXECUTING"
MODE_PAUSED = "PAUSED"
_VALID_MODES = {MODE_DISCUSSING, MODE_PLANNING, MODE_EXECUTING, MODE_PAUSED}
_PAUSE_MODES = {MODE_DISCUSSING, MODE_PAUSED}


@dataclass
class PlanningConfirmation:
    proposal_id: str
    target_agent: str
    scene_goal: str
    proposed_items: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    status: str = "pending"
    created_at: float = field(default_factory=time.time)


@dataclass
class PendingSceneNote:
    text: str
    kind: str
    source_agent: str
    source_user_id: str = ""
    created_at: float = field(default_factory=time.time)


class LanChatSceneRuntime:
    """Small Python-side state for single-user progressive intervention.

    This is deliberately not a chat/network state source. C++ LANChat still owns
    transport/history. The runtime only lets long compose jobs expose a minimal
    side-channel for confirmation and pending scene notes.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mode: str = MODE_DISCUSSING
        self._pending_confirmations: dict[str, PlanningConfirmation] = {}
        self._active_agent: str = ""
        self._active_goal: str = ""
        self._active_since: float = 0.0
        self._pending_notes: list[PendingSceneNote] = []

    @staticmethod
    def _agent_key(agent_name: str) -> str:
        return str(agent_name or "agent").strip() or "agent"

    @staticmethod
    def is_direct_generate(text: str) -> bool:
        return get_intent_understanding_service().is_generation_start(text)

    @staticmethod
    def is_plan_like(text: str) -> bool:
        return get_intent_understanding_service().is_plan_like(text)

    @staticmethod
    def is_pending_scene_note(text: str) -> bool:
        return get_intent_understanding_service().scene_note_kind(text) != "chat"

    @staticmethod
    def classify_scene_note(text: str) -> str:
        return get_intent_understanding_service().scene_note_kind(text)

    @staticmethod
    def is_plan_supplement(text: str) -> bool:
        return get_intent_understanding_service().is_plan_supplement(text)

    def set_mode(self, mode: str) -> str:
        normalized = str(mode or "").strip().upper()
        if normalized not in _VALID_MODES:
            normalized = MODE_DISCUSSING
        with self._lock:
            self._mode = normalized
        return normalized

    def mode(self) -> str:
        with self._lock:
            return self._mode

    def should_pause_batches(self) -> bool:
        with self._lock:
            return self._mode in _PAUSE_MODES

    def handle_planning_gate(self, agent_name: str, text: str) -> tuple[str, str | None]:
        """Return (action, payload).

        action:
          - reply: payload is user-visible confirmation/update text
          - compose: payload is enriched compose text
          - pass: caller should continue normal routing
        """
        key = self._agent_key(agent_name)
        value = str(text or "").strip()
        if not value:
            return "pass", None

        with self._lock:
            pending = self._pending_confirmations.get(key)
            if pending and self.is_direct_generate(value):
                compose_text = self._compose_text_from_confirmation(pending, value)
                pending.status = "confirmed"
                self._pending_confirmations.pop(key, None)
                self._mode = MODE_EXECUTING
                return "compose", compose_text

            if pending and self.is_plan_supplement(value):
                pending.constraints.append(value)
                for item in self._extract_requested_items(value):
                    if item not in pending.proposed_items:
                        pending.proposed_items.append(item)
                return "reply", self._format_confirmation(pending, updated=True)

            if self.is_plan_like(value) and not self.is_direct_generate(value):
                confirmation = PlanningConfirmation(
                    proposal_id=f"plan-{uuid.uuid4().hex[:8]}",
                    target_agent=key,
                    scene_goal=self._extract_scene_goal(value),
                    proposed_items=self._seed_items_from_text(value),
                    constraints=[],
                )
                self._pending_confirmations[key] = confirmation
                self._mode = MODE_PLANNING
                return "reply", self._format_confirmation(confirmation)

        return "pass", None

    def handle_pending_planning_message(self, text: str) -> tuple[str, str | None, str | None]:
        """Route an unmentioned room message to the only pending planning gate."""
        value = str(text or "").strip()
        if not value:
            return "pass", None, None
        with self._lock:
            pending_keys = [
                key
                for key, pending in self._pending_confirmations.items()
                if pending.status == "pending"
            ]
        if not pending_keys:
            return "pass", None, None
        decision = get_intent_understanding_service().classify(value, allow_llm=False)
        if len(pending_keys) != 1:
            if decision.intent in {
                "generation_start",
                "plan_revision",
                "intervention_add",
                "intervention_modify",
                "intervention_delete",
                "final_adjustment_request",
            }:
                return "reply", self._format_pending_disambiguation(pending_keys), "系统"
            return "pass", None, None
        agent_key = pending_keys[0]
        action, payload = self.handle_planning_gate(agent_key, value)
        if action == "pass":
            return "pass", None, None
        return action, payload, agent_key

    def handle_targeted_planning_message(
        self,
        target: str,
        text: str,
        *,
        draft_action: str = "",
    ) -> tuple[str, str | None, str | None]:
        """Route a structured UI action to a pending planning gate.

        `target` can be a target agent name/id or a pending proposal id. This is
        used by the LANChat UI metadata path so the user does not have to type
        @Agent or magic confirmation words.
        """
        value = str(text or "").strip()
        if not value:
            return "pass", None, None
        action = str(draft_action or "").strip().lower()
        with self._lock:
            agent_key = self._pending_agent_for_target(target)
            if not agent_key:
                return "pass", None, None
        routed_text = value
        if action == "generate" and not self.is_direct_generate(routed_text):
            routed_text = f"确认开始：{routed_text}"
        elif action == "supplement" and not self.is_plan_supplement(routed_text):
            routed_text = f"补充要求：{routed_text}"
        result, payload = self.handle_planning_gate(agent_key, routed_text)
        if result == "pass":
            return "pass", None, None
        return result, payload, agent_key

    def pending_planning_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            pending = [
                confirmation
                for confirmation in self._pending_confirmations.values()
                if confirmation.status == "pending"
            ]
            pending.sort(key=lambda item: item.created_at)
            return [
                {
                    "proposal_id": item.proposal_id,
                    "target_agent": item.target_agent,
                    "scene_goal": item.scene_goal,
                    "proposed_items": list(item.proposed_items),
                    "constraints": list(item.constraints),
                    "status": item.status,
                    "created_at": item.created_at,
                }
                for item in pending
            ]

    def _pending_agent_for_target(self, target: str) -> str:
        wanted = str(target or "").strip()
        if not wanted:
            return ""
        wanted_lower = wanted.lower()
        for key, pending in self._pending_confirmations.items():
            if pending.status != "pending":
                continue
            if (
                key == wanted
                or key.lower() == wanted_lower
                or pending.target_agent == wanted
                or pending.target_agent.lower() == wanted_lower
                or pending.proposal_id == wanted
            ):
                return key
        return ""

    @staticmethod
    def _format_pending_disambiguation(pending_keys: list[str]) -> str:
        targets = "、".join(str(key) for key in pending_keys if str(key).strip())
        return (
            "请先 @ 指定要更新哪个方案。"
            f"当前有多个待确认方案：{targets}。"
            "例如：@小女孩 补充要求：减少细碎装饰，保留核心家具。"
        )

    def clear_pending_planning(self, agent_name: str | None = None) -> None:
        with self._lock:
            if agent_name:
                self._pending_confirmations.pop(self._agent_key(agent_name), None)
            else:
                self._pending_confirmations.clear()

    def start_compose(self, agent_name: str, goal: str) -> None:
        with self._lock:
            self._mode = MODE_EXECUTING
            self._active_agent = self._agent_key(agent_name)
            self._active_goal = str(goal or "")[:300]
            self._active_since = time.time()
            self._pending_notes.clear()

    def end_compose(self, agent_name: str | None = None) -> None:
        with self._lock:
            if agent_name and self._active_agent and self._agent_key(agent_name) != self._active_agent:
                return
            self._active_agent = ""
            self._active_goal = ""
            self._active_since = 0.0
            self._pending_notes.clear()
            self._mode = MODE_DISCUSSING

    def active_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": bool(self._active_agent),
                "mode": self._mode,
                "active_agent": self._active_agent,
                "active_goal": self._active_goal,
                "active_since": self._active_since,
                "pending_count": len(self._pending_notes),
            }

    def record_busy_message(
        self,
        *,
        agent_name: str,
        text: str,
        source_user_id: str = "",
    ) -> str | None:
        value = str(text or "").strip()
        if not value:
            return None
        with self._lock:
            if not self._active_agent:
                return None
            kind = self.classify_scene_note(value)
            if kind != "chat":
                self._pending_notes.append(PendingSceneNote(
                    text=value,
                    kind=kind,
                    source_agent=self._agent_key(agent_name),
                    source_user_id=source_user_id,
                ))
                if kind == "edit_existing":
                    return "已收到这条编辑请求；如果物体已经出现，我会在下一批前尝试应用，未出现则先挂起。"
                if kind == "layout_constraint":
                    return f"已记录布局要求：{value}。后续摆放会在下一批前吸收。"
                requested = self._extract_requested_items(value)
                if requested:
                    return f"已记录后续补充：{'、'.join(requested[:4])}。我会优先尝试加入后续批次；若当前没有可用模型，会在最终报告里标为待补。"
                return "已记录后续生成补充。我会优先尝试加入后续批次；若当前没有可用模型，会在最终报告里标为待补。"
            if self._agent_key(agent_name) != self._active_agent:
                return f"{self._active_agent} 正在生成。我先帮你记录这条意见，等下一批前一起吸收。"
        return None

    def consume_notes_for_prompt(self) -> str:
        with self._lock:
            notes = list(self._pending_notes)
            self._pending_notes.clear()
        if not notes:
            return ""
        grouped: dict[str, list[str]] = {"generation_delta": [], "layout_constraint": [], "edit_existing": []}
        for note in notes:
            grouped.setdefault(note.kind, []).append(note.text)
        lines = ["## 生成中用户介入（下一批前吸收）"]
        if grouped.get("generation_delta"):
            lines.append("后续生成补充：" + "；".join(grouped["generation_delta"]))
        if grouped.get("layout_constraint"):
            lines.append("后续布局约束：" + "；".join(grouped["layout_constraint"]))
        if grouped.get("edit_existing"):
            lines.append("已有物体编辑请求：" + "；".join(grouped["edit_existing"]))
        return "\n".join(lines)

    def consume_notes(self) -> list[PendingSceneNote]:
        with self._lock:
            notes = list(self._pending_notes)
            self._pending_notes.clear()
        return notes

    def _compose_text_from_confirmation(self, confirmation: PlanningConfirmation, user_text: str) -> str:
        brief = self._design_brief_lines(confirmation)
        parts = [
            f"用户确认开始生成：{confirmation.scene_goal}",
            "确认方案内容：",
            *brief,
            "建议物体清单：" + "、".join(confirmation.proposed_items),
        ]
        if confirmation.constraints:
            parts.append("补充要求：" + "；".join(confirmation.constraints))
        parts.append("最新指令：" + user_text)
        return "\n".join(parts)

    def _format_confirmation(self, confirmation: PlanningConfirmation, *, updated: bool = False) -> str:
        prefix = "我已更新方案。" if updated else f"我理解你的目标是：{confirmation.scene_goal}。"
        brief = self._design_brief_lines(confirmation)
        lines = [
            prefix,
            "",
            "方案内容：",
            *brief,
        ]
        if confirmation.constraints:
            lines.extend([
                "",
                "已纳入补充要求：" + "；".join(confirmation.constraints),
            ])
        lines.extend([
            "",
            "建议先做：",
            "1. 锁定空间边界和主要动线",
            "2. 先生成核心物件：" + "、".join(self._core_items(confirmation)[:4]),
            "3. 再补足氛围装饰：" + "、".join(self._decor_items(confirmation)[:4]),
            "4. 最后检查比例、留空和遮挡关系",
            "",
            "你可以回复：",
            "- 确认开始：按当前方案进入 3D 场景生成。",
            "- 补充要求：写明要改的风格、物件、布局或限制；我会先更新方案，不会立刻生成。",
            "- 例如：补充要求：床边加一个小书架，整体更粉一点。",
            "- 直接生成：跳过继续讨论，立即按当前方案开始生成。",
        ])
        disclosure = self._classification_disclosure(confirmation.scene_goal, confirmation.proposed_items)
        if disclosure:
            lines.extend(["", "提炼结果：", disclosure])
        return "\n".join(lines)

    def _design_brief_lines(self, confirmation: PlanningConfirmation) -> list[str]:
        core = self._core_items(confirmation)
        decor = self._decor_items(confirmation)
        return [
            f"1. 风格定位：{self._style_direction(confirmation.scene_goal)}",
            f"2. 空间布局：{self._layout_direction(confirmation.scene_goal)}",
            "3. 核心物件：" + "、".join(core[:5]),
            "4. 氛围装饰：" + "、".join(decor[:5]),
        ]

    @staticmethod
    def _style_direction(goal: str) -> str:
        value = str(goal or "")
        styles: list[str] = []
        if any(word in value for word in ("可爱", "少女", "小女孩", "童趣")):
            styles.append("明亮可爱")
        if any(word in value for word in ("温暖", "暖", "治愈")):
            styles.append("温暖治愈")
        if any(word in value for word in ("暗黑", "神秘", "奇幻")):
            styles.append("奇幻神秘")
        if any(word in value for word in ("森林", "草原", "室外")):
            styles.append("自然户外")
        if not styles:
            styles.append("围绕目标主题统一色彩、材质和装饰语言")
        return "、".join(styles)

    @staticmethod
    def _layout_direction(goal: str) -> str:
        value = str(goal or "")
        if any(word in value for word in ("卧室", "房间")):
            return "以床区为视觉中心，保留入口到床边的通行动线，侧边安排收纳和学习/梳妆角"
        if any(word in value for word in ("集市", "摊", "街")):
            return "以主路为中轴，两侧布置摊位和停留点，入口保持开阔"
        if any(word in value for word in ("客厅", "休息区")):
            return "以沙发/茶几形成交流中心，周边留出通行和展示区域"
        if any(word in value for word in ("草原", "森林", "室外", "露营")):
            return "用开阔地形承载主体活动区，边缘布置自然元素形成层次"
        return "先确定主活动区，再围绕它安排支撑物件、装饰和留白"

    @staticmethod
    def _core_items(confirmation: PlanningConfirmation) -> list[str]:
        items = list(confirmation.proposed_items or [])
        value = confirmation.scene_goal
        if any(word in value for word in ("卧室", "房间")):
            preferred = ["床", "床头柜", "衣柜/收纳柜", "书桌或梳妆台", "地毯"]
        elif any(word in value for word in ("集市", "摊", "街")):
            preferred = ["入口牌", "主路", "摊位", "展示桌", "休息点"]
        elif any(word in value for word in ("草原", "森林", "室外", "露营")):
            preferred = ["地形主体", "活动中心", "路径", "树木/花草", "休息点"]
        else:
            preferred = ["主体空间", "主要功能物件", "支撑物件", "路径/动线", "停留点"]
        return LanChatSceneRuntime._merge_unique(preferred, items, limit=8)

    @staticmethod
    def _decor_items(confirmation: PlanningConfirmation) -> list[str]:
        items = list(confirmation.proposed_items or [])
        value = confirmation.scene_goal
        if any(word in value for word in ("可爱", "少女", "小女孩", "童趣")):
            preferred = ["玩偶/抱枕", "小花装饰", "暖色灯串", "柔软地毯", "粉色或浅色点缀"]
        elif any(word in value for word in ("暗黑", "神秘", "奇幻")):
            preferred = ["灯笼/烛光", "旗帜", "木牌", "雾气氛围", "奇幻小道具"]
        else:
            preferred = ["氛围灯光", "主题装饰", "小型道具", "色彩点缀", "导视/标识"]
        return LanChatSceneRuntime._merge_unique(preferred, items, limit=8)

    @staticmethod
    def _merge_unique(*groups: list[str], limit: int = 8) -> list[str]:
        merged: list[str] = []
        for group in groups:
            for item in group:
                value = str(item or "").strip()
                if value and value not in merged:
                    merged.append(value)
                if len(merged) >= limit:
                    return merged
        return merged

    @staticmethod
    def _extract_scene_goal(text: str) -> str:
        value = re.sub(r"@\S+\s*", "", str(text or "")).strip()
        value = re.sub(r"^.*?(我有一个计划[，,]?)", "", value).strip()
        value = re.sub(r"^(?:请|麻烦你|帮我|给我|我想要|我想做|我们来)?\s*", "", value).strip()
        value = re.sub(r"^(?:建立|搭建|设计|规划|做|布置)(?:一个|一下|一间)?", "", value).strip()
        return value or str(text or "").strip() or "新的开放场景"

    @staticmethod
    def _extract_requested_items(text: str) -> list[str]:
        value = re.sub(r"@\S+\s*", "", str(text or "")).strip()
        value = re.sub(
            r"^(?:后面|后续|接下来|之后)?\s*(?:再)?(?:补充|增加|新增|添加|加入|加|再加)\s*[:：]?",
            "",
            value,
        ).strip()
        chunks = re.split(r"[、，,和以及;；\s]+", value)
        out: list[str] = []
        for chunk in chunks:
            item = LanChatSceneRuntime._normalize_requested_item(chunk)
            if 1 < len(item) <= 12 and not any(word in item for word in ("补充", "增加", "新增", "添加", "加入", "再加", "需要", "想要")):
                out.append(item)
        return out[:6]

    @staticmethod
    def _normalize_requested_item(value: str) -> str:
        item = str(value or "").strip(" “‘”\"'，。；;,.")
        item = re.sub(r"^(?:后面|后续|接下来|之后|再|新增|增加|添加|加入|加|补|帮我|给我|设计|规划|做|布置|一个|一间|一只|一座|一盏|一张|一把)+", "", item).strip()
        item = re.sub(r"^(?:个|只|座|盏|张|把)", "", item).strip()
        item = re.sub(r"(?:要|得|需要|应该|放在|摆在).*$", "", item).strip()
        return item

    @classmethod
    def _seed_items_from_text(cls, text: str) -> list[str]:
        items = cls._extract_requested_items(text)
        for item in cls._candidate_items_from_text(text):
            if item not in items:
                items.append(item)
        goal = cls._extract_scene_goal(text)
        if any(word in goal for word in ("卧室", "房间")):
            generic = ["床", "床头柜", "衣柜/收纳柜", "书桌或梳妆台", "地毯", "玩偶/抱枕", "暖色灯串"]
        elif any(word in goal for word in ("集市", "摊", "街")):
            generic = ["入口牌", "主路", "摊位", "展示桌", "休息点", "氛围灯光", "主题装饰"]
        elif any(word in goal for word in ("草原", "森林", "室外", "露营")):
            generic = ["地形主体", "活动中心", "路径", "树木/花草", "休息点", "氛围灯光", "小型道具"]
        else:
            generic = ["主体空间", "主要功能物件", "支撑物件", "路径/动线", "氛围灯光", "主题装饰", "小型道具"]
        for item in generic:
            if len(items) >= 8:
                break
            if item not in items:
                items.append(item)
        return items

    @staticmethod
    def _candidate_items_from_text(text: str) -> list[str]:
        value = str(text or "")
        out: list[str] = []
        for term in _DISCLOSURE_CANDIDATE_TERMS:
            if term in value and term not in out:
                out.append(term)
        return out[:8]

    @staticmethod
    def _classification_disclosure(scene_goal: str, proposed_items: list[str]) -> str:
        try:
            from plugins.AITool.cai_extensions.agent.scene_element_classifier import (
                route_model_items,
                summarize_classification,
            )
        except Exception:
            return ""
        rows = [{"name": item} for item in proposed_items if str(item or "").strip()]
        if not rows:
            return ""
        _, routes = route_model_items(scene_goal, rows)
        return summarize_classification(routes)


_RUNTIME = LanChatSceneRuntime()


def get_lanchat_scene_runtime() -> LanChatSceneRuntime:
    return _RUNTIME
