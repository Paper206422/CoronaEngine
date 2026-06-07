"""房间管理：房间状态、密码校验、成员去重、环形历史。

房主侧使用。线程/协程安全性：所有方法预期在房主的单一 asyncio 事件循环
内被串行调用（ChatServer 的 handler 中），因此不额外加锁。
"""

from __future__ import annotations

import itertools
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from .protocol import ErrorCode


# 单房成员上限
MAX_MEMBERS = 16
# 历史消息环形缓冲上限
MAX_HISTORY = 200


class Agent:
    """聊天室里的虚拟 AI 成员（房主名册内）。

    待收口：model/params、私有标记、跨房复用、持久化等字段后续统一补充。
    persona 仅 owner + 房主持有，绝不随 agent_roster 广播给其他成员。
    """

    def __init__(self, agent_id: str, name: str, persona: str, owner: str,
                 requested_name: str) -> None:
        self.agent_id = agent_id
        self.name = name                  # 去重后的显示名 / @ 用名
        self.persona = persona
        self.owner = owner
        self.requested_name = requested_name  # owner 原始请求名（幂等匹配用）


class JoinResult:
    """加入房间的结果。成功时 error 为 None，final_name 为去重后的最终昵称。"""

    def __init__(
        self,
        ok: bool,
        final_name: str = "",
        error: Optional[str] = None,
    ) -> None:
        self.ok = ok
        self.final_name = final_name
        self.error = error


class Room:
    """单个房间的状态。

    成员以 connection 标识（任意可哈希对象，由 ChatServer 传入 websocket 实例）
    映射到昵称，便于断开时按连接移除。
    """

    # 滚动摘要阈值（默认值，后续可调）
    RECENT_KEEP = 30
    COMPRESS_TRIGGER = 40   # _recent 累计超过此数触发压缩
    COMPRESS_BATCH = 10     # 每次把最老的多少条压进摘要
    SUMMARY_MAX_CHARS = 800

    def __init__(self, room_id: str, password: str = "") -> None:
        self.room_id = room_id
        self.password = password
        # connection -> nickname
        self._members: Dict[Any, str] = {}
        # 最近消息环形缓冲
        self._history: Deque[Dict[str, Any]] = deque(maxlen=MAX_HISTORY)
        # agent 名册：agent_id -> Agent。与成员名册平行，独立管理。
        self._agents: Dict[str, Agent] = {}
        self._agent_id_seq = itertools.count(1)
        # 滚动摘要：summary 为早期对话压缩，_recent 复用 _history（最近原文窗口）
        self._summary: str = ""
        self._compressing: bool = False

    # ---- 成员管理 -------------------------------------------------------
    def member_names(self) -> List[str]:
        """返回当前成员昵称列表（按加入顺序）。"""
        return list(self._members.values())

    def member_count(self) -> int:
        return len(self._members)

    def is_full(self) -> bool:
        return len(self._members) >= MAX_MEMBERS

    def _unique_name(self, nickname: str) -> str:
        """昵称去重：若重复则追加 -2 / -3 ... 后缀。"""
        existing = set(self._members.values())
        base = nickname.strip() or "用户"
        if base not in existing:
            return base
        i = 2
        while f"{base}-{i}" in existing:
            i += 1
        return f"{base}-{i}"

    def try_join(
        self,
        connection: Any,
        password: str,
        nickname: str,
    ) -> JoinResult:
        """尝试加入房间，做密码校验、人数校验、昵称去重。"""
        if self.is_full():
            return JoinResult(False, error=ErrorCode.ROOM_FULL)
        if self.password and password != self.password:
            return JoinResult(False, error=ErrorCode.WRONG_PASSWORD)
        final_name = self._unique_name(nickname)
        self._members[connection] = final_name
        return JoinResult(True, final_name=final_name)

    def remove(self, connection: Any) -> Optional[str]:
        """移除成员，返回其昵称（若存在）。"""
        return self._members.pop(connection, None)

    def name_of(self, connection: Any) -> Optional[str]:
        return self._members.get(connection)

    def connections(self) -> List[Any]:
        """返回所有成员连接（供广播遍历）。"""
        return list(self._members.keys())

    # ---- 历史 -----------------------------------------------------------
    def append_history(self, message: Dict[str, Any]) -> None:
        """追加一条消息到历史环形缓冲。"""
        self._history.append(message)

    def history_snapshot(self) -> List[Dict[str, Any]]:
        """返回历史快照（浅拷贝列表）。"""
        return list(self._history)

    # ---- 历史与滚动摘要 -------------------------------------------------
    def record(self, message: Dict[str, Any]) -> None:
        """记录一条消息到原文窗口（_history 即 _recent）。"""
        self._history.append(message)

    def history_view(self) -> Dict[str, Any]:
        """供 agent_trigger 下发的历史视图：摘要 + 最近原文。"""
        return {"summary": self._summary, "recent": list(self._history)}

    def is_compressing(self) -> bool:
        """是否有压缩任务正在进行（单任务锁）。"""
        return self._compressing

    def take_compress_batch(self) -> Optional[List[Dict[str, Any]]]:
        """若原文越界且当前无压缩任务，弹出最老的一批并加压缩锁；否则 None。"""
        if self._compressing or len(self._history) <= self.COMPRESS_TRIGGER:
            return None
        batch = [self._history.popleft() for _ in range(self.COMPRESS_BATCH)]
        self._compressing = True
        return batch

    def set_summary(self, summary: str) -> None:
        """直接设置摘要（截断到上限），不改压缩锁。"""
        self._summary = summary[: self.SUMMARY_MAX_CHARS]

    def apply_summary(self, summary: str) -> None:
        """压缩成功：写入新摘要（截断到上限）并解锁。"""
        self._summary = summary[: self.SUMMARY_MAX_CHARS]
        self._compressing = False

    def append_summary_fallback(self, batch: List[Dict[str, Any]]) -> None:
        """压缩失败兜底：把 batch 拼成纯文本附到摘要末尾并截断（保留最近），然后解锁。"""
        extra = " ".join(f"{m.get('from', '?')}:{m.get('text', '')}" for m in batch)
        combined = (self._summary + " " + extra).strip()
        self._summary = combined[-self.SUMMARY_MAX_CHARS :]
        self._compressing = False

    # ---- agent 名册 -----------------------------------------------------
    def _unique_agent_name(self, name: str) -> str:
        """agent 显示名去重：重复则追加 -2/-3…（与成员去重思路一致）。"""
        existing = {a.name for a in self._agents.values()}
        base = name.strip() or "助手"
        if base not in existing:
            return base
        i = 2
        while f"{base}-{i}" in existing:
            i += 1
        return f"{base}-{i}"

    def add_agent(self, name: str, persona: str, owner: str) -> "Agent":
        """登记/更新 agent。同 owner 同请求名视为同一 agent（幂等，供重连补登记）。"""
        requested = name.strip()
        for agent in self._agents.values():
            if agent.owner == owner and agent.requested_name == requested:
                agent.persona = persona  # 更新人设
                return agent
        agent_id = f"agent-{next(self._agent_id_seq)}"
        agent = Agent(agent_id, self._unique_agent_name(name), persona, owner,
                      requested_name=requested)
        self._agents[agent_id] = agent
        return agent

    def remove_agent(self, agent_id: str) -> Optional[str]:
        """移除单个 agent，返回其 agent_id（若存在）。"""
        agent = self._agents.pop(agent_id, None)
        return agent.agent_id if agent is not None else None

    def remove_agents_of_owner(self, owner: str) -> List[str]:
        """移除某 owner 的全部 agent（owner 掉线/离开用），返回被移除的 id 列表。"""
        ids = [aid for aid, a in self._agents.items() if a.owner == owner]
        for aid in ids:
            self._agents.pop(aid, None)
        return ids

    def get_agent(self, agent_id: str) -> Optional["Agent"]:
        """按 agent_id 取 agent，不存在返回 None。"""
        return self._agents.get(agent_id)

    def agents_for_owner(self, owner: str) -> List["Agent"]:
        """返回某 owner 拥有的所有 agent。"""
        return [a for a in self._agents.values() if a.owner == owner]

    def agent_roster(self) -> List[Dict[str, Any]]:
        """名册的公开视图（不含 persona），供广播。"""
        return [
            {"agent_id": a.agent_id, "name": a.name, "owner": a.owner}
            for a in self._agents.values()
        ]

    def resolve_mentions(self, text: str) -> List[str]:
        """解析文本里 @ 到的 agent，返回命中的 agent_id 列表（按名册顺序、去重）。

        同名取名册中首个匹配（边界，先接受）。
        """
        hit: List[str] = []
        seen_names: Set[str] = set()
        for agent in self._agents.values():
            if agent.name in seen_names:
                continue
            if f"@{agent.name}" in text:
                hit.append(agent.agent_id)
                seen_names.add(agent.name)
        return hit


class RoomManager:
    """管理本机房主开的房间。初版只支持单房（主机一次开一个房）。"""

    def __init__(self) -> None:
        self._room: Optional[Room] = None

    def create_room(self, room_id: str, password: str = "") -> Room:
        """创建房间（覆盖已有房间）。"""
        self._room = Room(room_id, password)
        return self._room

    def close_room(self) -> None:
        """关闭当前房间。"""
        self._room = None

    def get_room(self, room_id: str) -> Optional[Room]:
        """按房间号取房间；不匹配返回 None。"""
        if self._room is not None and self._room.room_id == room_id:
            return self._room
        return None

    @property
    def active_room(self) -> Optional[Room]:
        return self._room

    def stamp_and_record(
        self,
        room: Room,
        sender: str,
        text: str,
    ) -> Dict[str, Any]:
        """给消息盖时间戳、写入历史，返回完整消息 dict。"""
        message = {
            "type": "message",
            "from": sender,
            "text": text,
            "ts": int(time.time()),
        }
        room.append_history(message)
        return message
