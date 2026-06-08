"""多人协同管理器"""
from __future__ import annotations
import logging, threading, time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_DEFAULT_LOCK_TIMEOUT = 30.0; _PREVIEW_COLLISION_DELTA = 0.5

class CollaborationManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._object_locks: Dict[str, Dict[str, Any]] = {}
        self._user_status: Dict[str, Dict[str, Any]] = {}
        self._conflict_log: List[Dict[str, Any]] = []

    def lock_object(self, object_id: str, user_id: str, operation: str = "modify") -> bool:
        with self._lock:
            self._cleanup_expired_locks()
            existing = self._object_locks.get(object_id)
            if existing:
                if existing["user_id"] == user_id: existing["timestamp"] = time.time(); return True
                else: logger.info("[Collab] lock conflict: %s by %s (req %s)", object_id, existing["user_id"], user_id); return False
            self._object_locks[object_id] = {"user_id": user_id, "timestamp": time.time(), "operation": operation}; return True

    def unlock_object(self, object_id: str, user_id: str) -> bool:
        with self._lock:
            if self._object_locks.get(object_id, {}).get("user_id") == user_id: del self._object_locks[object_id]; return True
            return False

    def is_locked(self, object_id: str) -> Optional[str]:
        with self._lock: self._cleanup_expired_locks(); return self._object_locks.get(object_id, {}).get("user_id")

    def broadcast_intent(self, user_id: str, tooltip: str, preview_position: List[float] = None, status: str = "placing_object"):
        with self._lock:
            self._user_status[user_id] = {"status": status, "tooltip": tooltip, "preview_position": list(preview_position) if preview_position else None, "timestamp": time.time()}

    def clear_intent(self, user_id: str):
        with self._lock: self._user_status.pop(user_id, None)

    def get_active_intents(self) -> Dict[str, Dict[str, Any]]:
        with self._lock: self._cleanup_expired_status(); return dict(self._user_status)

    def get_status_bar_text(self) -> str:
        with self._lock:
            active = [f"{uid}: {s['tooltip']}" for uid, s in self._user_status.items() if s["status"] != "idle"]
            return " | ".join(active) if active else "无活跃操作"

    def check_preview_collision(self, user_id: str, position: List[float], exclude_user: bool = True) -> Optional[str]:
        if not position or len(position) < 2: return None
        with self._lock:
            for uid, s in self._user_status.items():
                if exclude_user and uid == user_id: continue
                op = s.get("preview_position")
                if not op or len(op) < 2: continue
                if ((position[0]-op[0])**2 + (position[2]-op[2])**2)**0.5 < _PREVIEW_COLLISION_DELTA: return uid
        return None

    def _cleanup_expired_locks(self):
        now = time.time()
        for oid in [o for o, l in self._object_locks.items() if now - l["timestamp"] > _DEFAULT_LOCK_TIMEOUT]:
            del self._object_locks[oid]
    def _cleanup_expired_status(self):
        now = time.time()
        for uid in [u for u, s in self._user_status.items() if now - s["timestamp"] > 60.0]:
            del self._user_status[uid]
    def clear(self):
        with self._lock: self._object_locks.clear(); self._user_status.clear(); self._conflict_log.clear()

_COLLAB_INSTANCE: Optional[CollaborationManager] = None; _COLLAB_LOCK = threading.Lock()
def get_collaboration_manager() -> CollaborationManager:
    global _COLLAB_INSTANCE
    if _COLLAB_INSTANCE is None:
        with _COLLAB_LOCK:
            if _COLLAB_INSTANCE is None: _COLLAB_INSTANCE = CollaborationManager()
    return _COLLAB_INSTANCE

__all__ = ["CollaborationManager", "get_collaboration_manager"]
