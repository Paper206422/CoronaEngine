"""Plan 协商状态机 — 房间级的"讨论 → Plan协商 → 定稿"多阶段流程。

流程：
  DISCUSSING（讨论中）
    群聊 → 适当时机 AI 主动问"要执行 XXX 方案吗？"
    任何人说"执行" → 进入 PLANNING
  PLANNING（Plan协商中，不直接执行）
    1. 汇总进入前的全部聊天记录 → 生成 plan v1 → 展示 + 问"要执行吗？"
    2. 之后每条新消息实时修订：
       - 新意见 → 在当前 plan 上修订 → 展示新版 + 再问
       - 否定   → 先输出当前 plan 问是否执行，纳入否定意见继续优化
       - 确认   → plan 定稿（FINALIZED），不自动建模导入

AI 调用通过注入的 ai_chat 回调（(prompt)->str）完成，复用 SummaryService 通道。
所有状态在房主进程内（单房单实例）。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 状态
STATE_DISCUSSING = "discussing"
STATE_PLANNING = "planning"
STATE_FINALIZED = "finalized"

# 触发词
_EXECUTE_TRIGGERS = [
    r"执行", r"就这(?:个|样)(?:方案|吧)?", r"开始(?:吧|执行|生成)?",
    r"按这个来", r"可以(?:了|开始)", r"动手", r"上吧",
]
_CONFIRM_TRIGGERS = [
    r"^确认", r"没问题", r"就这样定", r"可以了?$", r"OK$", r"ok$",
    r"同意", r"通过", r"行(?:吧)?$",
]
_NEGATE_TRIGGERS = [
    r"不(?:对|行|好|要)", r"别", r"换(?:成|个)", r"改(?:成|为|一下|改)",
    r"不是(?:这个|这样)", r"重新", r"取消", r"否决", r"反对",
]
# 用户主动询问当前方案（明确要求输出 → 立即输出）
_ASK_PLAN_TRIGGERS = [
    r"(?:现在|当前|目前)?(?:的)?(?:方案|plan|计划)(?:是什么|是啥|呢|怎么样)",
    r"(?:读|说|看|念)(?:一下|下)?(?:当前|现在)?(?:的)?方案",
    r"总结(?:一?下)?(?:方案|现在)?", r"汇总(?:一?下)?", r"梳理(?:一?下)?",
    r"到哪(?:一?步|了)", r"进度",
]

_PLAN_SYSTEM = (
    "你是多人协作场景设计的方案整理助手。根据【全部讨论记录】和【当前方案】(若有)，"
    "整理/修订出一份清晰的场景执行方案 plan。\n"
    "输出 JSON：{\"scene_name\":\"\",\"style\":\"风格概述\","
    "\"items\":[{\"name\":\"物体\",\"note\":\"位置/数量/要求\"}],"
    "\"layout\":\"布局要点\",\"open_questions\":[\"待确认的点\"]}\n"
    "规则：综合所有人的意见；若有新意见或否定，在原方案上修订；items 是要放入场景的物体清单。"
    "只输出 JSON，不要解释。"
)

# 输出时机判断：让 LLM 决定"这条消息后，现在是否适合输出/更新方案"
_TIMING_SYSTEM = (
    "你在协助多人讨论场景方案。当前已有一份方案在协商中。根据【最新消息】判断助手现在该怎么做。\n"
    "只输出 JSON：{\"emit\":true/false,\"changed\":true/false,\"reason\":\"简短\"}\n"
    "判断规则：\n"
    "- emit=true：现在适合输出/重述方案给大家看。以下情况应 emit：用户在问当前方案、"
    "提出了重大修改或否定、讨论告一段落需要确认。\n"
    "- emit=false：只是闲聊、零碎补充、还在发散讨论，不打断。\n"
    "- changed=true：这条消息带来了对方案内容的实质改动（需重新生成方案）。\n"
    "只输出 JSON。"
)


class PlanSession:
    """单个房间的 Plan 协商会话状态机。"""

    # 积攒多少条"有效新意见"后即使没人问也主动输出一次
    _EMIT_AFTER_N_CHANGES = 3
    # 讨论停顿多少秒后主动输出一次当前方案
    _IDLE_EMIT_SECONDS = 12.0

    def __init__(self, ai_chat: Optional[Callable[[str], str]] = None) -> None:
        self._ai_chat = ai_chat
        self.state: str = STATE_DISCUSSING
        self.plan: Optional[Dict[str, Any]] = None          # 当前 plan（dict）
        self.plan_version: int = 0
        self._entered_planning_ts: float = 0.0
        # 进入 Planning 时冻结的"之前全部记录"，加上 Planning 期间的新消息
        self._planning_msgs: List[Dict[str, Any]] = []
        # 静默累积：未输出的有效改动计数 + 最后一条消息时间（用于停顿检测）
        self._pending_changes: int = 0
        self._last_msg_ts: float = 0.0
        self._last_emit_version: int = 0  # 上次已输出给用户的 plan 版本

    # ── 触发判别（规则，零成本）─────────────────────────────────

    @staticmethod
    def is_execute_trigger(text: str) -> bool:
        t = (text or "").strip()
        return any(re.search(p, t) for p in _EXECUTE_TRIGGERS)

    @staticmethod
    def is_ask_plan_trigger(text: str) -> bool:
        t = (text or "").strip()
        return any(re.search(p, t) for p in _ASK_PLAN_TRIGGERS)

    @staticmethod
    def is_confirm_trigger(text: str) -> bool:
        t = (text or "").strip()
        return any(re.search(p, t) for p in _CONFIRM_TRIGGERS)

    @staticmethod
    def is_negate_trigger(text: str) -> bool:
        t = (text or "").strip()
        return any(re.search(p, t) for p in _NEGATE_TRIGGERS)

    # ── 阶段操作 ────────────────────────────────────────────────

    def enter_planning(self, all_history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """从讨论进入 Plan 协商：汇总全部历史生成 plan v1。"""
        self.state = STATE_PLANNING
        self._entered_planning_ts = time.time()
        self._planning_msgs = list(all_history)  # 冻结进入前的全部记录
        self.plan = self._generate_plan(self._planning_msgs, prev_plan=None)
        if self.plan:
            self.plan_version = 1
            logger.info("[PlanSession] 进入 Planning，生成 plan v1: %s",
                        self.plan.get("scene_name", "?"))
        return self.plan

    def on_planning_message(self, user: str, text: str) -> Dict[str, Any]:
        """Planning 阶段每条新消息：静默累积，由 agent 判断"何时该输出方案"。

        返回 {"action": "confirmed|revised|asked|silent", "plan": ..., "message": ...}
        - silent : 累积中，不输出（最常见，避免刷屏）
        - revised: 到了输出时机，重新生成并展示方案
        - asked  : 用户主动问方案，直接展示当前方案
        - confirmed: 定稿
        """
        import time as _t
        self._planning_msgs.append({"from": user, "text": text, "ts": int(_t.time())})
        self._last_msg_ts = _t.time()

        # 1. 确认 → 定稿（最高优先）
        if self.is_confirm_trigger(text) and not self.is_negate_trigger(text):
            self.state = STATE_FINALIZED
            logger.info("[PlanSession] plan 定稿 (v%d)", self.plan_version)
            return {"action": "confirmed", "plan": self.plan, "message": self._format_final()}

        # 2. 用户主动询问方案 → 立即输出当前 plan（不重新生成）
        if self.is_ask_plan_trigger(text):
            self._last_emit_version = self.plan_version
            self._pending_changes = 0
            return {"action": "asked", "plan": self.plan,
                    "message": self._format_plan(prefix="📋 当前方案")}

        # 3. 否定 = 重大变更 → 立即修订并输出
        if self.is_negate_trigger(text):
            self._regenerate()
            self._last_emit_version = self.plan_version
            self._pending_changes = 0
            return {"action": "revised", "plan": self.plan,
                    "message": self._format_plan(prefix="📝 已按新意见修订方案")}

        # 4. 其余消息：让 LLM 判断"现在该不该输出 / 是否实质改动"
        decision = self._judge_timing(text)
        if decision.get("changed"):
            self._pending_changes += 1
        # 输出时机：LLM 说该输出 / 积攒够 N 条改动
        should_emit = decision.get("emit") or self._pending_changes >= self._EMIT_AFTER_N_CHANGES
        if should_emit:
            self._regenerate()
            self._last_emit_version = self.plan_version
            self._pending_changes = 0
            return {"action": "revised", "plan": self.plan,
                    "message": self._format_plan(prefix="📝 方案更新")}

        # 静默累积，不打扰
        logger.info("[PlanSession] 静默累积（pending=%d, reason=%s）",
                    self._pending_changes, decision.get("reason", ""))
        return {"action": "silent", "plan": self.plan, "message": ""}

    def check_idle_emit(self) -> Optional[Dict[str, Any]]:
        """讨论停顿检测：若 Planning 中已静默累积改动且超过停顿阈值，输出一次。

        由 ChatServer 用定时器/延迟任务调用。无需输出时返回 None。
        """
        import time as _t
        if self.state != STATE_PLANNING:
            return None
        if self._pending_changes <= 0:
            return None
        if _t.time() - self._last_msg_ts < self._IDLE_EMIT_SECONDS:
            return None
        # 停顿够久且有累积改动 → 输出
        self._regenerate()
        self._last_emit_version = self.plan_version
        self._pending_changes = 0
        logger.info("[PlanSession] 讨论停顿，主动输出 plan v%d", self.plan_version)
        return {"action": "revised", "plan": self.plan,
                "message": self._format_plan(prefix="💬 讨论暂歇，整理一下当前方案")}

    def _regenerate(self) -> None:
        """基于累积的全部消息重新生成 plan，版本号+1。"""
        revised = self._generate_plan(self._planning_msgs, prev_plan=self.plan)
        if revised and revised != self.plan:
            self.plan = revised
            self.plan_version += 1

    def _judge_timing(self, text: str) -> Dict[str, Any]:
        """LLM 判断这条消息是否到了输出时机 / 是否实质改动。

        失败/无 LLM 时保守返回不输出、不算改动（靠规则触发兜底）。
        """
        if not self._ai_chat:
            # 无 LLM：把"看起来像新增物体/要求"的当作一次改动
            changed = bool(re.search(r"(?:加|添|放|要|换|改|删|移|生成|做|搞)", text))
            return {"emit": False, "changed": changed, "reason": "no_llm"}
        try:
            recent = "\n".join(f"{m.get('from','?')}: {m.get('text','')}"
                               for m in self._planning_msgs[-6:])
            plan_brief = json.dumps(self.plan, ensure_ascii=False)[:300] if self.plan else "（无）"
            prompt = (f"{_TIMING_SYSTEM}\n\n【当前方案摘要】\n{plan_brief}\n\n"
                      f"【最近消息】\n{recent}\n\n【最新消息】\n{text}\n\n【输出】")
            raw = self._ai_chat(prompt)
            d = self._parse_json(raw) or {}
            return {"emit": bool(d.get("emit", False)),
                    "changed": bool(d.get("changed", False)),
                    "reason": str(d.get("reason", ""))}
        except Exception as e:
            logger.warning("[PlanSession] 时机判断失败: %s", e)
            return {"emit": False, "changed": False, "reason": f"error:{e}"}

    def reset(self) -> None:
        self.state = STATE_DISCUSSING
        self.plan = None
        self.plan_version = 0
        self._planning_msgs.clear()
        self._pending_changes = 0
        self._last_msg_ts = 0.0
        self._last_emit_version = 0

    # ── LLM 生成 plan ───────────────────────────────────────────

    def _generate_plan(self, msgs: List[Dict[str, Any]],
                       prev_plan: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not self._ai_chat:
            # 无 LLM：用规则兜底，至少抽出物体清单
            return self._rule_plan(msgs, prev_plan)
        try:
            history = "\n".join(f"{m.get('from','?')}: {m.get('text','')}" for m in msgs[-60:])
            prev = json.dumps(prev_plan, ensure_ascii=False) if prev_plan else "（无，首次生成）"
            prompt = (f"{_PLAN_SYSTEM}\n\n【全部讨论记录】\n{history}\n\n"
                      f"【当前方案】\n{prev}\n\n【输出修订后的方案 JSON】")
            raw = self._ai_chat(prompt)
            plan = self._parse_json(raw)
            return plan or self._rule_plan(msgs, prev_plan)
        except Exception as e:
            logger.warning("[PlanSession] 生成 plan 失败，规则兜底: %s", e)
            return self._rule_plan(msgs, prev_plan)

    def _rule_plan(self, msgs: List[Dict[str, Any]],
                   prev_plan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """无 LLM 时的兜底：从消息里正则抽物体名。"""
        items = []
        seen = set()
        for m in msgs:
            for mt in re.finditer(r"(?:加个?|添加|放个?|要个?|生成)\s*([^\s，。,.、]{1,8})", m.get("text", "")):
                name = mt.group(1).strip()
                if name and name not in seen:
                    seen.add(name)
                    items.append({"name": name, "note": ""})
        base = prev_plan or {"scene_name": "讨论场景", "style": "", "layout": "", "open_questions": []}
        base["items"] = items or base.get("items", [])
        return base

    def _parse_json(self, raw: str) -> Optional[Dict[str, Any]]:
        text = (raw or "").strip()
        if "```" in text:
            s = text.find("{"); e = text.rfind("}")
            if s != -1 and e != -1:
                text = text[s:e + 1]
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    # ── 展示格式化 ──────────────────────────────────────────────

    def _format_plan(self, prefix: str = "📋 当前方案") -> str:
        p = self.plan or {}
        lines = [f"{prefix}（v{self.plan_version}）"]
        if p.get("scene_name"):
            lines.append(f"  场景：{p['scene_name']}")
        if p.get("style"):
            lines.append(f"  风格：{p['style']}")
        items = p.get("items", [])
        if items:
            lines.append("  物品清单：")
            for it in items[:20]:
                note = f"（{it['note']}）" if it.get("note") else ""
                lines.append(f"    • {it.get('name', '?')}{note}")
        if p.get("layout"):
            lines.append(f"  布局：{p['layout']}")
        oq = p.get("open_questions", [])
        if oq:
            lines.append("  待确认：" + "；".join(oq[:3]))
        lines.append("\n这样可以吗？回复「确认」定稿，或继续提出修改意见。")
        return "\n".join(lines)

    def _format_final(self) -> str:
        p = self.plan or {}
        items = "、".join(it.get("name", "?") for it in p.get("items", [])[:20])
        return (f"✅ 方案已定稿（v{self.plan_version}）：{p.get('scene_name', '场景')}\n"
                f"包含：{items}\n"
                f"如需生成，请说「开始执行/生成场景」。")


__all__ = ["PlanSession", "STATE_DISCUSSING", "STATE_PLANNING", "STATE_FINALIZED"]
