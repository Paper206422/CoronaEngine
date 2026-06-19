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
        parts = [
            f"用户确认开始生成：{confirmation.scene_goal}",
            "建议物体清单：" + "、".join(confirmation.proposed_items),
        ]
        if confirmation.constraints:
            parts.append("补充要求：" + "；".join(confirmation.constraints))
        parts.append("最新指令：" + user_text)
        return "\n".join(parts)

    def _format_confirmation(self, confirmation: PlanningConfirmation, *, updated: bool = False) -> str:
        items = confirmation.proposed_items[:8]
        while len(items) < 6:
            filler = ["主体物件", "支撑物件", "灯光装饰", "导视牌", "储物道具", "活动区装饰"][len(items)]
            if filler not in items:
                items.append(filler)
        prefix = "我已更新方案。" if updated else f"我理解你的目标是：{confirmation.scene_goal}。"
        lines = [
            prefix,
            "",
            "建议先做：",
            "1. 场地：确定主要活动区和通行动线",
            "2. 主体：" + "、".join(items[:2]),
            "3. 支撑：" + "、".join(items[2:4]),
            "4. 装饰：" + "、".join(items[4:8]),
            "",
            "你可以回复：",
            "- 确认开始",
            "- 补充：...",
            "- 直接生成",
        ]
        disclosure = self._classification_disclosure(confirmation.scene_goal, confirmation.proposed_items)
        if disclosure:
            lines.extend(["", "提炼结果：", disclosure])
        return "\n".join(lines)

    @staticmethod
    def _extract_scene_goal(text: str) -> str:
        value = re.sub(r"^.*?(我有一个计划[，,]?)", "", str(text or "")).strip()
        value = re.sub(r"^(建立|搭建|设计|规划|做)一个", "", value).strip()
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
        item = re.sub(r"^(?:后面|后续|接下来|之后|再|新增|增加|添加|加入|加|补|一个|一只|一座|一盏|一张|一把)+", "", item).strip()
        item = re.sub(r"^(?:个|只|座|盏|张|把)", "", item).strip()
        item = re.sub(r"(?:要|得|需要|应该|放在|摆在).*$", "", item).strip()
        return item

    @classmethod
    def _seed_items_from_text(cls, text: str) -> list[str]:
        items = cls._extract_requested_items(text)
        for item in cls._candidate_items_from_text(text):
            if item not in items:
                items.append(item)
        generic = ["主体建筑或摊位", "环境主体", "功能物件", "灯光装饰", "导视牌", "小型道具", "活动区装饰"]
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
