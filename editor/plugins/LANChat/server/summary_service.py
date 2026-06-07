"""房主侧滚动摘要服务。

把「已有摘要 + 一批待压缩的群聊原文」交给房主本机 AI 压成简洁摘要。
仅在房主进程内存在；guest 不需要。摘要调用失败时抛异常，由调用方
（ChatServer）退化为纯文本截断兜底（Room.append_summary_fallback）。

AI 调用通过注入的 ai_chat 回调完成（签名 (prompt: str) -> str），
便于测试与解耦——生产环境注入 AITool 的 CAIApp.chat 包装。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "你是对话摘要助手。把以下群聊压缩成简洁要点，"
    "保留人名、已达成的决定和未决的问题。只输出摘要本身，不要解释。"
)


class SummaryService:
    """滚动摘要执行器。ai_chat 为阻塞式 (prompt)->str 回调。"""

    def __init__(self, ai_chat: Callable[[str], str]) -> None:
        self._ai_chat = ai_chat

    def _build_prompt(self, prev_summary: str, batch: List[Dict[str, Any]]) -> str:
        """拼装摘要 prompt：系统指令 + 旧摘要 + 新增对话（带发言人标注）。"""
        lines = [f"{m.get('from', '?')}: {m.get('text', '')}" for m in batch]
        body = "\n".join(lines)
        prev = prev_summary.strip() or "（无）"
        return (
            f"{_SUMMARY_SYSTEM}\n\n"
            f"【已有摘要】\n{prev}\n\n"
            f"【新增对话】\n{body}\n\n"
            f"【合并后的摘要】"
        )

    async def compress(self, prev_summary: str, batch: List[Dict[str, Any]]) -> str:
        """合并旧摘要与新批次，返回新摘要。失败抛异常交调用方兜底。

        阻塞的 AI 调用丢到默认线程池执行器，避免堵住房主事件循环。
        """
        prompt = self._build_prompt(prev_summary, batch)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(None, self._ai_chat, prompt)
        except Exception:
            logger.warning("[LANChat] 摘要压缩调用 AI 失败，将退化为文本截断", exc_info=True)
            raise
        text = (result or "").strip()
        if not text:
            logger.warning("[LANChat] 摘要压缩返回空结果，将退化为文本截断")
            raise RuntimeError("empty summary")
        return text
