"""极简事件总线 — 单机内存发布/订阅"""
from __future__ import annotations
import asyncio, logging, threading, time, uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_EVENT_BUS_INSTANCE: Optional["EventBus"] = None
_EVENT_BUS_LOCK = threading.Lock()

class EventBus:
    def __init__(self, max_history: int = 10000):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._history: List[Dict[str, Any]] = []
        self._max_history = max_history
        self._lock = threading.RLock()

    def publish(self, event: Dict[str, Any]) -> int:
        event.setdefault("event_id", f"evt_{uuid.uuid4().hex[:12]}")
        event.setdefault("timestamp", time.time())
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            index = len(self._history) - 1
            event["_history_index"] = index
        for q in self._queues.values():
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("[EventBus] queue full, dropped: %s", event.get("event_type"))
        logger.debug("[EventBus] published %s (idx=%d)", event.get("event_type"), index)
        return index

    def subscribe(self, user_id: str) -> asyncio.Queue:
        with self._lock:
            if user_id not in self._queues:
                self._queues[user_id] = asyncio.Queue(maxsize=500)
                logger.info("[EventBus] %s subscribed (%d total)", user_id, len(self._queues))
            return self._queues[user_id]

    def unsubscribe(self, user_id: str):
        with self._lock:
            self._queues.pop(user_id, None)

    def replay(self, since_index: int = 0, scene_id: str = None) -> List[Dict[str, Any]]:
        with self._lock:
            events = self._history[since_index:]
        if scene_id:
            events = [e for e in events if e.get("scene_id") == scene_id]
        return events

    @property
    def subscriber_count(self) -> int:
        with self._lock: return len(self._queues)
    @property
    def history_size(self) -> int:
        with self._lock: return len(self._history)

    def clear(self):
        with self._lock:
            self._history.clear()
            self._queues.clear()

class EventType:
    ADD_OBJECT = "add_object"; DELETE_OBJECT = "delete_object"
    MOVE_OBJECT = "move_object"; MODIFY_OBJECT = "modify_object"
    INIT_PROJECT = "init_project"; CREATE_SCENE = "create_scene"
    STYLE_ALERT = "style_alert"; USER_INTENT = "user_intent"
    OPERATION_COMPLETE = "operation_complete"; CONFLICT_DETECTED = "conflict_detected"

def get_event_bus() -> EventBus:
    global _EVENT_BUS_INSTANCE
    if _EVENT_BUS_INSTANCE is None:
        with _EVENT_BUS_LOCK:
            if _EVENT_BUS_INSTANCE is None:
                _EVENT_BUS_INSTANCE = EventBus()
    return _EVENT_BUS_INSTANCE

__all__ = ["EventBus", "EventType", "get_event_bus"]
