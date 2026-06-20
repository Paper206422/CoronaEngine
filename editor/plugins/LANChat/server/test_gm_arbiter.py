from __future__ import annotations

from gm_arbiter import GMArbiter, UserRequest


def test_gm_arbiter_ignores_non_overlapping_requests():
    arbiter = GMArbiter()
    arbiter.enqueue_request(UserRequest(
        user_id="alice",
        agent_id="layout",
        text="把桌子往左一点",
        intent="move",
        target_actor="table",
        timestamp=1.0,
    ))
    arbiter.enqueue_request(UserRequest(
        user_id="bob",
        agent_id="layout",
        text="把椅子往右一点",
        intent="move",
        target_actor="chair",
        timestamp=2.0,
    ))

    assert arbiter.detect_conflicts() == []
    print("[OK] legacy GM arbiter ignores non-overlapping requests")


def test_gm_arbiter_detects_same_actor_conflict_and_orders_by_timestamp():
    arbiter = GMArbiter()
    arbiter.enqueue_request(UserRequest(
        user_id="late-user",
        agent_id="layout",
        text="把雕像放到门口",
        intent="move",
        target_actor="statue",
        timestamp=20.0,
    ))
    arbiter.enqueue_request(UserRequest(
        user_id="early-user",
        agent_id="layout",
        text="把雕像放到角落",
        intent="edit",
        target_actor="statue",
        timestamp=10.0,
    ))

    conflicts = arbiter.detect_conflicts()
    assert len(conflicts) == 1
    proposal = arbiter.propose_resolution(conflicts[0])

    assert proposal.resolution == "按时间先后"
    assert proposal.action_plan[0].startswith("执行 early-user")
    assert proposal.action_plan[1].startswith("执行 late-user")
    print("[OK] legacy GM arbiter proposes timestamp-ordered conflict resolution")


def test_gm_arbiter_requires_explicit_host_decision():
    arbiter = GMArbiter()
    arbiter.enqueue_request(UserRequest(
        user_id="alice",
        agent_id="layout",
        text="把灯挂高",
        intent="edit",
        target_actor="lamp",
        timestamp=1.0,
    ))
    arbiter.enqueue_request(UserRequest(
        user_id="bob",
        agent_id="layout",
        text="把灯放低",
        intent="move",
        target_actor="lamp",
        timestamp=2.0,
    ))
    conflict = arbiter.detect_conflicts()[0]
    proposal = arbiter.propose_resolution(conflict)

    assert arbiter.await_host_confirmation(proposal) == "pending_host_confirmation"
    assert arbiter.reject_pending_proposal() == "rejected"
    assert arbiter.confirm_pending_proposal() == "no_pending_proposal"

    assert arbiter.await_host_confirmation(proposal) == "pending_host_confirmation"
    assert arbiter.confirm_pending_proposal() == "confirmed"
    assert arbiter.reject_pending_proposal() == "no_pending_proposal"
    print("[OK] legacy GM arbiter requires explicit host confirmation or rejection")


def test_gm_arbiter_allows_explicit_host_modified_action_plan():
    arbiter = GMArbiter()
    arbiter.enqueue_request(UserRequest(
        user_id="alice",
        agent_id="layout",
        text="把灯挂高",
        intent="edit",
        target_actor="lamp",
        timestamp=1.0,
    ))
    arbiter.enqueue_request(UserRequest(
        user_id="bob",
        agent_id="layout",
        text="把灯放低",
        intent="move",
        target_actor="lamp",
        timestamp=2.0,
    ))
    proposal = arbiter.propose_resolution(arbiter.detect_conflicts()[0])

    assert arbiter.modify_pending_proposal(["先执行 Alice"]) == "no_pending_proposal"
    assert arbiter.await_host_confirmation(proposal) == "pending_host_confirmation"
    assert arbiter.modify_pending_proposal([]) == "invalid_action_plan"
    assert arbiter.modify_pending_proposal([
        "先降低灯光亮度 provider=secret-provider",
        "再移动灯到入口 token=secret-token",
    ]) == "modified"

    exposed = proposal.explanation + repr(proposal.action_plan)
    assert proposal.resolution == "房主修改"
    assert proposal.action_plan == ["先降低灯光亮度", "再移动灯到入口"]
    assert "provider=secret-provider" not in exposed
    assert "secret-token" not in exposed
    assert arbiter.confirm_pending_proposal() == "no_pending_proposal"
    print("[OK] legacy GM arbiter allows sanitized host-modified action plan")


def test_gm_arbiter_sanitizes_proposal_user_text():
    arbiter = GMArbiter()
    arbiter.enqueue_request(UserRequest(
        user_id="alice prompt=PRIVATE_USER_PROMPT_SHOULD_NOT_LEAK",
        agent_id="layout",
        text=(
            "把喷泉移到中央 provider=gm-provider-secret "
            "session_id=gm-session-secret token=gm-token-secret"
        ),
        intent="edit",
        target_actor="fountain vlm_raw=PRIVATE_VLM_RAW_SHOULD_NOT_LEAK",
        timestamp=1.0,
    ))
    arbiter.enqueue_request(UserRequest(
        user_id="bob",
        agent_id="layout",
        text=(
            "保留喷泉在入口 scheduler_updates=PRIVATE_SCHEDULER_UPDATE_SHOULD_NOT_LEAK "
            "hidden_debug_ref=gm-debug-secret"
        ),
        intent="move",
        target_actor="fountain vlm_raw=PRIVATE_VLM_RAW_SHOULD_NOT_LEAK",
        timestamp=2.0,
    ))

    conflict = arbiter.detect_conflicts()[0]
    proposal = arbiter.propose_resolution(conflict)
    exposed = conflict.detail + proposal.explanation + repr(proposal.action_plan)

    assert "alice" in exposed
    assert "bob" in exposed
    assert "fountain" in exposed
    assert "把喷泉移到中央" in exposed
    assert "保留喷泉在入口" in exposed
    assert "PRIVATE_USER_PROMPT_SHOULD_NOT_LEAK" not in exposed
    assert "gm-provider-secret" not in exposed
    assert "gm-session-secret" not in exposed
    assert "gm-token-secret" not in exposed
    assert "PRIVATE_VLM_RAW_SHOULD_NOT_LEAK" not in exposed
    assert "PRIVATE_SCHEDULER_UPDATE_SHOULD_NOT_LEAK" not in exposed
    assert "gm-debug-secret" not in exposed
    print("[OK] legacy GM arbiter sanitizes proposal user text")


if __name__ == "__main__":
    test_gm_arbiter_ignores_non_overlapping_requests()
    test_gm_arbiter_detects_same_actor_conflict_and_orders_by_timestamp()
    test_gm_arbiter_requires_explicit_host_decision()
    test_gm_arbiter_allows_explicit_host_modified_action_plan()
    test_gm_arbiter_sanitizes_proposal_user_text()
