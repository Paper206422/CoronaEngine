"""Thin Python proxy for C++ collaboration state.

Python agents may run local AI/tool logic, but network transport, locks,
preview intents, room state, member state, and agent roster live in C++.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_PREVIEW_COLLISION_DELTA = 0.5


def _engine():
    try:
        import CoronaEngine  # type: ignore

        return CoronaEngine
    except Exception as exc:
        logger.debug("[Collab] CoronaEngine bindings unavailable: %s", exc)
        return None


def _position3(position: Optional[List[float]]) -> List[float]:
    values = list(position or [])
    while len(values) < 3:
        values.append(0.0)
    return [float(values[0]), float(values[1]), float(values[2])]


class CollaborationManager:
    def lock_object(self, object_id: str, user_id: str, operation: str = "modify") -> bool:
        engine = _engine()
        if not engine or not hasattr(engine, "network_lock_object"):
            return False
        return bool(engine.network_lock_object(object_id, user_id, operation))

    def unlock_object(self, object_id: str, user_id: str) -> bool:
        engine = _engine()
        if not engine or not hasattr(engine, "network_unlock_object"):
            return False
        return bool(engine.network_unlock_object(object_id, user_id))

    def is_locked(self, object_id: str) -> Optional[str]:
        engine = _engine()
        if not engine or not hasattr(engine, "network_locked_by"):
            return None
        owner = engine.network_locked_by(object_id)
        return owner or None

    def broadcast_intent(
        self,
        user_id: str,
        tooltip: str,
        preview_position: List[float] = None,
        status: str = "placing_object",
    ):
        engine = _engine()
        if engine and hasattr(engine, "network_broadcast_intent"):
            engine.network_broadcast_intent(user_id, tooltip, _position3(preview_position), status)

    def clear_intent(self, user_id: str):
        self.broadcast_intent(user_id, "", [0.0, 0.0, 0.0], "idle")

    def get_active_intents(self) -> Dict[str, Dict[str, Any]]:
        return {}

    def get_status_bar_text(self) -> str:
        return "无活跃操作"

    def check_preview_collision(
        self,
        user_id: str,
        position: List[float],
        exclude_user: bool = True,
    ) -> Optional[str]:
        engine = _engine()
        if not engine or not hasattr(engine, "network_check_preview_collision"):
            return None
        conflict = engine.network_check_preview_collision(
            user_id, _position3(position), _PREVIEW_COLLISION_DELTA
        )
        if exclude_user and conflict == user_id:
            return None
        return conflict or None

    def clear(self):
        return None


_COLLAB_INSTANCE: Optional[CollaborationManager] = None
_COLLAB_LOCK = threading.Lock()


def get_collaboration_manager() -> CollaborationManager:
    global _COLLAB_INSTANCE
    if _COLLAB_INSTANCE is None:
        with _COLLAB_LOCK:
            if _COLLAB_INSTANCE is None:
                _COLLAB_INSTANCE = CollaborationManager()
    return _COLLAB_INSTANCE


__all__ = ["CollaborationManager", "get_collaboration_manager"]
