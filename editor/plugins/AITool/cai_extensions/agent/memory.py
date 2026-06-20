"""Agent Memory 系统 — 2 层内存"""
from __future__ import annotations
import json, logging, os, time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class SessionMemory:
    def __init__(self, max_conversation_turns: int = 20, max_operations: int = 50):
        self.max_conversation_turns = max_conversation_turns
        self.max_operations = max_operations
        self.conversation_history: List[Dict[str, Any]] = []
        self.recent_operations: List[Dict[str, Any]] = []
        self.pending_conflicts: List[Dict[str, Any]] = []
        self._created_at = time.time()

    def add_conversation(self, user_text: str, assistant_response: str, metadata: Dict[str, Any] = None):
        turn = {"timestamp": time.time(), "user": user_text, "assistant": assistant_response, "metadata": metadata or {}}
        self.conversation_history.append(turn)
        if len(self.conversation_history) > self.max_conversation_turns:
            self.conversation_history = self.conversation_history[-self.max_conversation_turns:]

    def get_recent_conversation(self, n: int = 5) -> str:
        if not self.conversation_history: return "无历史对话"
        recent = self.conversation_history[-n:]
        return "\n".join(f" 用户: {t['user']}\n Agent: {t['assistant'][:200]}" for t in recent)

    def add_operation(self, operation: Dict[str, Any]):
        self.recent_operations.append(operation)
        if len(self.recent_operations) > self.max_operations:
            self.recent_operations = self.recent_operations[-self.max_operations:]

    def get_recent_operations(self, n: int = 10) -> List[Dict[str, Any]]:
        return self.recent_operations[-n:]

    def find_similar_operations(self, action: str, target_name: str, n: int = 3) -> List[Dict[str, Any]]:
        similar = []
        for op in reversed(self.recent_operations):
            if op.get("action") == action and _name_overlap(target_name, op.get("target", "")) > 0.3:
                similar.append(op)
                if len(similar) >= n: break
        return similar

    def clear(self):
        self.conversation_history.clear(); self.recent_operations.clear(); self.pending_conflicts.clear()

    def age_seconds(self) -> float: return time.time() - self._created_at


class SceneMemory:
    def __init__(self, scene_id: str = "default"):
        self.scene_id = scene_id
        self.style_bible: Dict[str, Any] = {"theme": "", "color_palette": [], "materials": [], "lighting": "", "mood": "", "avoid": []}
        self.objects_state: Dict[str, Dict[str, Any]] = {}
        self.operation_log: List[Dict[str, Any]] = []
        self.metadata: Dict[str, Any] = {"scene_name": "", "scene_type": "indoor", "room_size": [5.0, 3.0, 3.0], "zones": [], "partitions": []}
        self._created_at = time.time()

    def set_style_bible(self, bible: Dict[str, Any]): self.style_bible.update(bible)

    def get_style_bible_text(self) -> str:
        sb = self.style_bible; parts = []
        if sb.get("theme"): parts.append(f"主题: {sb['theme']}")
        if sb.get("color_palette"): parts.append(f"色调: {', '.join(sb['color_palette'])}")
        if sb.get("materials"): parts.append(f"材质: {', '.join(sb['materials'])}")
        if sb.get("mood"): parts.append(f"氛围: {sb['mood']}")
        if sb.get("avoid"): parts.append(f"避免: {', '.join(sb['avoid'])}")
        return "\n".join(parts) if parts else "无风格约束"

    def update_objects_state(self, objects: Dict[str, Dict[str, Any]]): self.objects_state = objects

    def get_objects_summary(self) -> str:
        if not self.objects_state: return "场景为空"
        return "\n".join(f"  - {v.get('name', k)}: pos={v.get('position', v.get('pos', [0,0,0]))}" for k, v in list(self.objects_state.items())[:50])

    def log_operation(self, op: Dict[str, Any]):
        op.setdefault("timestamp", time.time()); op.setdefault("scene_id", self.scene_id)
        self.operation_log.append(op)

    def save(self, filepath: str):
        data = {"scene_id": self.scene_id, "style_bible": self.style_bible, "objects_state": self.objects_state, "metadata": self.metadata, "operation_log": self.operation_log[-500:]}
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> "SceneMemory":
        with open(filepath, "r", encoding="utf-8") as f: data = json.load(f)
        inst = cls(scene_id=data.get("scene_id", "default"))
        inst.style_bible = data.get("style_bible", inst.style_bible)
        inst.objects_state = data.get("objects_state", {})
        inst.metadata = data.get("metadata", inst.metadata)
        inst.operation_log = data.get("operation_log", [])
        return inst

    def clear(self): self.operation_log.clear(); self.objects_state.clear()


class MemoryManager:
    def __init__(self, scene_id: str = "default"):
        self.session = SessionMemory()
        self.scene = SceneMemory(scene_id=scene_id)

    def record_conversation(self, user_text: str, assistant_response: str, metadata: Dict[str, Any] = None):
        self.session.add_conversation(user_text, assistant_response, metadata)
    def record_operation(self, op: Dict[str, Any]):
        self.session.add_operation(op); self.scene.log_operation(op)
    def set_style_bible(self, bible: Dict[str, Any]): self.scene.set_style_bible(bible)
    def update_scene_objects(self, objects: Dict[str, Dict[str, Any]]): self.scene.update_objects_state(objects)

    def get_context_for_prompt(self, user_text: str = "") -> Dict[str, Any]:
        return {"style_bible_text": self.scene.get_style_bible_text(), "conversation_history": self.session.get_recent_conversation(), "scene_objects_summary": self.scene.get_objects_summary(), "recent_operations": self.session.get_recent_operations(5), "scene_metadata": self.scene.metadata}
    def find_similar_operations(self, action: str, target: str) -> List[Dict[str, Any]]:
        return self.session.find_similar_operations(action, target)
    def save_scene(self, filepath: str): self.scene.save(filepath)
    def load_scene(self, filepath: str): self.scene = SceneMemory.load(filepath)
    def clear_session(self): self.session.clear()
    def clear_all(self): self.session.clear(); self.scene.clear()


def _name_overlap(a: str, b: str) -> float:
    if not a or not b: return 0.0
    set_a = set(a.lower()); set_b = set(b.lower())
    if not set_a or not set_b: return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


# ── 进程级分桶单例（房主侧共享，使同一场景记忆跨多次操作持久）────────────
import threading as _threading
_MEMORY_MAX_INSTANCES = 128
_MEMORY_INSTANCES: "OrderedDict[str, MemoryManager]" = OrderedDict()
_MEMORY_LOCK = _threading.Lock()


def _clean_scope_part(value: Any) -> str:
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text.replace("|", "_").replace("=", "_")


def make_memory_scope_id(
    scene_id: str = "default",
    *,
    room_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
    agent_id: str = "",
) -> str:
    """Build a stable legacy MemoryManager bucket id with explicit scope parts."""
    scene = _clean_scope_part(scene_id) or "default"
    parts = [("scene", scene)]
    for key, value in (
        ("room", room_id),
        ("plan", plan_id),
        ("batch", batch_id),
        ("agent", agent_id),
    ):
        cleaned = _clean_scope_part(value)
        if cleaned:
            parts.append((key, cleaned))
    if len(parts) == 1 and scene == "default":
        return "default"
    return "|".join(f"{key}={value}" for key, value in parts)


def get_memory_manager(scene_id: str = "default") -> "MemoryManager":
    """获取按 scene_id 分桶的 MemoryManager。

    旧实现是全进程单例，第一次用 default 创建后会忽略后续 scene_id，
    在多人/多房间场景下容易串记忆。这里保留同一 scene_id 内的连续记忆，
    但不同 room/plan 可以通过不同 scene_id 隔离。
    """
    key = str(scene_id or "default")
    with _MEMORY_LOCK:
        memory = _MEMORY_INSTANCES.get(key)
        if memory is not None:
            _MEMORY_INSTANCES.move_to_end(key)
            return memory
        memory = MemoryManager(scene_id=key)
        _MEMORY_INSTANCES[key] = memory
        _evict_memory_instances_locked()
        return memory


def get_scoped_memory_manager(
    scene_id: str = "default",
    *,
    room_id: str = "",
    plan_id: str = "",
    batch_id: str = "",
    agent_id: str = "",
) -> "MemoryManager":
    """获取按 scene/room/plan/batch/agent 显式分桶的旧 MemoryManager。"""
    return get_memory_manager(
        make_memory_scope_id(
            scene_id=scene_id,
            room_id=room_id,
            plan_id=plan_id,
            batch_id=batch_id,
            agent_id=agent_id,
        )
    )


def reset_memory_manager(scene_id: str | None = None) -> None:
    """重置记忆实例；传 scene_id 时只清理该场景。"""
    with _MEMORY_LOCK:
        if scene_id is None:
            _MEMORY_INSTANCES.clear()
        else:
            _MEMORY_INSTANCES.pop(str(scene_id or "default"), None)


def memory_manager_registry_snapshot() -> Dict[str, Any]:
    """Return a payload-safe snapshot of legacy memory buckets for observability."""
    with _MEMORY_LOCK:
        return {
            "size": len(_MEMORY_INSTANCES),
            "limit": max(1, int(_MEMORY_MAX_INSTANCES)),
            "scope_ids": list(_MEMORY_INSTANCES.keys()),
        }


def _evict_memory_instances_locked() -> None:
    limit = max(1, int(_MEMORY_MAX_INSTANCES))
    while len(_MEMORY_INSTANCES) > limit:
        evicted_scope, _ = _MEMORY_INSTANCES.popitem(last=False)
        logger.info("[MemoryManager] evicted legacy memory scope: %s", evicted_scope)


__all__ = ["SessionMemory", "SceneMemory", "MemoryManager",
           "make_memory_scope_id", "get_memory_manager", "get_scoped_memory_manager",
           "memory_manager_registry_snapshot", "reset_memory_manager"]
