from __future__ import annotations

import logging
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .lanchat_summary_service import DiscussionState, LANChatSummaryService


@dataclass
class AgentOrchestrationResult:
    """Result sent back through C++ LANChat."""

    text: str
    sender_id: str
    sender_name: str
    discussion_state: DiscussionState
    proposal: bool = False
    action_payload: dict[str, Any] | None = None


class LanChatAgentOrchestrator:
    """Python AI/GM layer for C++ LANChat agent triggers.

    C++ owns room state and reliable transport. This class only performs
    semantic orchestration and returns a reply payload for the worker to send
    through C++.
    """

    _GM_NAMES = {"gm", "主持人", "裁判", "gm agent", "game master"}
    _CONFLICT_WORDS = ("冲突", "同时", "覆盖", "不同意", "反对", "抢", "都要")
    _CONFIRM_WORDS = ("确认", "同意", "按方案", "执行", "可以")
    _REJECT_WORDS = ("拒绝", "取消", "不要", "暂停")
    _MAJOR_ACTION_WORDS = ("删除", "重置", "清空", "整体", "主题", "大件", "核心家具")
    _PROPOSAL_ID_PATTERN = re.compile(r"\bgm-\d+\b", re.I)

    def __init__(
        self,
        agent_factory: Callable[[], Any] | None = None,
        summary_service: LANChatSummaryService | None = None,
        system_sender_id: str = "gm-system",
        system_sender_name: str = "GM",
    ) -> None:
        self._agent_factory = agent_factory or self._default_agent_factory
        self._summary_service = summary_service or LANChatSummaryService()
        self._system_sender_id = system_sender_id
        self._system_sender_name = system_sender_name
        self._agent: Any = None
        self._pending_proposal: dict[str, Any] | None = None
        self._last_confirmed_action: dict[str, Any] | None = None
        self._processed_proposals: dict[str, str] = {}
        self._logger = logging.getLogger(__name__)

    @property
    def summary_state(self) -> DiscussionState:
        return self._summary_service.state

    def handle_trigger(self, trigger: dict[str, Any]) -> AgentOrchestrationResult:
        history = self._history_from_trigger(trigger)
        state = self._summary_service.monitor(history)
        text = str(trigger.get("text") or "")

        confirmation = self._consume_confirmation(text, trigger)
        if confirmation is not None:
            return AgentOrchestrationResult(
                text=confirmation,
                sender_id=self._system_sender_id,
                sender_name=self._system_sender_name,
                discussion_state=state,
                proposal=False,
                action_payload=self._last_confirmed_action,
            )

        if self._needs_gm_proposal(trigger, state):
            proposal_text = self._build_gm_proposal(trigger, state)
            return AgentOrchestrationResult(
                text=proposal_text,
                sender_id=self._system_sender_id,
                sender_name=self._system_sender_name,
                discussion_state=state,
                proposal=True,
                action_payload=dict(self._pending_proposal or {}),
            )

        return AgentOrchestrationResult(
            text=self._run_role_agent(trigger, state),
            sender_id=str(trigger.get("agent_id") or "agent"),
            sender_name=str(trigger.get("agent_name") or "Agent"),
            discussion_state=state,
            proposal=False,
        )

    def _needs_gm_proposal(self, trigger: dict[str, Any], state: DiscussionState) -> bool:
        agent_name = str(trigger.get("agent_name") or "").strip().lower()
        text = str(trigger.get("text") or "")
        if agent_name in self._GM_NAMES:
            return True
        if state.conflicts:
            return True
        if any(word in text for word in self._CONFLICT_WORDS):
            return True
        # 单人/无冲突的明确增删改移应回到普通 agentic 工具通道，避免
        # GM 只发 proposal 但没有执行队列时吞掉用户操作。多人重大操作仍需 GM。
        if any(word in text for word in self._MAJOR_ACTION_WORDS) and self._is_multi_user(trigger):
            return True
        return False

    def _build_gm_proposal(self, trigger: dict[str, Any], state: DiscussionState) -> str:
        requester = str(trigger.get("sender_name") or trigger.get("sender_id") or "用户")
        text = str(trigger.get("text") or "").strip()
        proposal_id = f"gm-{int(time.time() * 1000)}"
        pending = state.pending_intents or [f"{requester}: {text}"]
        conflicts = state.conflicts or self._infer_pair_conflicts(self._history_from_trigger(trigger))
        if not conflicts:
            conflicts = ["暂无明确对象冲突，但该操作可能影响多人共识或核心布局。"]

        self._pending_proposal = {
            "proposal_id": proposal_id,
            "correlation_id": proposal_id,
            "status": "pending_host_confirmation",
            "source_user_id": str(trigger.get("sender_id") or ""),
            "target_agent_id": str(trigger.get("agent_id") or ""),
            "requester": requester,
            "intent_text": text,
            "pending": pending,
            "conflicts": conflicts,
            "requires_host_confirm": True,
            "execution": "host_single_writer",
        }

        return (
            f"【GM 提案 {proposal_id}】\n"
            f"我理解当前请求来自 {requester}：{text}\n"
            f"待处理意图：{self._join_lines(pending)}\n"
            f"潜在冲突：{self._join_lines(conflicts)}\n"
            "建议：先保留最近用户明确操作，Agent 物体让位；涉及删除、重置或覆盖多人意见时由房主确认。\n"
            f"房主可回复：@GM 确认 {proposal_id} / @GM 拒绝 {proposal_id}。"
        )

    def _consume_confirmation(self, text: str, trigger: dict[str, Any] | None = None) -> str | None:
        self._last_confirmed_action = None
        trigger = trigger or {}
        metadata = self._metadata_from_trigger(trigger)
        kind = str(trigger.get("message_kind") or "").strip().lower()
        decision = str(metadata.get("decision") or "").strip().lower()
        is_structured_confirmation = kind == "confirmation"
        is_confirm = (
            decision in {"confirm", "confirmed", "yes", "accept"}
            or any(word in text for word in self._CONFIRM_WORDS)
        )
        is_reject = (
            decision in {"reject", "rejected", "no", "cancel"}
            or any(word in text for word in self._REJECT_WORDS)
        )
        if is_structured_confirmation and not is_confirm and not is_reject:
            return "【GM】结构化确认缺少 decision=confirm|reject，未进入执行队列。"
        if not is_confirm and not is_reject:
            return None
        mentioned_ids = {match.group(0).lower() for match in self._PROPOSAL_ID_PATTERN.finditer(text)}
        correlation_id = str(trigger.get("correlation_id") or metadata.get("proposal_id") or "").strip().lower()
        if correlation_id:
            mentioned_ids.add(correlation_id)
        processed_matches = [
            item for item in sorted(mentioned_ids)
            if item in self._processed_proposals
        ]
        if processed_matches:
            replay_id = processed_matches[0]
            status = self._processed_proposals[replay_id]
            return f"【GM】提案 {replay_id} 已处理（{status}），不会重复入队。"
        if self._pending_proposal is None:
            return None
        pid = str(self._pending_proposal.get("proposal_id") or "")
        if mentioned_ids and pid.lower() not in mentioned_ids:
            for item in mentioned_ids:
                self._processed_proposals.setdefault(item, "mismatched")
            return f"【GM】确认编号不匹配，当前待确认提案是 {pid}。请回复：@GM 确认 {pid} 或 @GM 拒绝 {pid}。"
        host_check = self._trusted_host_confirmation(trigger)
        if host_check is False:
            return f"【GM】只有房主可以确认 {pid}；该请求没有进入 host 执行队列。"
        if is_confirm:
            self._last_confirmed_action = dict(self._pending_proposal)
            self._last_confirmed_action["status"] = "confirmed"
            if not mentioned_ids:
                self._last_confirmed_action["confirmation_mode"] = "bare_text_fallback"
            elif is_structured_confirmation:
                self._last_confirmed_action["confirmation_mode"] = "structured_confirmation"
            elif host_check is None:
                self._last_confirmed_action["confirmation_mode"] = "proposal_id_without_verified_host"
            else:
                self._last_confirmed_action["confirmation_mode"] = "verified_host"
            self._last_confirmed_action["requires_host_confirm"] = False
            self._pending_proposal = None
            self._processed_proposals[pid.lower()] = "confirmed"
            return f"【GM】已确认 {pid}，后续由 host 单写者执行；执行时保留真实 source_user_id。"
        if is_reject:
            self._last_confirmed_action = dict(self._pending_proposal)
            self._last_confirmed_action["status"] = "rejected"
            self._pending_proposal = None
            self._processed_proposals[pid.lower()] = "rejected"
            return f"【GM】已取消 {pid}，不会执行该提案。"
        return None

    @staticmethod
    def _metadata_from_trigger(trigger: dict[str, Any]) -> dict[str, Any]:
        metadata = trigger.get("metadata")
        if isinstance(metadata, dict):
            return metadata
        raw = trigger.get("metadata_json")
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(str(raw))
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _run_role_agent(self, trigger: dict[str, Any], state: DiscussionState) -> str:
        agent = self._get_agent()
        persona = str(trigger.get("persona") or "")
        messages = self._messages_from_trigger(trigger)
        agent_name = str(trigger.get("agent_name") or "Agent")
        latest = str(trigger.get("text") or "")
        messages = [
            "【当前点名上下文】\n"
            f"本轮明确被 @ 的 AI 助手是：{agent_name}。\n"
            f"最新用户消息是发给你的：{latest}\n"
            "请以该助手身份回应，不要因为历史中出现其他 @对象 而拒绝执行或越位判断。"
        ] + messages
        context = state.to_prompt_context()
        if context:
            messages = [f"【静默监听摘要】\n{context}"] + messages
        return str(agent(persona, messages))

    def _get_agent(self) -> Any:
        if self._agent is None:
            self._agent = self._agent_factory()
        return self._agent

    @staticmethod
    def _history_from_trigger(trigger: dict[str, Any]) -> list[dict[str, Any]]:
        history = trigger.get("history") or []
        return [item for item in history if isinstance(item, dict)]

    @staticmethod
    def _messages_from_trigger(trigger: dict[str, Any]) -> list[str]:
        messages: list[str] = []
        for item in LanChatAgentOrchestrator._history_from_trigger(trigger):
            sender = str(item.get("from") or item.get("sender_name") or "")
            text = str(item.get("text") or "")
            if text:
                messages.append(f"{sender}: {text}" if sender else text)

        text = str(trigger.get("text") or "")
        if text and text not in messages:
            messages.append(text)
        return messages

    @staticmethod
    def _infer_pair_conflicts(history: list[dict[str, Any]]) -> list[str]:
        object_mentions: dict[str, list[str]] = {}
        pattern = re.compile(r"(桌子|椅子|门|墙|蒙古包|篝火|灯|床|沙发|table|chair|door|wall|fire)", re.I)
        for item in history[-8:]:
            sender = str(item.get("from") or item.get("sender_name") or item.get("sender_id") or "")
            text = str(item.get("text") or "")
            for match in pattern.findall(text):
                key = match.lower()
                object_mentions.setdefault(key, []).append(sender or text[:12])
        conflicts = []
        for key, speakers in object_mentions.items():
            unique = [s for i, s in enumerate(speakers) if s and s not in speakers[:i]]
            if len(unique) >= 2:
                conflicts.append(f"{key}: " + " / ".join(unique[:3]))
        return conflicts

    @staticmethod
    def _is_multi_user(trigger: dict[str, Any]) -> bool:
        speakers: set[str] = set()
        sender = str(trigger.get("sender_id") or trigger.get("sender_name") or "")
        sender_name = str(trigger.get("sender_name") or "")
        if sender:
            speakers.add(sender)
        for item in LanChatAgentOrchestrator._history_from_trigger(trigger):
            speaker = str(
                item.get("sender_id")
                or item.get("from")
                or item.get("sender_name")
                or ""
            )
            if speaker and sender_name and speaker == sender_name and sender:
                speaker = sender
            if speaker:
                speakers.add(speaker)
        return len(speakers) >= 2

    @staticmethod
    def _trusted_host_confirmation(trigger: dict[str, Any]) -> bool | None:
        """Return True/False only when trigger carries an explicit room role."""
        for key in ("sender_role", "room_role", "role"):
            if key not in trigger:
                continue
            role = str(trigger.get(key) or "").strip().lower()
            if role:
                return role in {"host", "owner", "room_host", "房主"}
        for key in ("is_host", "is_room_host", "sender_is_host"):
            if key in trigger:
                return bool(trigger.get(key))
        return None

    @staticmethod
    def _join_lines(items: list[str]) -> str:
        return "；".join(items) if items else "无"

    @staticmethod
    def _default_agent_factory() -> Any:
        from plugins.AITool.cai_extensions.agent.agent_adapter import create_master_agent

        return create_master_agent()


__all__ = ["AgentOrchestrationResult", "LanChatAgentOrchestrator"]
