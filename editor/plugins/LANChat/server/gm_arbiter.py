"""GM 仲裁器历史兼容模块。

LANChat transport/state has moved to C++ NetworkSystem. New GM orchestration
lives in plugins.AITool.services.lanchat_agent_orchestrator and consumes C++
agent triggers. This module keeps the old data classes available for legacy
imports, but it must not own chat state or integrate with a Python chat server.

权限模型（写死，不做动态仲裁）：GM > 房主 > 玩家。

工作流：
1. 绝大多数请求不重叠（A摆东边、B摆西边）→ 串行执行，GM 不出场。
2. 真语义冲突（罕见，如 A刷红墙、B刷蓝墙）→ GM 检测 + 提案 → 房主一键确认/改。
3. 投票只做重大决定咨询（如换整个场景主题），且只对房主咨询、不强制。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


_SENSITIVE_GM_TEXT_MARKERS = (
    "prompt",
    "raw_prompt",
    "provider",
    "model_provider",
    "runtime_context",
    "scheduler_updates",
    "hidden_debug_ref",
    "debug",
    "job_id",
    "session_id",
    "token",
    "api_key",
    "vlm_raw",
)


def _safe_user_text(value: Any, *, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    lower = text.lower()
    cut_points = [
        lower.find(marker)
        for marker in _SENSITIVE_GM_TEXT_MARKERS
        if lower.find(marker) >= 0
    ]
    if cut_points:
        keep = text[:min(cut_points)].strip(" \t\r\n,;；。")
        return keep or fallback or "内部细节已隐藏"
    return text


@dataclass
class UserRequest:
    """一条用户请求（通过 @agent 发出）。"""
    user_id: str                # 用户昵称
    agent_id: str               # 目标 agent
    text: str                   # 请求文本
    intent: str = "unknown"     # 意图分类（compose/edit/move/chat）
    target_actor: Optional[str] = None   # 针对哪个物体（edit/move 时）
    timestamp: float = 0.0


@dataclass
class Conflict:
    """语义冲突：两个请求互相矛盾。"""
    kind: str                   # "同物体冲突" | "全局属性冲突"
    req_a: UserRequest
    req_b: UserRequest
    detail: str = ""            # 人读描述（"A 要把桌子移右、B 要移左"）


@dataclass
class GMArbiterProposal:
    """GM 提案：如何解决冲突。"""
    conflict: Conflict
    resolution: str             # "按时间先后" | "合并" | "优先房主" | "投票"
    explanation: str            # 给用户的文案（"两人都想移桌子，建议按谁先说谁先执行"）
    action_plan: List[str] = field(default_factory=list)  # 执行顺序（["执行 A", "执行 B"]）


class GMArbiter:
    """GM 仲裁器（单例，房主侧持有）。

    核心方法：
    - `enqueue_request(req)` — 用户请求入队（单写者队列）
    - `detect_conflicts()` — 检测队列中的语义冲突
    - `propose_resolution(conflict)` — GM 给提案
    - `await_host_confirmation(proposal)` — 等房主确认
    """

    def __init__(
        self,
        gm_agent_runner: Optional[Callable[[str, List], str]] = None,
    ) -> None:
        """
        gm_agent_runner: GM agent 的推理入口（persona, messages）→ str。
        为 None 时用启发式规则（不调 LLM）。
        """
        self._queue: List[UserRequest] = []
        self._gm_runner = gm_agent_runner
        self._pending_proposal: Optional[GMArbiterProposal] = None

    def enqueue_request(self, req: UserRequest) -> None:
        """用户请求入队（单写者模型：所有请求串行经此）。"""
        self._queue.append(req)
        logger.info("[GMArbiter] 入队: user=%s agent=%s intent=%s",
                    req.user_id, req.agent_id, req.intent)

    def detect_conflicts(self) -> List[Conflict]:
        """检测队列中的语义冲突（两两比）。

        当前简化版：只检测"同时操作同一物体"冲突（edit/move 针对同 actor）。
        可扩展：全局属性冲突（A刷红墙、B刷蓝墙）、空间冲突（A摆这、B摆那同位置）。
        """
        conflicts: List[Conflict] = []
        for i, req_a in enumerate(self._queue):
            for req_b in self._queue[i + 1:]:
                # 同物体 edit/move 冲突
                if (req_a.intent in ("edit", "move") and req_b.intent in ("edit", "move")
                        and req_a.target_actor and req_a.target_actor == req_b.target_actor):
                    conflicts.append(Conflict(
                        kind="同物体冲突",
                        req_a=req_a,
                        req_b=req_b,
                        detail=(
                            f"{_safe_user_text(req_a.user_id, fallback='用户')} 和 "
                            f"{_safe_user_text(req_b.user_id, fallback='用户')} 同时要操作 "
                            f"{_safe_user_text(req_a.target_actor, fallback='同一目标')}"
                        ),
                    ))
        return conflicts

    def propose_resolution(self, conflict: Conflict) -> GMArbiterProposal:
        """GM 给解决提案（语义冲突仲裁的核心）。

        当前启发式规则（不调 LLM）：
        - 同物体冲突 → 按时间先后（队列顺序 = 先到先得）
        可扩展：调 GM agent LLM 给语义合并建议。
        """
        # 简化版：按时间先后
        if conflict.req_a.timestamp <= conflict.req_b.timestamp:
            first, second = conflict.req_a, conflict.req_b
        else:
            first, second = conflict.req_b, conflict.req_a

        first_user = _safe_user_text(first.user_id, fallback="先到用户")
        second_user = _safe_user_text(second.user_id, fallback="后到用户")
        target_actor = _safe_user_text(conflict.req_a.target_actor, fallback="同一目标")
        first_text = _safe_user_text(first.text, fallback="请求")
        second_text = _safe_user_text(second.text, fallback="请求")

        return GMArbiterProposal(
            conflict=conflict,
            resolution="按时间先后",
            explanation=(
                f"{first_user} 和 {second_user} 同时想操作 {target_actor}。\n"
                f"建议按谁先说谁先执行：先 {first_user}，再 {second_user}。"
            ),
            action_plan=[
                f"执行 {first_user} 的请求（{first_text[:20]}...）",
                f"执行 {second_user} 的请求（{second_text[:20]}...）",
            ],
        )

    def await_host_confirmation(
        self,
        proposal: GMArbiterProposal,
        timeout: float = 60.0,
    ) -> str:
        """等待房主确认 GM 提案。

        返回：
        - "pending_host_confirmation" — 已挂起，等待房主显式确认/拒绝
        - "confirmed" — 房主确认，按 action_plan 执行
        - "rejected" — 房主拒绝，丢弃提案
        - "modified" — 房主修改了顺序或执行计划
        - "timeout" — 超时，默认按提案执行

        Legacy 模块不再默认自动确认。新版控制面由
        AITool.services.interaction_coordinator 收口；这里仅保留一个显式
        pending 状态，避免旧入口绕过房主确认。
        """
        logger.info("[GMArbiter] 等待房主确认提案: %s", proposal.explanation)
        self._pending_proposal = proposal
        return "pending_host_confirmation"

    def confirm_pending_proposal(self) -> str:
        """Confirm the currently pending legacy GM proposal."""
        if self._pending_proposal is None:
            return "no_pending_proposal"
        self._pending_proposal = None
        return "confirmed"

    def reject_pending_proposal(self) -> str:
        """Reject the currently pending legacy GM proposal."""
        if self._pending_proposal is None:
            return "no_pending_proposal"
        self._pending_proposal = None
        return "rejected"

    def modify_pending_proposal(self, action_plan: List[str]) -> str:
        """Replace the pending proposal action plan with an explicit host edit."""
        if self._pending_proposal is None:
            return "no_pending_proposal"
        safe_plan = [
            _safe_user_text(item, fallback="内部细节已隐藏")
            for item in action_plan
            if str(item or "").strip()
        ]
        if not safe_plan:
            return "invalid_action_plan"
        self._pending_proposal.action_plan = safe_plan
        self._pending_proposal.resolution = "房主修改"
        self._pending_proposal.explanation = "房主已修改 GM 仲裁执行计划。"
        self._pending_proposal = None
        return "modified"

    def drain_queue(self) -> List[UserRequest]:
        """清空队列（执行完一批后调用）。返回已处理的请求列表。"""
        drained = self._queue[:]
        self._queue.clear()
        return drained


def integrate_gm_into_chat_server(chat_server: Any) -> None:
    """Deprecated no-op.

    The Python chat_server was removed by the C++ NetworkSystem migration.
    Use AITool.services.lanchat_agent_orchestrator instead.
    """
    logger.warning(
        "[GMArbiter] integrate_gm_into_chat_server is deprecated; "
        "LANChat is owned by C++ NetworkSystem"
    )


__all__ = [
    "UserRequest", "Conflict", "GMArbiterProposal", "GMArbiter",
    "integrate_gm_into_chat_server",
]
