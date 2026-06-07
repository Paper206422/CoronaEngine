"""owner 侧 agent 执行器。

把「人设 + 全群历史（摘要 + 最近原文） + 触发消息」翻译成一次阻塞的本机
AI 调用，返回完整回复字符串（符合「生成完整发」）。失败时抛异常，由
ChatClient 包成 agent_reply{error} 回交房主。

run 是同步阻塞方法——调用方（ChatClient）负责把它丢到线程池，避免堵住
事件循环。AI 调用通过注入的 ai_chat 回调完成（签名
(system: str, messages: list[str]) -> str），便于测试与解耦。
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM = "你是一个有帮助的助手。"


class AgentRunner:
    """单次 agent 推理。ai_chat 为阻塞式 (system, messages)->str 回调。"""

    def __init__(self, ai_chat: Callable[[str, List[str]], str]) -> None:
        self._ai_chat = ai_chat

    def _build_messages(self, history: Dict[str, Any]) -> List[str]:
        """把历史拼成带发言人标注的消息行；摘要非空则前置。"""
        messages: List[str] = []
        summary = (history.get("summary") or "").strip()
        if summary:
            messages.append(f"[此前对话摘要] {summary}")
        recent = history.get("recent") or []
        for m in recent:
            messages.append(f"{m.get('from', '?')}: {m.get('text', '')}")
        return messages

    def run(
        self,
        persona: str,
        history: Dict[str, Any],
        trigger_msg: Dict[str, Any],
    ) -> str:
        """阻塞执行一次推理，返回完整回复。失败抛异常（调用方兜底）。"""
        system = persona or _DEFAULT_SYSTEM
        messages = self._build_messages(history)
        try:
            result = self._ai_chat(system, messages)
        except Exception:
            logger.warning("[LANChat] agent 推理调用 AI 失败", exc_info=True)
            raise
        return (result or "").strip()
