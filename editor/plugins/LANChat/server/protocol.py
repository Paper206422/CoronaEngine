"""LANChat 消息协议定义。

定义两层协议：
- Python ↔ Python 跨机 WebSocket 消息（MsgType 枚举 + 构造/解析 helper）。
- Python → 前端 js_call_func 推送信封（build_frontend_event）。

Server 和 Client 共享本模块，保证两端对消息格式的理解一致。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# 消息类型常量（跨机 WebSocket）
# ---------------------------------------------------------------------------
class MsgType:
    """跨机 WebSocket 消息的 type 字段取值。"""

    # 客户端 → 服务器
    JOIN = "join"
    MESSAGE = "message"
    LEAVE = "leave"
    PING = "ping"

    # 服务器 → 客户端
    JOINED = "joined"
    MEMBER_UPDATE = "member_update"
    ERROR = "error"
    PONG = "pong"

    # Agent 相关（owner ↔ 房主 ↔ 全群）
    AGENT_REGISTER = "agent_register"   # owner → 房主
    AGENT_REMOVE = "agent_remove"       # owner → 房主
    AGENT_TRIGGER = "agent_trigger"     # 房主 → owner
    AGENT_REPLY = "agent_reply"         # owner → 房主
    AGENT_ROSTER = "agent_roster"       # 房主 → 全群


# ---------------------------------------------------------------------------
# 错误码
# ---------------------------------------------------------------------------
class ErrorCode:
    """error 消息的 code 字段取值。"""

    WRONG_PASSWORD = "WRONG_PASSWORD"
    ROOM_NOT_FOUND = "ROOM_NOT_FOUND"
    ROOM_FULL = "ROOM_FULL"
    NAME_TAKEN = "NAME_TAKEN"
    BAD_REQUEST = "BAD_REQUEST"


# 前端事件信封的 channel 标记，用于在 AITalkBar 中区分 AI 消息与聊天室消息
FRONTEND_CHANNEL = "lanchat"

# 房主在房间内的显示昵称。房主不通过 WS join，由此常量统一标识，
# 前端据此判定消息气泡是否为本人（self）。Python 与前端须保持一致。
HOST_NICKNAME = "房主"


# ---------------------------------------------------------------------------
# 服务器 → 客户端 消息构造
# ---------------------------------------------------------------------------
def build_joined(
    members: List[str],
    history: List[Dict[str, Any]],
    you: str = "",
) -> Dict[str, Any]:
    """构造 joined 消息（进房成功，下发成员、历史与本人最终昵称）。"""
    return {
        "type": MsgType.JOINED,
        "members": list(members),
        "history": list(history),
        "you": you,  # 服务器去重后分配给本连接的最终昵称
    }


def build_message(sender: str, text: str, ts: int | None = None) -> Dict[str, Any]:
    """构造一条聊天消息，ts 由服务器统一盖章。"""
    return {
        "type": MsgType.MESSAGE,
        "from": sender,
        "text": text,
        "ts": ts if ts is not None else int(time.time()),
    }


def build_member_update(members: List[str]) -> Dict[str, Any]:
    """构造成员变更广播。"""
    return {
        "type": MsgType.MEMBER_UPDATE,
        "members": list(members),
    }


def build_error(code: str, detail: str = "") -> Dict[str, Any]:
    """构造错误消息。"""
    msg: Dict[str, Any] = {"type": MsgType.ERROR, "code": code}
    if detail:
        msg["detail"] = detail
    return msg


def build_pong() -> Dict[str, Any]:
    """构造心跳响应。"""
    return {"type": MsgType.PONG}


# ---------------------------------------------------------------------------
# 客户端 → 服务器 消息构造
# ---------------------------------------------------------------------------
def build_join(room: str, password: str, nickname: str) -> Dict[str, Any]:
    """构造加入房间请求。"""
    return {
        "type": MsgType.JOIN,
        "room": room,
        "password": password,
        "nickname": nickname,
    }


def build_client_message(sender: str, text: str) -> Dict[str, Any]:
    """构造客户端发往服务器的聊天消息（ts 由服务器盖章，此处不带）。"""
    return {
        "type": MsgType.MESSAGE,
        "from": sender,
        "text": text,
    }


def build_leave(sender: str) -> Dict[str, Any]:
    """构造离开房间通知。"""
    return {"type": MsgType.LEAVE, "from": sender}


def build_ping() -> Dict[str, Any]:
    """构造心跳。"""
    return {"type": MsgType.PING}


# ---------------------------------------------------------------------------
# Python → 前端 推送信封（经 js_call_func）
# ---------------------------------------------------------------------------
def build_frontend_event(event: str, **fields: Any) -> Dict[str, Any]:
    """构造推送给前端的事件信封。

    Args:
        event: 事件名（joined / message / member_update / error / room_closed）。
        **fields: 事件附带字段（from / text / ts / members / history / code 等）。

    Returns:
        带 channel 标记的事件 dict，前端按 channel == "lanchat" 分流。
    """
    payload: Dict[str, Any] = {"channel": FRONTEND_CHANNEL, "event": event}
    payload.update(fields)
    return payload


# ---------------------------------------------------------------------------
# Agent 消息构造
# ---------------------------------------------------------------------------
def build_agent_register(
    name: str,
    persona: str,
    owner: str,
    agent_id: str | None = None,
) -> Dict[str, Any]:
    """owner → 房主：登记一个 agent。agent_id 为 None 时由房主分配。"""
    return {
        "type": MsgType.AGENT_REGISTER,
        "agent_id": agent_id,
        "name": name,
        "persona": persona,
        "owner": owner,
    }


def build_agent_remove(agent_id: str) -> Dict[str, Any]:
    """owner → 房主：注销一个 agent。"""
    return {"type": MsgType.AGENT_REMOVE, "agent_id": agent_id}


def build_agent_trigger(
    agent_id: str,
    trigger_id: str,
    summary: str,
    recent: List[Dict[str, Any]],
    trigger_msg: Dict[str, Any],
    persona: str = "",
) -> Dict[str, Any]:
    """房主 → owner：派活，带全群历史快照（summary + recent）+ 人设。

    persona 仅发给该 agent 的 owner（owner 本就拥有此人设），不广播全群，无泄露。
    随触发下发可避免 owner 侧因 agent_id 重新分配而查不到本地人设。
    """
    return {
        "type": MsgType.AGENT_TRIGGER,
        "agent_id": agent_id,
        "trigger_id": trigger_id,
        "history": {"summary": summary, "recent": list(recent)},
        "trigger_msg": dict(trigger_msg),
        "persona": persona,
    }


def build_agent_reply(
    agent_id: str,
    trigger_id: str,
    text: str | None = None,
    error: str | None = None,
) -> Dict[str, Any]:
    """owner → 房主：回交结果。text 与 error 二选一。"""
    msg: Dict[str, Any] = {
        "type": MsgType.AGENT_REPLY,
        "agent_id": agent_id,
        "trigger_id": trigger_id,
    }
    if error is not None:
        msg["error"] = error
    else:
        msg["text"] = text or ""
    return msg


def build_agent_roster(agents: List[Dict[str, Any]]) -> Dict[str, Any]:
    """房主 → 全群：名册变更广播。只下发可见信息，绝不含 persona。"""
    public = [
        {"agent_id": a["agent_id"], "name": a["name"], "owner": a["owner"]}
        for a in agents
    ]
    return {"type": MsgType.AGENT_ROSTER, "agents": public}
