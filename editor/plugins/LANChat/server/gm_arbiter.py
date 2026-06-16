"""GM 仲裁器（突击方案 COMMIT 7 / §3.2）。

定位：桌游隐喻 —— GM = 地下城主，负责编排、裁定、推进；房主 = 桌主，拥有拍板权。
GM 不负责解决 race（单写者队列已解决），只负责**语义冲突仲裁**。

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
                        detail=f"{req_a.user_id} 和 {req_b.user_id} 同时要操作 {req_a.target_actor}",
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

        return GMArbiterProposal(
            conflict=conflict,
            resolution="按时间先后",
            explanation=(
                f"{first.user_id} 和 {second.user_id} 同时想操作 {conflict.req_a.target_actor}。\n"
                f"建议按谁先说谁先执行：先 {first.user_id}，再 {second.user_id}。"
            ),
            action_plan=[
                f"执行 {first.user_id} 的请求（{first.text[:20]}...）",
                f"执行 {second.user_id} 的请求（{second.text[:20]}...）",
            ],
        )

    def await_host_confirmation(
        self,
        proposal: GMArbiterProposal,
        timeout: float = 60.0,
    ) -> str:
        """等待房主确认 GM 提案。

        返回：
        - "confirmed" — 房主确认，按 action_plan 执行
        - "modified" — 房主修改了顺序（TODO: 实现修改接口）
        - "timeout" — 超时，默认按提案执行

        当前简化版：立即返回 "confirmed"（假设房主默认同意）。
        完整版需前端 UI：弹窗显示 proposal.explanation + action_plan，房主点确认/改。
        """
        logger.info("[GMArbiter] 等待房主确认提案: %s", proposal.explanation)
        # TODO: 发消息给房主前端 → 等回复
        # 简化版：直接确认
        return "confirmed"

    def drain_queue(self) -> List[UserRequest]:
        """清空队列（执行完一批后调用）。返回已处理的请求列表。"""
        drained = self._queue[:]
        self._queue.clear()
        return drained


def integrate_gm_into_chat_server(chat_server: Any) -> None:
    """把 GM 仲裁器集成进 LANChat server（突击方案接入点）。

    在 `_dispatch_mentions` 前插入冲突检测 + GM 提案环节：
    1. 用户消息入 GM 队列（而非立即派发）
    2. 每轮消息后检测冲突
    3. 有冲突 → GM 提案 → 房主确认 → 按顺序派发
    4. 无冲突 → 直接派发

    当前简化版：在 chat_server 里加 `gm_arbiter` 属性，修改 `_dispatch_mentions` 逻辑。
    完整版需改 `_on_message` 入口。
    """
    from .gm_arbiter import GMArbiter
    chat_server.gm_arbiter = GMArbiter()
    logger.info("[GMArbiter] 已集成进 LANChat server（房主侧）")


__all__ = [
    "UserRequest", "Conflict", "GMArbiterProposal", "GMArbiter",
    "integrate_gm_into_chat_server",
]
