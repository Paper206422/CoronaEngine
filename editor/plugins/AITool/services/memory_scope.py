from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


_SENSITIVE_METADATA_KEYS = {
    "api_key",
    "auth",
    "debug",
    "debug_trace",
    "error_trace",
    "finding_details",
    "hidden_debug_ref",
    "internal",
    "job_id",
    "llm_request",
    "llm_response",
    "model_config",
    "prompt",
    "provider",
    "raw_prompt",
    "request",
    "response",
    "runtime_context",
    "scheduler_updates",
    "session_id",
    "stack",
    "trace",
    "tool_call",
    "tool_calls",
    "token",
    "vlm_raw",
}


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_lower in _SENSITIVE_METADATA_KEYS or key_lower.endswith("_prompt"):
                continue
            safe[key_text] = _sanitize_metadata(item)
        return safe
    if isinstance(value, list):
        return [_sanitize_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_metadata(item) for item in value]
    return value


@dataclass(frozen=True)
class MemoryScope:
    room_id: str
    plan_id: str = ""
    agent_id: str = ""
    batch_id: str = ""

    def key(self) -> tuple[str, str, str, str]:
        return (self.room_id or "default", self.plan_id or "", self.agent_id or "", self.batch_id or "")

    def matches(self, other: "MemoryScope") -> bool:
        room_id, plan_id, agent_id, batch_id = other.key()
        return (
            self.room_id == room_id
            and (not plan_id or self.plan_id == plan_id)
            and (not agent_id or self.agent_id in {"", agent_id})
            and (not batch_id or self.batch_id in {"", batch_id})
        )


@dataclass
class ScopedMemoryEntry:
    scope: MemoryScope
    entry_type: str
    text: str
    actor_id: str = ""
    visibility: str = "private"
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": {
                "room_id": self.scope.room_id,
                "plan_id": self.scope.plan_id,
                "agent_id": self.scope.agent_id,
                "batch_id": self.scope.batch_id,
            },
            "entry_type": self.entry_type,
            "text": self.text,
            "actor_id": self.actor_id,
            "visibility": self.visibility,
            "metadata": _sanitize_metadata(self.metadata),
            "timestamp": self.timestamp,
        }


class MemoryScopeStore:
    """Small in-process scoped memory for multi-user / multi-agent control flow.

    The old scene memory is intentionally left untouched. This store gives the
    coordinator a deterministic place to persist room, plan, agent, and batch
    summaries without leaking one participant's context into another scope.
    """

    def __init__(self, *, max_entries_per_room: int = 200) -> None:
        self._max_entries_per_room = max(1, int(max_entries_per_room))
        self._entries_by_room: dict[str, list[ScopedMemoryEntry]] = {}

    def record(
        self,
        *,
        scope: MemoryScope,
        entry_type: str,
        text: str,
        actor_id: str = "",
        visibility: str = "private",
        metadata: dict[str, Any] | None = None,
    ) -> ScopedMemoryEntry:
        entry = ScopedMemoryEntry(
            scope=scope,
            entry_type=entry_type,
            text=str(text or ""),
            actor_id=str(actor_id or ""),
            visibility=str(visibility or "private"),
            metadata=dict(metadata or {}),
        )
        bucket = self._entries_by_room.setdefault(scope.room_id or "default", [])
        bucket.append(entry)
        if len(bucket) > self._max_entries_per_room:
            del bucket[: len(bucket) - self._max_entries_per_room]
        return entry

    def query(
        self,
        *,
        room_id: str,
        plan_id: str = "",
        agent_id: str = "",
        batch_id: str = "",
        actor_id: str = "",
        visibility: str | None = None,
        limit: int = 20,
    ) -> list[ScopedMemoryEntry]:
        target = MemoryScope(room_id=room_id or "default", plan_id=plan_id, agent_id=agent_id, batch_id=batch_id)
        actor_filter = str(actor_id or "")
        entries = self._entries_by_room.get(target.room_id, [])
        result: list[ScopedMemoryEntry] = []
        for entry in reversed(entries):
            if not entry.scope.matches(target):
                continue
            if actor_filter and entry.actor_id != actor_filter:
                continue
            if visibility is not None and entry.visibility != visibility:
                continue
            result.append(entry)
            if len(result) >= limit:
                break
        return list(reversed(result))

    def summarize(
        self,
        *,
        room_id: str,
        plan_id: str = "",
        agent_id: str = "",
        batch_id: str = "",
        actor_id: str = "",
        visibility: str | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        entries = self.query(
            room_id=room_id,
            plan_id=plan_id,
            agent_id=agent_id,
            batch_id=batch_id,
            actor_id=actor_id,
            visibility=visibility,
            limit=limit,
        )
        return {
            "room_id": room_id or "default",
            "plan_id": plan_id,
            "agent_id": agent_id,
            "batch_id": batch_id,
            "actor_id": actor_id,
            "entries": [entry.as_dict() for entry in entries],
            "summary_text": "\n".join(
                f"[{entry.entry_type}] {entry.text}" for entry in entries if entry.text
            ),
        }

    def clear_room(self, room_id: str) -> None:
        self._entries_by_room.pop(room_id or "default", None)


__all__ = ["MemoryScope", "MemoryScopeStore", "ScopedMemoryEntry"]
