"""Compatibility proxy for LANChat.

CEF now intercepts the LANChat module and routes it to C++ NetworkSystem.
This file remains only for any legacy Python-side imports; it must not start
WebSocket clients/servers or own collaboration state.
It is not a source of truth for current UI port display; C++/CEF owns that.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_PORT = 27960


def _engine():
    try:
        import CoronaEngine  # type: ignore

        return CoronaEngine
    except Exception:
        return None


def _unsupported(name: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "error": f"LANChat.{name} is owned by C++ NetworkSystem",
    }


class LANChat:
    @classmethod
    def start_room(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return _unsupported("start_room")

    @classmethod
    def start_local_room(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        payload = payload or {}
        return {
            "ok": True,
            "room": payload.get("room") or "",
            "mode": "single",
            "ip": "",
            "port": 0,
            "peer_id": "local-single-player",
            "members": ["房主"],
            "member_details": [
                {
                    "member_id": "local-single-player",
                    "nickname": "房主",
                    "status": "online",
                },
            ],
            "agents": [],
        }

    @classmethod
    def stop_room(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return {"ok": True}

    @classmethod
    def stop_local_room(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return {"ok": True}

    @classmethod
    def join_room(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return _unsupported("join_room")

    @classmethod
    def leave_room(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return {"ok": True}

    @classmethod
    def send_message(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return _unsupported("send_message")

    @classmethod
    def get_local_ip(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return {"ok": True, "ip": "127.0.0.1", "port": DEFAULT_PORT}

    @classmethod
    def add_agent(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        payload = payload or {}
        engine = _engine()
        if not engine or not hasattr(engine, "network_register_agent"):
            return _unsupported("add_agent")
        agent_id = payload.get("agent_id") or f"agent-{payload.get('name', 'Agent')}"
        ok = bool(engine.network_register_agent(
            agent_id,
            payload.get("name") or "Agent",
            payload.get("persona") or "",
        ))
        return {"ok": ok, "agent_id": agent_id, "name": payload.get("name") or "Agent"}

    @classmethod
    def remove_agent(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        payload = payload or {}
        engine = _engine()
        if not engine or not hasattr(engine, "network_remove_agent"):
            return _unsupported("remove_agent")
        return {"ok": bool(engine.network_remove_agent(payload.get("agent_id") or ""))}

    @classmethod
    def list_agents(cls, payload: Optional[dict] = None) -> Dict[str, Any]:
        return {"ok": True, "agents": []}


__all__ = ["LANChat"]
