from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plugins.AITool.cai_extensions.agent.memory import (  # noqa: E402
    get_memory_manager,
    get_scoped_memory_manager,
    make_memory_scope_id,
    memory_manager_registry_snapshot,
    reset_memory_manager,
)
from plugins.AITool.cai_extensions.agent import memory as memory_module  # noqa: E402


def test_scope_id_is_stable_and_explicit():
    scope_id = make_memory_scope_id(
        scene_id="demo-scene",
        room_id="room-a",
        plan_id="plan-1",
        batch_id="batch-2",
        agent_id="layout-agent",
    )

    assert scope_id == make_memory_scope_id(
        scene_id="demo-scene",
        room_id="room-a",
        plan_id="plan-1",
        batch_id="batch-2",
        agent_id="layout-agent",
    )
    assert "scene=demo-scene" in scope_id
    assert "room=room-a" in scope_id
    assert "plan=plan-1" in scope_id
    assert "batch=batch-2" in scope_id
    assert "agent=layout-agent" in scope_id
    print("[OK] legacy memory scope id is stable and explicit")


def test_scoped_managers_do_not_leak_between_rooms():
    reset_memory_manager()
    room_a = get_scoped_memory_manager(scene_id="demo", room_id="room-a", plan_id="plan")
    room_b = get_scoped_memory_manager(scene_id="demo", room_id="room-b", plan_id="plan")

    room_a.record_conversation("room-a user", "room-a response")
    room_b.record_conversation("room-b user", "room-b response")

    assert room_a is get_scoped_memory_manager(scene_id="demo", room_id="room-a", plan_id="plan")
    assert room_a is not room_b
    assert "room-a user" in room_a.session.get_recent_conversation()
    assert "room-b user" not in room_a.session.get_recent_conversation()
    assert "room-b user" in room_b.session.get_recent_conversation()
    print("[OK] legacy scoped memory isolates rooms")


def test_reset_scoped_memory_keeps_other_scopes():
    reset_memory_manager()
    scope_a = make_memory_scope_id(scene_id="demo", room_id="room-a", plan_id="plan")
    scope_b = make_memory_scope_id(scene_id="demo", room_id="room-b", plan_id="plan")

    room_a = get_scoped_memory_manager(scene_id="demo", room_id="room-a", plan_id="plan")
    room_b = get_scoped_memory_manager(scene_id="demo", room_id="room-b", plan_id="plan")
    room_a.record_operation({"action": "add", "target": "angel statue"})
    room_b.record_operation({"action": "add", "target": "market stall"})

    reset_memory_manager(scope_a)
    fresh_room_a = get_scoped_memory_manager(scene_id="demo", room_id="room-a", plan_id="plan")
    same_room_b = get_scoped_memory_manager(scene_id="demo", room_id="room-b", plan_id="plan")

    assert fresh_room_a is not room_a
    assert fresh_room_a.session.get_recent_operations() == []
    assert same_room_b is room_b
    assert same_room_b.session.get_recent_operations()[0]["target"] == "market stall"
    assert scope_a != scope_b
    print("[OK] legacy scoped reset only clears the target scope")


def test_legacy_agent_coordinator_uses_room_scope_for_recall():
    from plugins.AITool.cai_extensions.agent.coordinator import AgentCoordinator

    reset_memory_manager()
    coordinator = AgentCoordinator()
    room_a_state = {"metadata": {"scene_name": "legacy_scene", "room_id": "room-a", "agent_id": "designer"}}
    room_b_state = {"metadata": {"scene_name": "legacy_scene", "room_id": "room-b", "agent_id": "designer"}}
    intent = {"action": "add", "target": "台灯", "confidence": 0.9}
    spatial = {"position": [0, 0, 0]}

    coordinator._record(intent, spatial, {"status": "planned_only"}, scene_state=room_a_state)
    coordinator._record(intent, spatial, {"status": "planned_only"}, scene_state=room_a_state)

    assert "连续添加" in coordinator._recall_similar(intent, scene_state=room_a_state)
    assert coordinator._recall_similar(intent, scene_state=room_b_state) == ""
    reset_memory_manager()
    print("[OK] legacy AgentCoordinator recall uses room scoped memory")


def test_legacy_agent_coordinator_uses_wrapped_lanchat_scope_for_recall():
    from plugins.AITool.cai_extensions.agent.coordinator import AgentCoordinator

    reset_memory_manager()
    coordinator = AgentCoordinator()
    room_a_state = {
        "metadata": {"scene_name": "legacy_scene"},
        "lanchat_memory_scope": {"room_id": "room-a", "agent_id": "designer"},
    }
    room_b_state = {
        "metadata": {"scene_name": "legacy_scene"},
        "lanchat_memory_scope": {"room_id": "room-b", "agent_id": "designer"},
    }
    intent = {"action": "add", "target": "壁灯", "confidence": 0.9}
    spatial = {"position": [0, 0, 0]}

    coordinator._record(intent, spatial, {"status": "planned_only"}, scene_state=room_a_state)
    coordinator._record(intent, spatial, {"status": "planned_only"}, scene_state=room_a_state)

    assert "连续添加" in coordinator._recall_similar(intent, scene_state=room_a_state)
    assert coordinator._recall_similar(intent, scene_state=room_b_state) == ""
    reset_memory_manager()
    print("[OK] legacy AgentCoordinator recall uses wrapped LANChat memory scope")


def test_master_agent_extracts_lanchat_memory_scope():
    from plugins.AITool.cai_extensions.agent.agent_adapter import MasterAgent

    agent = MasterAgent(fallback_chat=lambda _system, _messages: "fake")
    context = agent._extract_lanchat_context([
        (
            "【当前点名上下文】\n"
            "【链路上下文】room_id=room-7 agent_id=agent-a agent_name=灯光师\n"
            "本轮明确被 @ 的 AI 助手是：灯光师。"
        )
    ])

    assert context["room_id"] == "room-7"
    assert context["agent_id"] == "agent-a"
    assert context["agent_name"] == "灯光师"
    print("[OK] MasterAgent extracts LANChat memory scope")


def test_legacy_memory_registry_is_bounded_lru_without_payload_leak():
    reset_memory_manager()
    old_limit = memory_module._MEMORY_MAX_INSTANCES
    memory_module._MEMORY_MAX_INSTANCES = 3
    try:
        room_a = get_memory_manager("room-a")
        get_memory_manager("room-b")
        room_c = get_memory_manager("room-c")
        room_a.record_conversation("room-a secret note", "room-a response")

        assert get_memory_manager("room-a") is room_a

        room_d = get_memory_manager("room-d")
        snapshot = memory_manager_registry_snapshot()

        assert snapshot["size"] == 3
        assert snapshot["limit"] == 3
        assert "room-b" not in snapshot["scope_ids"]
        assert "room-a" in snapshot["scope_ids"]
        assert "room-c" in snapshot["scope_ids"]
        assert "room-d" in snapshot["scope_ids"]
        assert all("secret note" not in scope_id for scope_id in snapshot["scope_ids"])
        assert get_memory_manager("room-d") is room_d
        assert room_c is get_memory_manager("room-c")
    finally:
        memory_module._MEMORY_MAX_INSTANCES = old_limit
        reset_memory_manager()
    print("[OK] legacy memory registry is bounded by LRU without payload leakage")


if __name__ == "__main__":
    test_scope_id_is_stable_and_explicit()
    test_scoped_managers_do_not_leak_between_rooms()
    test_reset_scoped_memory_keeps_other_scopes()
    test_legacy_agent_coordinator_uses_room_scope_for_recall()
    test_legacy_agent_coordinator_uses_wrapped_lanchat_scope_for_recall()
    test_master_agent_extracts_lanchat_memory_scope()
    test_legacy_memory_registry_is_bounded_lru_without_payload_leak()
