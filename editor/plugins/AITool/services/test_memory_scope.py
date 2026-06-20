from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plugins.AITool.services.memory_scope import MemoryScope, MemoryScopeStore  # noqa: E402


def test_room_scopes_are_isolated():
    store = MemoryScopeStore()
    store.record(
        scope=MemoryScope(room_id="room-a", plan_id="seed-a"),
        entry_type="discussion",
        text="room-a wants an outdoor market",
        visibility="shared",
    )
    store.record(
        scope=MemoryScope(room_id="room-b", plan_id="seed-b"),
        entry_type="discussion",
        text="room-b wants an indoor hall",
        visibility="shared",
    )

    summary = store.summarize(room_id="room-a")

    assert "outdoor market" in summary["summary_text"]
    assert "indoor hall" not in summary["summary_text"]
    print("[OK] scoped memory isolates rooms")


def test_agent_scope_includes_shared_and_own_private_entries_only():
    store = MemoryScopeStore()
    store.record(
        scope=MemoryScope(room_id="room-a", plan_id="seed-a"),
        entry_type="seed_plan_confirmed",
        text="shared plan",
        visibility="shared",
    )
    store.record(
        scope=MemoryScope(room_id="room-a", plan_id="seed-a", agent_id="agent-layout"),
        entry_type="agent_note",
        text="layout private note",
        visibility="private",
    )
    store.record(
        scope=MemoryScope(room_id="room-a", plan_id="seed-a", agent_id="agent-style"),
        entry_type="agent_note",
        text="style private note",
        visibility="private",
    )

    summary = store.summarize(room_id="room-a", plan_id="seed-a", agent_id="agent-layout")

    assert "shared plan" in summary["summary_text"]
    assert "layout private note" in summary["summary_text"]
    assert "style private note" not in summary["summary_text"]
    print("[OK] scoped memory avoids cross-agent private leakage")


def test_actor_scope_filters_same_plan_interventions():
    store = MemoryScopeStore()
    store.record(
        scope=MemoryScope(room_id="room-a", plan_id="seed-a", batch_id="batch-1"),
        entry_type="intervention",
        text="statue should be smaller",
        actor_id="actor-statue",
        visibility="shared",
    )
    store.record(
        scope=MemoryScope(room_id="room-a", plan_id="seed-a", batch_id="batch-1"),
        entry_type="intervention",
        text="lamp should rotate",
        actor_id="actor-lamp",
        visibility="shared",
    )

    summary = store.summarize(room_id="room-a", plan_id="seed-a", actor_id="actor-statue")

    assert summary["actor_id"] == "actor-statue"
    assert "statue should be smaller" in summary["summary_text"]
    assert "lamp should rotate" not in summary["summary_text"]
    print("[OK] scoped memory filters interventions by actor within the same plan")


def test_scoped_memory_metadata_output_is_sanitized():
    store = MemoryScopeStore()
    entry = store.record(
        scope=MemoryScope(room_id="room-a", plan_id="seed-a", batch_id="batch-1"),
        entry_type="batch_review",
        text="batch accepted with placement adjustment",
        actor_id="actor-table",
        visibility="shared",
        metadata={
            "actor_id": "actor-table",
            "target_hint": "table",
            "reason": "layout conflict resolved",
            "prompt": "PRIVATE_PROMPT_SHOULD_NOT_LEAK",
            "provider": "internal-vlm-provider",
            "job_id": "job-secret-1",
            "scheduler_updates": [{"session_id": "exec-secret-1", "prompt": "nested-secret"}],
            "vlm_raw": {"finding_details": "raw geometry trace"},
            "nested": {
                "safe_note": "keep this",
                "runtime_context": {"token": "secret-token"},
                "custom_prompt": "nested custom secret",
            },
        },
    )

    public_entry = entry.as_dict()
    summary = store.summarize(room_id="room-a", plan_id="seed-a")

    assert public_entry["metadata"]["actor_id"] == "actor-table"
    assert public_entry["metadata"]["target_hint"] == "table"
    assert public_entry["metadata"]["reason"] == "layout conflict resolved"
    assert public_entry["metadata"]["nested"]["safe_note"] == "keep this"
    public_text = repr(public_entry) + repr(summary)
    assert "PRIVATE_PROMPT_SHOULD_NOT_LEAK" not in public_text
    assert "internal-vlm-provider" not in public_text
    assert "job-secret-1" not in public_text
    assert "exec-secret-1" not in public_text
    assert "raw geometry trace" not in public_text
    assert "secret-token" not in public_text
    assert "nested custom secret" not in public_text
    print("[OK] scoped memory metadata output is sanitized")


if __name__ == "__main__":
    test_room_scopes_are_isolated()
    test_agent_scope_includes_shared_and_own_private_entries_only()
    test_actor_scope_filters_same_plan_interventions()
    test_scoped_memory_metadata_output_is_sanitized()
