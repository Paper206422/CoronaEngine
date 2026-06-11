"""消息意图分类器 — 每条用户消息发出后，判别 agent 是否需要响应。

把「定量被动触发」升级为「每条消息主动判别」（类似主流 AI 助手）：
  - execute   : 这条消息含可执行的场景操作（加/删/移/生成等）
  - summarize : 该总结了（话题收尾、用户暗示、讨论充分）
  - none      : 普通闲聊，无需 agent 介入

用注入的 ai_chat 回调（复用 SummaryService 的 LLM 通道）做一次轻量分类。
失败时返回 none，绝不阻断正常聊天。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_CLASSIFY_SYSTEM = (
    "你是群聊场景助手的意图判别器。根据【最新消息】(结合少量上下文)判断助手是否需要介入。\n"
    "只输出 JSON：{\"intent\":\"execute|summarize|none\",\"reason\":\"简短理由\",\"target\":\"若execute则填操作对象，否则空\"}\n"
    "判别规则：\n"
    "- execute：消息要求对 3D 场景做操作（添加/删除/移动/缩放/生成模型/布置/导入等）\n"
    "- summarize：讨论告一段落、用户说『总结下/差不多了/就这样』、或多人已达成方案共识\n"
    "- none：普通闲聊、提问、寒暄，无需操作也无需总结\n"
    "只输出 JSON，不要解释。"
)

# 快速规则：明显执行类（命中直接判 execute，省一次 LLM 调用）
_EXEC_HINTS = [
    r"(?:加个?|添加|放个?|增加|新[增建]|导入)",
    r"(?:删[掉除]|移除|去掉|清除)",
    r"(?:把|将).{0,12}(?:移|挪|搬|放大|缩小|旋转|调整)",
    r"生成.{0,8}(?:3d|3D|模型|物体|场景|家具)",
    r"(?:布置|摆放|组合|搭建).{0,12}(?:场景|房间|卧室|客厅|酒吧)",
    r"(?:按|根据).{0,8}清单",
]
# 快速规则：明显总结类
_SUMMARY_HINTS = [
    r"总结(?:一?下|下)?", r"差不多了", r"就这样(?:吧)?",
    r"汇总", r"梳理(?:一?下)?", r"小结",
]
# 明显闲聊（直接 none，省 LLM）
_NONE_HINTS = [
    r"^(?:你好|hello|hi|hey|在吗|哈喽)\b", r"^(?:谢谢|thanks?|多谢|辛苦)",
    r"^(?:好的|嗯+|行|ok|可以|收到)\b",
]


class IntentClassifier:
    """每条消息的意图判别器。ai_chat 为阻塞式 (prompt)->str 回调。"""

    def __init__(self, ai_chat: Optional[Callable[[str], str]] = None) -> None:
        self._ai_chat = ai_chat

    def quick_rule(self, text: str) -> Optional[str]:
        """规则快判：命中明确模式直接返回 intent，否则 None（交给 LLM）。"""
        t = (text or "").strip()
        if not t or len(t) < 2:
            return "none"
        for pat in _NONE_HINTS:
            if re.search(pat, t):
                return "none"
        for pat in _EXEC_HINTS:
            if re.search(pat, t):
                return "execute"
        for pat in _SUMMARY_HINTS:
            if re.search(pat, t):
                return "summarize"
        return None

    async def classify(self, text: str, recent: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """判别单条消息意图。返回 {"intent","reason","target"}。

        先规则快判；规则未命中且有 LLM 通道时调一次 LLM；否则回退 none。
        """
        # 规则优先（零延迟、零成本）—— 注：先不依赖 LLM 也能用
        quick = self.quick_rule(text)
        if quick is not None:
            logger.info("[IntentClassifier] 规则判别: %r → %s", text[:30], quick)
            return {"intent": quick, "reason": "rule", "target": text[:20] if quick == "execute" else ""}

        if not self._ai_chat:
            return {"intent": "none", "reason": "no_llm", "target": ""}

        # LLM 判别（后台线程，不阻塞事件循环）
        try:
            prompt = self._build_prompt(text, recent or [])
            loop = asyncio.get_running_loop()
            raw = await loop.run_in_executor(None, self._ai_chat, prompt)
            result = self._parse(raw)
            logger.info("[IntentClassifier] LLM 判别: %r → %s (%s)",
                        text[:30], result.get("intent"), result.get("reason", ""))
            return result
        except Exception as e:
            logger.warning("[IntentClassifier] LLM 判别失败，回退 none: %s", e)
            return {"intent": "none", "reason": f"error:{e}", "target": ""}

    def _build_prompt(self, text: str, recent: List[Dict[str, Any]]) -> str:
        ctx_lines = [f"{m.get('from', '?')}: {m.get('text', '')}" for m in recent[-5:]]
        ctx = "\n".join(ctx_lines) if ctx_lines else "（无）"
        return (
            f"{_CLASSIFY_SYSTEM}\n\n"
            f"【最近上下文】\n{ctx}\n\n"
            f"【最新消息】\n{text}\n\n"
            f"【输出】"
        )

    def _parse(self, raw: str) -> Dict[str, Any]:
        text = (raw or "").strip()
        if "```" in text:
            s = text.find("{"); e = text.rfind("}")
            if s != -1 and e != -1:
                text = text[s:e + 1]
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"intent": "none", "reason": "parse_fail", "target": ""}
        intent = str(data.get("intent", "none")).strip().lower()
        if intent not in ("execute", "summarize", "none"):
            intent = "none"
        return {
            "intent": intent,
            "reason": str(data.get("reason", "")),
            "target": str(data.get("target", "")),
        }


__all__ = ["IntentClassifier"]
