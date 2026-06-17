from __future__ import annotations

import logging
import json
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque


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
        system_sender_id: str = "gm-system",
        system_sender_name: str = "GM",
    ) -> None:
        self._corona_engine = corona_engine
        self._agent_factory = agent_factory
        self._engine_gate = engine_gate or self._default_engine_gate()
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
                self._logger.debug("Host GM action execution failed: %s", exc)
                result = HostActionExecutionResult(
                    ok=False,
                    event_type="CommandRejected",
                    message=f"host action failed: {exc}",
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
                message = f"{result_text}（未产生 typed actor delta；peer 同步以底层 SceneDelta 为准。）"
                result = HostActionExecutionResult(
                    ok=True,
                    event_type="AcceptedNoDelta",
                    message=message,
                    payload=self._result_payload(payload, "AcceptedNoDelta", True, message),
                )
                self._broadcast_status(payload, "accepted_no_delta")
                self._send_system_message(result.message, payload, "accepted_no_delta")
                return result

            message = f"{result_text}（语义执行完成；peer actor sync 以底层 SceneDelta 为准。）"
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
        agent = self._get_agent()
        if agent is None:
            return "GM action accepted by host queue; no executor agent is registered yet."

        source_user_id = str(payload.get("source_user_id") or "unknown")
        intent_text = str(payload.get("intent_text") or payload.get("proposal_id") or "")
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
            f"pending={pending}",
            f"conflicts={conflicts}",
            f"用户确认意图：{intent_text}",
        ]
        return str(agent(persona, messages))

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
        tooltip = str(payload.get("intent_text") or payload.get("proposal_id") or status)
        if hasattr(self._corona_engine, "network_send_system_message_ex"):
            try:
                self._corona_engine.network_send_system_message_ex(
                    self._system_sender_id,
                    self._system_sender_name,
                    f"[Host status] {status}: {tooltip}",
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
        try:
            if hasattr(self._corona_engine, "network_send_system_message_ex"):
                self._corona_engine.network_send_system_message_ex(
                    self._system_sender_id,
                    self._system_sender_name,
                    f"【Host 执行结果】{message}",
                    "action_status",
                    str(payload.get("proposal_id") or ""),
                    json.dumps({
                        **self._action_status_metadata(payload, status or "executed"),
                        "message": message,
                    }, ensure_ascii=False),
                )
            else:
                self._corona_engine.network_send_system_message(
                    self._system_sender_id,
                    self._system_sender_name,
                    f"【Host 执行结果】{message}",
                )
        except Exception as exc:
            self._logger.debug("Failed to send host action system message: %s", exc)

    @staticmethod
    def _action_status_metadata(payload: dict[str, Any], status: str) -> dict[str, Any]:
        return {
            "status": status,
            "proposal_id": str(payload.get("proposal_id") or ""),
            "source_user_id": str(payload.get("source_user_id") or ""),
            "target_agent_id": str(payload.get("target_agent_id") or ""),
            "intent_text": str(payload.get("intent_text") or ""),
            "execution": "host_single_writer",
        }

    @staticmethod
    def _result_payload(
        payload: dict[str, Any],
        event_type: str,
        ok: bool,
        message: str,
    ) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "ok": ok,
            "source_user_id": str(payload.get("source_user_id") or ""),
            "proposal_id": str(payload.get("proposal_id") or ""),
            "intent_text": str(payload.get("intent_text") or ""),
            "message": message,
            "timestamp": time.time(),
        }

    @staticmethod
    def _default_engine_gate() -> Any:
        try:
            from plugins.AITool.cai_extensions.agent.engine_write_gate import get_engine_write_gate

            return get_engine_write_gate()
        except Exception:
            return None


__all__ = ["HostActionExecutionResult", "LanChatHostActionExecutor"]
