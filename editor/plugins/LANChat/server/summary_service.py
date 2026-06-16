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
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)

_SUMMARY_SYSTEM = (
    "你是对话摘要助手。把以下群聊压缩成简洁要点，"
    "保留人名、已达成的决定和未决的问题。只输出摘要本身，不要解释。"
)

_SCENE_INTENT_PATTERNS = [
    r"(?:生成|制作|创建|搭建|布置|设计).{0,20}(?:场景|房间|模型|物体)",
    r"(?:添加|加个?|放个?|导入|移除|删除|移动|旋转|放大|缩小|改成).{1,40}",
    r"(?:重新整理|重新布置|整体调整|最终确认|执行方案)",
]

_GLOBAL_CONFLICT_KEYWORDS = [
    ("红", "蓝", "颜色冲突"),
    ("保留", "删除", "保留/删除冲突"),
    ("室内", "室外", "空间意图冲突"),
]


@dataclass
class DiscussionState:
    """静默监听/GM 的结构化讨论状态。"""
    summary: str = ""
    accepted_intents: List[str] = field(default_factory=list)
    pending_intents: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    next_batch_suggestions: List[str] = field(default_factory=list)
    required_confirmations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "accepted_intents": list(self.accepted_intents),
            "pending_intents": list(self.pending_intents),
            "conflicts": list(self.conflicts),
            "constraints": list(self.constraints),
            "next_batch_suggestions": list(self.next_batch_suggestions),
            "required_confirmations": list(self.required_confirmations),
        }


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

    async def monitor(self, prev_summary: str, batch: List[Dict[str, Any]]) -> DiscussionState:
        """生成 GM/静默监听结构化状态。

        保持 compress() 作为摘要来源；结构化字段用确定性规则先兜底，避免为了
        监听状态额外阻塞一次 LLM。
        """
        summary = await self.compress(prev_summary, batch)
        texts = [str(m.get("text", "") or "").strip() for m in batch]
        pending = self._extract_scene_intents(texts)
        conflicts = self._detect_conflicts(texts)
        confirmations = list(conflicts)
        if any(("删除" in t or "移除" in t or "重置" in t) for t in texts):
            confirmations.append("检测到删除/重置类操作，需要房主确认后执行")
        return DiscussionState(
            summary=summary,
            pending_intents=pending,
            conflicts=conflicts,
            constraints=self._extract_constraints(texts),
            next_batch_suggestions=pending[:3],
            required_confirmations=confirmations,
        )

    @staticmethod
    def _extract_scene_intents(texts: List[str]) -> List[str]:
        intents: List[str] = []
        for text in texts:
            if any(re.search(p, text) for p in _SCENE_INTENT_PATTERNS):
                intents.append(text[:120])
        return intents

    @staticmethod
    def _extract_constraints(texts: List[str]) -> List[str]:
        constraints: List[str] = []
        for text in texts:
            if any(k in text for k in ("不要", "必须", "保留", "锁定", "不能")):
                constraints.append(text[:120])
        return constraints

    @staticmethod
    def _detect_conflicts(texts: List[str]) -> List[str]:
        joined = "\n".join(texts)
        conflicts: List[str] = []
        for a, b, label in _GLOBAL_CONFLICT_KEYWORDS:
            if a in joined and b in joined:
                conflicts.append(f"{label}: 同一轮讨论同时出现“{a}”和“{b}”")
        return conflicts
