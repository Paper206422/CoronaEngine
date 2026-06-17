from __future__ import annotations

import logging
import json
import os
import threading
from typing import Any, Callable

from .lanchat_agent_orchestrator import LanChatAgentOrchestrator
from .lanchat_host_action_executor import LanChatHostActionExecutor


class LANChatAgentWorker:
    """Poll C++ LANChat agent triggers and return replies through C++."""

    def __init__(
        self,
        corona_engine: Any = None,
        agent_factory: Callable[[], Any] | None = None,
        host_action_executor: Any = None,
        sleep_seconds: float = 0.1,
        async_agent_execution: bool | None = None,
    ) -> None:
        self._corona_engine = corona_engine
        self._agent_factory = agent_factory
        self._host_action_executor = host_action_executor
        self._sleep_seconds = sleep_seconds
        self._async_agent_execution = (
            os.getenv("LANCHAT_AGENT_ASYNC", "1") == "1"
            if async_agent_execution is None
            else bool(async_agent_execution)
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._orchestrator: LanChatAgentOrchestrator | None = None
        self._agent_call_lock = threading.RLock()
        self._logger = logging.getLogger(__name__)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._has_engine_api():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="LANChatAgentWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def process_once(self) -> bool:
        if not self._has_engine_api():
            return False

        try:
            trigger = self._corona_engine.network_pop_lanchat_agent_trigger()
        except Exception as exc:
            self._logger.debug("Failed to poll LANChat agent trigger: %s", exc)
            return False

        if not trigger:
            return False

        if self._async_agent_execution:
            threading.Thread(
                target=self._process_trigger,
                args=(trigger,),
                name="LANChatAgentTask",
                daemon=True,
            ).start()
            return True

        return self._process_trigger(trigger)

    def _process_trigger(self, trigger: dict[str, Any]) -> bool:
        agent_id = str(trigger.get("agent_id") or "agent")
        agent_name = str(trigger.get("agent_name") or "Agent")
        action_payload = None

        def _send_progress(message: str) -> None:
            text = str(message or "").strip()
            if not text:
                return
            try:
                if hasattr(self._corona_engine, "network_send_agent_reply_ex"):
                    self._corona_engine.network_send_agent_reply_ex(
                        agent_id,
                        agent_name,
                        text,
                        "progress",
                        agent_id,
                        self._correlation_id(trigger),
                        json.dumps({"phase": "progress"}, ensure_ascii=False),
                    )
                else:
                    self._corona_engine.network_send_agent_reply(
                        agent_id,
                        agent_name,
                        text,
                    )
            except Exception as exc:
                self._logger.debug("Failed to send LANChat progress reply: %s", exc)

        try:
            from .agent_progress_context import agent_progress_sink

            if self._async_agent_execution and self._should_send_fast_ack(trigger):
                _send_progress("已收到你的要求；如果当前正在生成，我会在下一阶段吸收这条调整。")

            with agent_progress_sink(_send_progress):
                with self._agent_call_lock:
                    result = self._run_agent(trigger)
        except Exception as exc:
            self._logger.debug("LANChat AI agent failed: %s", exc)
            reply = f"AI agent failed: {exc}"
        else:
            agent_id = result.sender_id
            agent_name = result.sender_name
            reply = result.text
            action_payload = getattr(result, "action_payload", None)

        try:
            self._broadcast_confirmed_action(action_payload)
            return bool(
                self._send_final_reply(agent_id, agent_name, str(reply or ""), trigger, action_payload)
            )
        except Exception as exc:
            self._logger.debug("Failed to send LANChat agent reply: %s", exc)
            return False

    def _run(self) -> None:
        while not self._stop_event.is_set():
            processed = self.process_once()
            if not processed:
                self._stop_event.wait(self._sleep_seconds)

    def _send_final_reply(
        self,
        agent_id: str,
        agent_name: str,
        text: str,
        trigger: dict[str, Any],
        action_payload: dict[str, Any] | None = None,
    ) -> bool:
        if action_payload and action_payload.get("status") == "pending_host_confirmation":
            proposal_id = str(action_payload.get("proposal_id") or self._correlation_id(trigger))
            metadata = dict(action_payload)
            metadata.setdefault("requires_host_confirm", True)
            if hasattr(self._corona_engine, "network_send_system_message_ex"):
                return bool(self._corona_engine.network_send_system_message_ex(
                    agent_id,
                    agent_name,
                    text,
                    "gm_proposal",
                    proposal_id,
                    json.dumps(metadata, ensure_ascii=False),
                ))
        if hasattr(self._corona_engine, "network_send_agent_reply_ex"):
            return bool(self._corona_engine.network_send_agent_reply_ex(
                agent_id,
                agent_name,
                text,
                "agent_reply",
                agent_id,
                self._correlation_id(trigger),
                json.dumps({"reply_to": str(trigger.get("message_id") or "")}, ensure_ascii=False),
            ))
        return bool(self._corona_engine.network_send_agent_reply(agent_id, agent_name, text))

    def _has_engine_api(self) -> bool:
        return (
            self._corona_engine is not None
            and hasattr(self._corona_engine, "network_pop_lanchat_agent_trigger")
            and hasattr(self._corona_engine, "network_send_agent_reply")
        )

    def _get_orchestrator(self) -> LanChatAgentOrchestrator:
        if self._orchestrator is None:
            self._orchestrator = LanChatAgentOrchestrator(
                agent_factory=self._agent_factory or self._default_agent_factory,
            )
        return self._orchestrator

    def _run_agent(self, trigger: dict[str, Any]):
        return self._get_orchestrator().handle_trigger(trigger)

    def _broadcast_confirmed_action(self, payload: dict[str, Any] | None) -> None:
        if not payload or payload.get("status") != "confirmed":
            return
        if hasattr(self._corona_engine, "network_broadcast_intent"):
            source_user_id = str(payload.get("source_user_id") or "unknown")
            tooltip = str(payload.get("intent_text") or payload.get("proposal_id") or "")
            try:
                self._corona_engine.network_broadcast_intent(
                    source_user_id,
                    tooltip,
                    [0.0, 0.0, 0.0],
                    "confirmed_gm_action",
                )
            except Exception as exc:
                self._logger.debug("Failed to broadcast confirmed GM action: %s", exc)

        self._execute_confirmed_action(payload)

    def _execute_confirmed_action(self, payload: dict[str, Any]) -> None:
        executor = self._get_host_action_executor()
        if executor is None or not hasattr(executor, "enqueue_and_process"):
            return
        try:
            executor.enqueue_and_process(payload)
        except Exception as exc:
            self._logger.debug("Failed to execute confirmed GM action: %s", exc)

    def _get_host_action_executor(self) -> Any:
        if self._host_action_executor is None:
            self._host_action_executor = LanChatHostActionExecutor(
                corona_engine=self._corona_engine,
                agent_factory=self._agent_factory or self._default_agent_factory,
            )
        return self._host_action_executor

    @staticmethod
    def _correlation_id(trigger: dict[str, Any]) -> str:
        return str(trigger.get("correlation_id") or trigger.get("message_id") or "")

    @staticmethod
    def _should_send_fast_ack(trigger: dict[str, Any]) -> bool:
        kind = str(trigger.get("message_kind") or "chat").lower()
        if kind and kind != "chat":
            return False
        text = str(trigger.get("text") or "")
        if not text.strip():
            return False
        keywords = (
            "生成", "设计", "场景", "房间", "卧室", "广场", "教堂",
            "添加", "放大", "缩小", "移动", "移", "删", "删除", "调整",
            "靠左", "靠右", "远一点", "近一点", "不要太拥挤",
            "generate", "create", "move", "scale", "delete", "adjust",
        )
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _messages_from_trigger(trigger: dict[str, Any]) -> list[str]:
        messages: list[str] = []
        history = trigger.get("history") or []
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue
                sender = str(item.get("from") or item.get("sender_name") or "")
                text = str(item.get("text") or "")
                if text:
                    messages.append(f"{sender}: {text}" if sender else text)

        text = str(trigger.get("text") or "")
        if text and text not in messages:
            messages.append(text)
        return messages

    @staticmethod
    def _default_agent_factory() -> Any:
        from plugins.AITool.cai_extensions.agent.agent_adapter import create_master_agent

        return create_master_agent()
