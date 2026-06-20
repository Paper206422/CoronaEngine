from __future__ import annotations

import logging
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque


_SENSITIVE_TEXT_MARKERS = (
    "prompt",
    "raw_prompt",
    "provider",
    "model_provider",
    "runtime_context",
    "scheduler_updates",
    "vlm_raw",
    "hidden_debug_ref",
    "debug",
    "job_id",
    "session_id",
    "token",
    "api_key",
)


@dataclass
class HostActionExecutionResult:
    ok: bool
    event_type: str
    message: str
    payload: dict[str, Any]


class LanChatHostActionExecutor:
    """Host-side single-writer queue for confirmed GM actions.

    C++ LANChat remains the room/message source of truth. This executor is the
    Python AI side's minimal bridge from "host confirmed" to "host performs the
    action under EngineWriteGate". v1 intentionally keeps semantic execution
    behind an injectable agent callback instead of parsing free text into
    destructive scene commands here.
    """

    def __init__(
        self,
        corona_engine: Any = None,
        agent_factory: Callable[[], Any] | None = None,
        engine_gate: Any = None,
        structured_action_handler: Callable[[dict[str, Any]], str] | None = None,
        system_sender_id: str = "gm-system",
        system_sender_name: str = "GM",
    ) -> None:
        self._corona_engine = corona_engine
        self._agent_factory = agent_factory
        self._engine_gate = engine_gate or self._default_engine_gate()
        self._structured_action_handler = structured_action_handler
        self._system_sender_id = system_sender_id
        self._system_sender_name = system_sender_name
        self._queue: Deque[dict[str, Any]] = deque()
        self._lock = threading.RLock()
        self._process_lock = threading.RLock()
        self._agent: Any = None
        self._logger = logging.getLogger(__name__)

    def enqueue(self, action_payload: dict[str, Any]) -> int:
        payload = dict(action_payload or {})
        payload.setdefault("queued_at", time.time())
        with self._lock:
            self._queue.append(payload)
            queue_size = len(self._queue)
        self._broadcast_status(payload, "queued_host_action")
        return queue_size

    def process_next(self) -> HostActionExecutionResult | None:
        with self._process_lock:
            with self._lock:
                if not self._queue:
                    return None
                payload = self._queue.popleft()

            self._broadcast_status(payload, "executing_host_action")
            try:
                if self._engine_gate is not None and hasattr(self._engine_gate, "run"):
                    result_text = self._engine_gate.run(self._execute_payload, payload)
                else:
                    result_text = self._execute_payload(payload)
            except Exception as exc:
                self._logger.warning("Host GM action execution failed", exc_info=True)
                result = HostActionExecutionResult(
                    ok=False,
                    event_type="CommandRejected",
                    message="执行失败，请稍后重试或换一个助手。",
                    payload=self._result_payload(payload, "CommandRejected", False, str(exc)),
                )
                self._broadcast_status(payload, "host_action_failed")
                self._send_system_message(result.message, payload, "failed")
                return result

            result_text = str(result_text or "").strip()
            if not result_text or self._looks_failed_result(result_text):
                message = result_text or "host action produced no execution result"
                result = HostActionExecutionResult(
                    ok=False,
                    event_type="CommandRejected",
                    message=message,
                    payload=self._result_payload(payload, "CommandRejected", False, message),
                )
                self._broadcast_status(payload, "host_action_failed")
                self._send_system_message(result.message, payload, "failed")
                return result

            if self._looks_no_delta_result(result_text):
                message = "已接收该请求；这是讨论或状态类内容，未修改场景。"
                result = HostActionExecutionResult(
                    ok=True,
                    event_type="AcceptedNoDelta",
                    message=message,
                    payload=self._result_payload(payload, "AcceptedNoDelta", True, message),
                )
                self._broadcast_status(payload, "accepted_no_delta")
                self._send_system_message(result.message, payload, "accepted_no_delta")
                return result

            message = result_text
            result = HostActionExecutionResult(
                ok=True,
                event_type="SceneDelta",
                message=message,
                payload=self._result_payload(payload, "SceneDelta", True, message),
            )
            self._broadcast_status(payload, "host_action_executed")
            self._send_system_message(result.message, payload, "executed")
            return result

    def enqueue_and_process(self, action_payload: dict[str, Any]) -> HostActionExecutionResult | None:
        self.enqueue(action_payload)
        return self.process_next()

    def _execute_payload(self, payload: dict[str, Any]) -> str:
        if self._structured_action_handler is not None and self._is_structured_seed_plan_action(payload):
            return str(self._structured_action_handler(dict(payload)))

        agent = self._get_agent()
        if agent is None:
            return "GM action accepted by host queue; no executor agent is registered yet."

        source_user_id = str(payload.get("source_user_id") or "unknown")
        raw_intent_text = str(payload.get("intent_text") or payload.get("proposal_id") or "")
        resolved_intent_text = str(payload.get("resolved_intent_text") or "").strip()
        intent_text = resolved_intent_text or raw_intent_text
        conflicts = payload.get("conflicts") or []
        pending = payload.get("pending") or []
        persona = (
            "你是房主侧 host single-writer 执行器。你只能执行已由 GM 和房主确认的多人协作意图；"
            "涉及场景增删改移时必须走现有 agentic 工具/EngineWriteGate 链路，并保留 source_user_id。"
        )
        messages = [
            "【已确认 GM action】",
            "请在 host 机器上按确认意图执行；无法安全执行时说明原因，不要静默覆盖用户对象。",
            f"source_user_id={source_user_id}",
            f"proposal_id={payload.get('proposal_id', '')}",
            f"source_agent_name={payload.get('source_agent_name', '')}",
            f"resolved_from_plan_id={payload.get('resolved_from_plan_id', '')}",
            f"pending={pending}",
            f"conflicts={conflicts}",
            f"用户确认意图：{intent_text}",
        ]
        try:
            return str(agent(persona, messages))
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Host executor agent failed", exc_info=True)
            return self._safe_agent_error_text(exc)

    @staticmethod
    def _is_structured_seed_plan_action(payload: dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if payload.get("seed_plan") or payload.get("plan_id"):
            return str(payload.get("action_type") or "") in {
                "start_generation",
                "execute_seed_plan",
                "post_generation_add",
            }
        return False

    @staticmethod
    def _looks_failed_result(text: str) -> bool:
        lower = text.lower()
        failure_markers = (
            "failed",
            "failure",
            "error",
            "exception",
            "cannot",
            "can't",
            "unable",
            "失败",
            "错误",
            "异常",
            "不能",
            "无法",
            "未能",
            "不可用",
            "已跳过",
        )
        return any(marker in lower for marker in failure_markers)

    @staticmethod
    def _looks_no_delta_result(text: str) -> bool:
        lower = text.lower()
        no_delta_markers = (
            "no executor agent",
            "accepted by host queue",
            "no typed actor delta",
            "未产生 typed actor delta",
            "未注册执行器",
        )
        return any(marker in lower for marker in no_delta_markers)

    def _get_agent(self) -> Any:
        if self._agent is None and self._agent_factory is not None:
            self._agent = self._agent_factory()
        return self._agent

    def _broadcast_status(self, payload: dict[str, Any], status: str) -> None:
        if not self._corona_engine:
            return
        source_user_id = str(payload.get("source_user_id") or "unknown")
        tooltip = self._safe_text(payload.get("intent_text") or payload.get("proposal_id") or status)
        visible_status = self._visible_status_text(status)
        if hasattr(self._corona_engine, "network_send_system_message_ex"):
            try:
                self._corona_engine.network_send_system_message_ex(
                    self._system_sender_id,
                    self._system_sender_name,
                    f"【执行状态】{visible_status}: {tooltip}",
                    "action_status",
                    str(payload.get("proposal_id") or ""),
                    json.dumps(self._action_status_metadata(payload, status), ensure_ascii=False),
                )
            except Exception as exc:
                self._logger.debug("Failed to send structured host action status %s: %s", status, exc)
        if not hasattr(self._corona_engine, "network_broadcast_intent"):
            return
        try:
            self._corona_engine.network_broadcast_intent(
                source_user_id,
                tooltip,
                [0.0, 0.0, 0.0],
                status,
            )
        except Exception as exc:
            self._logger.debug("Failed to broadcast host action status %s: %s", status, exc)

    def _send_system_message(
        self,
        message: str,
        payload: dict[str, Any] | None = None,
        status: str = "",
    ) -> None:
        if not self._corona_engine:
            return
        payload = payload or {}
        safe_message = self._safe_text(message)
        try:
            if hasattr(self._corona_engine, "network_send_system_message_ex"):
                self._corona_engine.network_send_system_message_ex(
                    self._system_sender_id,
                    self._system_sender_name,
                    f"【执行结果】{safe_message}",
                    "action_status",
                    str(payload.get("proposal_id") or ""),
                    json.dumps({
                        **self._action_status_metadata(payload, status or "executed"),
                        "message": safe_message,
                    }, ensure_ascii=False),
                )
            else:
                self._corona_engine.network_send_system_message(
                    self._system_sender_id,
                    self._system_sender_name,
                    f"【执行结果】{safe_message}",
                )
        except Exception as exc:
            self._logger.debug("Failed to send host action system message: %s", exc)

    @classmethod
    def _action_status_metadata(cls, payload: dict[str, Any], status: str) -> dict[str, Any]:
        return {
            "status": status,
            "proposal_id": str(payload.get("proposal_id") or ""),
            "source_user_id": str(payload.get("source_user_id") or ""),
            "target_agent_id": str(payload.get("target_agent_id") or ""),
            "intent_text": cls._safe_text(payload.get("intent_text") or ""),
            "execution": "host_single_writer",
        }

    @classmethod
    def _result_payload(
        cls,
        payload: dict[str, Any],
        event_type: str,
        ok: bool,
        message: str,
    ) -> dict[str, Any]:
        safe_message = cls._safe_text(message)
        return {
            "event_type": event_type,
            "ok": ok,
            "source_user_id": str(payload.get("source_user_id") or ""),
            "proposal_id": str(payload.get("proposal_id") or ""),
            "intent_text": cls._safe_text(payload.get("intent_text") or ""),
            "message": safe_message,
            "timestamp": time.time(),
        }

    @staticmethod
    def _visible_status_text(status: str) -> str:
        return {
            "queued_host_action": "已排队",
            "executing_host_action": "执行中",
            "host_action_executed": "已完成",
            "host_action_failed": "执行失败",
            "accepted_no_delta": "未修改场景",
            "failed": "执行失败",
            "executed": "已完成",
        }.get(status, status)

    @staticmethod
    def _safe_agent_error_text(exc: Exception) -> str:
        text = str(exc)
        if any(marker in text for marker in ("Invalid Token", "request id", "rix_api_error", "stack trace")):
            return "当前模型服务不可用，已跳过该助手回复。"
        return "该助手暂时无法响应，请稍后重试或换一个助手。"

    @staticmethod
    def _safe_text(value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        lower = text.lower()
        if any(marker in lower for marker in _SENSITIVE_TEXT_MARKERS):
            cut_points = [
                lower.find(marker)
                for marker in _SENSITIVE_TEXT_MARKERS
                if lower.find(marker) >= 0
            ]
            first = min(cut_points) if cut_points else 0
            keep = text[:first].strip(" \t\r\n,;；。")
            return keep or "已收到确认动作，内部执行细节已隐藏。"
        return text

    @staticmethod
    def _default_engine_gate() -> Any:
        try:
            from plugins.AITool.cai_extensions.agent.engine_write_gate import get_engine_write_gate

            return get_engine_write_gate()
        except Exception:
            return None


__all__ = ["HostActionExecutionResult", "LanChatHostActionExecutor"]
