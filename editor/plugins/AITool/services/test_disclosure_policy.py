from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from plugins.AITool.services.disclosure_policy import DisclosurePolicy  # noqa: E402
from plugins.AITool.services.interaction_coordinator import ChatMessage, InteractionCoordinator  # noqa: E402
from plugins.AITool.services.interaction_coordinator import BatchEvent  # noqa: E402


def _plan():
    return {
        "plan_id": "seed-1",
        "version": 1,
        "status": "proposed",
        "scene_type": "outdoor",
        "intent_summary": "室外暗黑集市，分批生成",
        "conflicts": ["用户A要天使雕塑，用户B担心风格冲突"],
        "style_constraints": ["暗黑集市"],
        "placement_constraints": ["接地，不穿模"],
        "prompt": "INTERNAL RAW PROMPT",
        "tool_name": "hunyuan_internal",
        "batch_id": "r1_OBJECTS_b1",
    }


def test_disclosure_policy_splits_host_participant_agent_gm_views():
    policy = DisclosurePolicy()
    events = {
        audience: policy.disclose(
            room_id="room-a",
            stage="proposed",
            audience=audience,
            progress=0,
            plan=_plan(),
        )
        for audience in ("host", "participant", "agent", "gm")
    }

    assert events["host"].requires_confirmation is True
    assert "confirm_plan" in events["host"].available_actions
    assert "clarify_intent" in events["participant"].available_actions
    assert "execute_constraints" in events["agent"].available_actions
    assert "resolve_conflict" in events["gm"].available_actions
    assert "潜在冲突" in events["gm"].public_message or "冲突" in events["gm"].public_message
    print("[OK] DisclosurePolicy exposes role-specific actions and messages")


def test_disclosure_policy_does_not_leak_internal_fields():
    policy = DisclosurePolicy()
    participant = policy.disclose(
        room_id="room-a",
        stage="batch",
        audience="participant",
        progress=40,
        plan=_plan(),
        debug_ref="trace-1",
    )
    text = str(participant.as_dict())

    assert "INTERNAL RAW PROMPT" not in text
    assert "hunyuan_internal" not in text
    assert "r1_OBJECTS_b1" not in text
    assert "hidden_debug_ref" not in participant.as_dict()
    assert "trace-1" not in text
    assert participant.hidden_debug_ref == "trace-1"
    assert "40%" in participant.public_message
    print("[OK] DisclosurePolicy keeps internal chain/tool/provider details out of public payload")


def test_disclosure_policy_queued_stage_is_not_generating_zero_percent():
    policy = DisclosurePolicy()
    host = policy.disclose(
        room_id="room-a",
        stage="queued",
        audience="host",
        progress=0,
        plan=_plan(),
    )
    participant = policy.disclose(
        room_id="room-a",
        stage="queued",
        audience="participant",
        progress=0,
        plan=_plan(),
    )

    assert host.stage == "排队中"
    assert participant.stage == "排队中"
    assert "等待资源" in host.public_message
    assert "已排队" in participant.public_message
    assert "生成中 0%" not in participant.public_message
    assert "0%" not in participant.public_message
    assert "request_add" in participant.available_actions
    print("[OK] DisclosurePolicy maps queued jobs to waiting-resource copy, not generating 0%")


def test_disclosure_policy_recursively_sanitizes_nested_metadata():
    policy = DisclosurePolicy()
    participant = policy.disclose(
        room_id="room-a",
        stage="intervention",
        audience="participant",
        progress=0,
        plan=_plan(),
        intervention={
            "intent_type": "add",
            "apply_policy": "next_batch",
            "priority": 1,
            "target_hint": "一个天使雕塑",
            "scheduler_update_summary": {
                "attempted_count": 1,
                "updated_count": 1,
                "failed_count": 0,
                "deferred_to_pending": False,
                "reason": "queued future generation job accepted the intervention update",
            },
            "scheduler_updates": [{"job_id": "gen-hidden", "success": True}],
            "finding_details": [{"prompt": "hidden nested prompt", "job_id": "hidden-job"}],
            "prompt": "hidden prompt",
            "job_id": "hidden-job",
        },
        review={
            "status": "warning",
            "warnings": [{"tool_name": "hidden-tool", "message": "公开警告"}],
            "repair_count": 1,
            "raw_prompt": "hidden review prompt",
        },
    )

    data = participant.as_dict()
    text = str(data)
    intervention = data["metadata"]["intervention"]
    review = data["metadata"]["review"]
    assert intervention["target_hint"] == "一个天使雕塑"
    assert intervention["scheduler_update_summary"]["updated_count"] == 1
    assert review["repair_count"] == 1
    assert "scheduler_updates" not in intervention
    assert "finding_details" not in intervention
    assert "job_id" not in text
    assert "hidden" not in text.lower()
    assert "raw_prompt" not in text
    assert "tool_name" not in text
    print("[OK] DisclosurePolicy recursively sanitizes nested metadata")


def test_disclosure_policy_marks_host_confirmation_interventions():
    policy = DisclosurePolicy()
    host = policy.disclose(
        room_id="room-a",
        stage="draft",
        audience="host",
        progress=0,
        plan=_plan(),
        intervention={
            "intent_type": "conflict",
            "apply_policy": "host_confirmation",
            "priority": 2,
            "proposal_id": "cr-1",
            "target_hint": "入口摊位",
            "prompt": "INTERNAL",
        },
    )
    participant = policy.disclose(
        room_id="room-a",
        stage="draft",
        audience="participant",
        progress=0,
        plan=_plan(),
        intervention={
            "intent_type": "conflict",
            "apply_policy": "host_confirmation",
            "priority": 2,
            "proposal_id": "cr-1",
            "target_hint": "入口摊位",
        },
    )

    assert host.requires_confirmation is True
    assert "confirm_conflict_resolution" in host.available_actions
    assert "reject_conflict_resolution" in host.available_actions
    assert host.metadata["intervention"]["proposal_id"] == "cr-1"
    assert host.metadata["intervention"]["target_hint"] == "入口摊位"
    assert participant.requires_confirmation is False
    assert "INTERNAL" not in str(host.as_dict())
    print("[OK] DisclosurePolicy marks host-confirmation interventions without leaking internals")


def test_coordinator_records_disclosure_events_for_seed_plan_and_intervention():
    coordinator = InteractionCoordinator()
    coordinator.ingest_message(ChatMessage(
        room_id="room-a",
        sender_id="host-a",
        sender_name="房主",
        is_host=True,
        text="形成方案：室外暗黑集市，等待确认方案",
    ))
    plan = coordinator.active_plan_for_room("room-a")
    assert plan is not None
    coordinator.confirm_seed_plan(plan.plan_id, "host-a")
    ref = coordinator.execute_confirmed_plan(plan.plan_id)
    coordinator.ingest_batch_event(BatchEvent(
        room_id="room-a",
        plan_id=plan.plan_id,
        session_id=ref.session_id,
        batch_id="r1_OBJECTS_b1",
        stage="OBJECTS#1",
        status="done",
        progress=60,
        message="第一批已完成，可继续介入。",
        intervention_window_open=True,
    ))
    coordinator.ingest_message(ChatMessage(
        room_id="room-a",
        sender_id="user-b",
        text="第一批后补一个天使雕塑",
    ))

    events = [event.as_dict() for event in coordinator.disclosure_events]
    audiences = {event["audience"] for event in events}
    stages = {event["stage"] for event in events}
    intervention_events = [
        event for event in events
        if event["stage"] == "可介入窗口" and event["audience"] == "participant"
    ]

    assert {"host", "participant", "agent", "gm"}.issubset(audiences)
    assert "等待房主确认" in stages
    assert "已确认方案" in stages
    assert "排队中" in stages
    assert "可介入窗口" in stages
    assert intervention_events
    assert any("第一批已完成" in event["public_message"] for event in intervention_events)
    assert "天使雕塑" in intervention_events[-1]["public_message"]
    assert any(
        event["metadata"]["intervention"].get("status_message") == "第一批已完成，可继续介入。"
        for event in intervention_events
    )
    assert "天使雕塑" in intervention_events[-1]["metadata"]["intervention"]["target_hint"]
    assert not any("prompt" in str(event).lower() for event in events)
    print("[OK] InteractionCoordinator records safe disclosure events across lifecycle")


if __name__ == "__main__":
    test_disclosure_policy_splits_host_participant_agent_gm_views()
    test_disclosure_policy_does_not_leak_internal_fields()
    test_disclosure_policy_queued_stage_is_not_generating_zero_percent()
    test_disclosure_policy_recursively_sanitizes_nested_metadata()
    test_disclosure_policy_marks_host_confirmation_interventions()
    test_coordinator_records_disclosure_events_for_seed_plan_and_intervention()
