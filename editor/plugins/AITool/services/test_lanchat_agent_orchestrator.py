from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from plugins.AITool.services.lanchat_agent_orchestrator import LanChatAgentOrchestrator  # noqa: E402
from plugins.AITool.services.lanchat_host_action_executor import LanChatHostActionExecutor  # noqa: E402
from plugins.AITool.services.lanchat_agent_worker import LANChatAgentWorker  # noqa: E402
from plugins.AITool.services.lanchat_scene_runtime import get_lanchat_scene_runtime  # noqa: E402


def _agent_factory():
    def _agent(persona, messages):
        assert messages
        return f"agent-reply persona={persona or 'none'} messages={len(messages)}"

    return _agent


def _trigger(text="@小B 添加一个篝火", agent_name="小B"):
    return {
        "trigger_id": "m1:a1",
        "message_id": "m1",
        "room_id": "r1",
        "sender_id": "user-a",
        "sender_name": "用户A",
        "agent_id": "agent-b",
        "agent_name": agent_name,
        "persona": "山贼",
        "text": text,
        "history": [
            {"message_id": "m0", "from": "用户A", "text": "我们做一个营地"},
            {"message_id": "m1", "from": "用户A", "text": text},
        ],
    }


class FakeEngine:
    def __init__(self, triggers):
        self.triggers = list(triggers)
        self.replies = []
        self.intents = []
        self.system_messages = []

    def network_pop_lanchat_agent_trigger(self):
        return self.triggers.pop(0) if self.triggers else None

    def network_send_agent_reply(self, agent_id, agent_name, text):
        self.replies.append((agent_id, agent_name, text))
        return True

    def network_send_agent_reply_ex(
        self,
        agent_id,
        agent_name,
        text,
        message_kind="agent_reply",
        target_agent_id="",
        correlation_id="",
        metadata_json="",
    ):
        self.replies.append((
            agent_id,
            agent_name,
            text,
            message_kind,
            target_agent_id,
            correlation_id,
            metadata_json,
        ))
        return True

    def network_broadcast_intent(self, user_id, tooltip, preview_position, status):
        self.intents.append((user_id, tooltip, preview_position, status))
        return True

    def network_send_system_message(self, sender_id, sender_name, text):
        self.system_messages.append((sender_id, sender_name, text))
        return True

    def network_send_system_message_ex(
        self,
        sender_id,
        sender_name,
        text,
        message_kind="agent_reply",
        correlation_id="",
        metadata_json="",
    ):
        self.system_messages.append((
            sender_id,
            sender_name,
            text,
            message_kind,
            correlation_id,
            metadata_json,
        ))
        return True


class FakeGate:
    def __init__(self):
        self.calls = 0

    def run(self, fn, *args, **kwargs):
        self.calls += 1
        return fn(*args, **kwargs)


class FakeHostActionExecutor:
    def __init__(self):
        self.payloads = []

    def enqueue_and_process(self, payload):
        self.payloads.append(dict(payload))
        return None


def test_regular_role_agent_reply():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    result = orch.handle_trigger(_trigger())
    assert result.sender_id == "agent-b"
    assert result.sender_name == "小B"
    assert "agent-reply" in result.text
    assert result.discussion_state.pending_intents
    print("[OK] regular role agent reply goes through orchestrator")


def test_current_mentioned_agent_identity_overrides_history_mentions():
    captured = {}

    def agent_factory():
        def _agent(persona, messages):
            captured["messages"] = list(messages)
            return "我就是小D，可以继续处理。"

        return _agent

    trigger = _trigger("@小D 我明明是找你的呀", "小D")
    trigger["agent_id"] = "agent-d"
    trigger["history"] = [
        {"message_id": "m0", "from": "房主", "text": "@学者 你好"},
        {"message_id": "m1", "from": "学者", "text": "若需要我参与，请直接 @学者。"},
        {"message_id": "m2", "from": "房主", "text": "@小D 我明明是找你的呀"},
    ]

    orch = LanChatAgentOrchestrator(agent_factory=agent_factory)
    result = orch.handle_trigger(trigger)
    assert result.sender_id == "agent-d"
    assert result.sender_name == "小D"
    assert result.proposal is False
    assert any("本轮明确被 @ 的 AI 助手是：小D" in item for item in captured["messages"])
    assert any("请以该助手身份回应" in item for item in captured["messages"])
    print("[OK] current @agent identity is injected ahead of conflicting history")


def test_gm_proposal_for_conflict():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    result = orch.handle_trigger(_trigger("@GM 用户A要移动桌子，但是用户B不同意", "GM"))
    assert result.sender_id == "gm-system"
    assert result.sender_name == "GM"
    assert result.proposal is True
    assert "GM 提案" in result.text
    assert "房主可回复" in result.text
    assert result.action_payload["source_user_id"] == "user-a"
    assert result.action_payload["intent_text"]
    assert result.action_payload["execution"] == "host_single_writer"
    print("[OK] conflict or GM mention produces GM proposal")


def test_gm_summary_does_not_create_proposal():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    trigger = _trigger("@GM 整理一下大家的想法", "GM")
    trigger["agent_id"] = "gm"
    result = orch.handle_trigger(trigger)
    assert result.sender_id == "gm-system"
    assert result.sender_name == "GM"
    assert result.proposal is False
    assert "GM 总结" in result.text
    assert "GM 提案" not in result.text
    print("[OK] @GM summary stays on GM control path without proposal")


def test_role_agent_not_hijacked_by_prior_agent_or_gm_messages():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    trigger = _trigger("@学者 给我介绍一下agent", "学者")
    trigger["agent_id"] = "agent-scholar"
    trigger["history"] = [
        {
            "message_id": "m0",
            "from": "山贼",
            "sender_type": "agent",
            "message_kind": "agent_reply",
            "text": "能看懂，直接生成也行。",
        },
        {
            "message_id": "m1",
            "from": "GM",
            "sender_type": "gm",
            "message_kind": "gm_proposal",
            "text": "【GM 提案 gm-1】待处理意图：内部摘要",
        },
        {
            "message_id": "m2",
            "from": "用户A",
            "sender_type": "user",
            "message_kind": "chat",
            "text": "@学者 给我介绍一下agent",
        },
    ]
    result = orch.handle_trigger(trigger)
    assert result.proposal is False
    assert result.sender_id == "agent-scholar"
    assert result.sender_name == "学者"
    print("[OK] prior agent/GM messages do not hijack a normal @agent reply")


def test_role_agent_theme_discussion_not_hijacked_by_gm():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    trigger = _trigger("@商人 围绕暗黑集市主题讨论一下吧，其他人都可以提出想法", "商人")
    trigger["agent_id"] = "merchant"
    trigger["sender_id"] = "host-a"
    trigger["sender_name"] = "房主"
    trigger["history"] = [
        {"message_id": "m0", "from": "房主", "sender_id": "host-a", "text": "@长者 介绍一下各位"},
        {"message_id": "m1", "from": "用户", "sender_id": "user-b", "text": "@房主 用商人"},
        {"message_id": "m2", "from": "房主", "sender_id": "host-a", "text": trigger["text"]},
    ]
    result = orch.handle_trigger(trigger)
    assert result.proposal is False
    assert result.sender_id == "merchant"
    assert result.sender_name == "商人"
    assert "GM 提案" not in result.text
    print("[OK] @Agent theme discussion stays on role agent path")


def test_role_agent_advice_request_not_hijacked_by_gm():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    result = orch.handle_trigger(_trigger("@商人 你有什么建议呢", "商人"))
    assert result.proposal is False
    assert result.sender_name == "商人"
    print("[OK] @Agent advice request does not create GM proposal")


def test_agent_plan_reference_resolves_before_gm_proposal():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    trigger = _trigger("@商人 就按照你的方案来执行吧", "商人")
    trigger["agent_id"] = "merchant"
    trigger["history"] = [
        {
            "message_id": "m0",
            "from": "房主",
            "sender_id": "host-a",
            "sender_type": "user",
            "message_kind": "chat",
            "text": "@商人 给我一个暗黑集市方案",
        },
        {
            "message_id": "m1",
            "from": "商人",
            "sender_id": "merchant",
            "sender_type": "agent",
            "message_kind": "agent_reply",
            "text": "暗黑集市方案：入口留出动线，中央主摊位，两侧货架，黑铁灯笼，贵重交易区靠内侧。",
        },
        {
            "message_id": "m2",
            "from": "房主",
            "sender_id": "host-a",
            "sender_type": "user",
            "message_kind": "chat",
            "text": trigger["text"],
        },
    ]
    result = orch.handle_trigger(trigger)
    assert result.proposal is True
    assert result.sender_name == "GM"
    assert result.action_payload["action_type"] == "start_generation"
    assert result.action_payload["source_agent_id"] == "merchant"
    assert "暗黑集市方案" in result.action_payload["resolved_intent_text"]
    assert "暗黑集市方案" in result.text
    assert "就按照你的方案来执行吧" not in result.action_payload["resolved_intent_text"]
    print("[OK] @Agent plan reference is resolved before GM proposal")


def test_agent_plan_reference_does_not_cross_agents():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    trigger = _trigger("@长者 就按照你的方案来执行吧", "长者")
    trigger["agent_id"] = "elder"
    trigger["history"] = [
        {
            "message_id": "m1",
            "from": "商人",
            "sender_id": "merchant",
            "sender_type": "agent",
            "message_kind": "agent_reply",
            "text": "暗黑集市方案：中央主摊位，两侧货架，黑铁灯笼。",
        },
        {
            "message_id": "m2",
            "from": "房主",
            "sender_id": "host-a",
            "sender_type": "user",
            "message_kind": "chat",
            "text": trigger["text"],
        },
    ]
    result = orch.handle_trigger(trigger)
    assert result.proposal is False
    assert "没有找到长者刚才的可执行方案" in result.text
    assert result.action_payload is None
    print("[OK] plan reference only resolves against the currently mentioned agent")


def test_agent_plan_reference_after_stale_marker_is_rejected():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    trigger = _trigger("@商人 换方案，不要刚才那个。就按照你的方案来执行吧", "商人")
    trigger["agent_id"] = "merchant"
    trigger["history"] = [
        {
            "message_id": "m1",
            "from": "商人",
            "sender_id": "merchant",
            "sender_type": "agent",
            "message_kind": "agent_reply",
            "text": "暗黑集市方案：中央主摊位，两侧货架，黑铁灯笼。",
        },
        {
            "message_id": "m2",
            "from": "房主",
            "sender_id": "host-a",
            "sender_type": "user",
            "message_kind": "chat",
            "text": trigger["text"],
        },
    ]
    result = orch.handle_trigger(trigger)
    assert result.proposal is False
    assert "没有找到商人刚才的可执行方案" in result.text
    print("[OK] stale plan marker prevents executing an old plan reference")


def test_gm_pause_and_discussion_controls_do_not_reject_pending_proposal():
    runtime = get_lanchat_scene_runtime()
    runtime.end_compose()
    runtime.consume_notes()
    runtime.set_mode("DISCUSSING")
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    proposal = orch.handle_trigger(_trigger("@GM 删除桌子", "GM"))
    assert proposal.proposal is True
    proposal_id = proposal.action_payload["proposal_id"]

    paused = orch.handle_trigger(_trigger("@GM 暂停", "GM"))
    assert paused.proposal is False
    assert "暂停状态" in paused.text
    assert paused.action_payload is None
    assert runtime.mode() == "PAUSED"

    discussing = orch.handle_trigger(_trigger("@GM 先讨论，不要生成", "GM"))
    assert "讨论模式" in discussing.text
    assert discussing.action_payload is None
    assert runtime.mode() == "DISCUSSING"

    resumed = orch.handle_trigger(_trigger("@GM 继续", "GM"))
    assert "恢复" in resumed.text
    assert runtime.mode() == "EXECUTING"

    confirmed = orch.handle_trigger(_trigger(f"@GM 确认 {proposal_id}", "GM"))
    assert confirmed.action_payload["status"] == "confirmed"
    runtime.end_compose()
    print("[OK] GM control commands do not accidentally reject pending proposals")


def test_single_user_major_action_stays_on_role_agent_path():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    result = orch.handle_trigger(_trigger("删除桌子", "小B"))
    assert result.proposal is False
    assert result.sender_id == "agent-b"
    assert "agent-reply" in result.text
    print("[OK] single-user major action is not swallowed by GM proposal")


def test_host_confirmation_consumes_pending_proposal():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    proposal = orch.handle_trigger(_trigger("@GM 删除桌子", "GM"))
    assert proposal.proposal is True
    proposal_id = proposal.action_payload["proposal_id"]
    confirmed = orch.handle_trigger(_trigger(f"@GM 确认 {proposal_id}", "GM"))
    assert confirmed.proposal is False
    assert "已确认" in confirmed.text
    assert confirmed.action_payload["status"] == "confirmed"
    assert confirmed.action_payload["source_user_id"] == "user-a"
    print("[OK] host confirmation consumes pending GM proposal")


def test_host_confirmation_rejects_wrong_proposal_id():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    proposal = orch.handle_trigger(_trigger("@GM 删除桌子", "GM"))
    assert proposal.proposal is True
    current_id = proposal.action_payload["proposal_id"]

    mismatch = orch.handle_trigger(_trigger("@GM 确认 gm-000000", "GM"))
    assert mismatch.proposal is False
    assert "编号不匹配" in mismatch.text
    assert mismatch.action_payload is None

    confirmed = orch.handle_trigger(_trigger(f"@GM 确认 {current_id}", "GM"))
    assert "已确认" in confirmed.text
    assert confirmed.action_payload["status"] == "confirmed"
    print("[OK] host confirmation validates proposal_id before consuming pending proposal")


def test_host_confirmation_replay_does_not_requeue_action():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    proposal = orch.handle_trigger(_trigger("@GM 删除桌子", "GM"))
    proposal_id = proposal.action_payload["proposal_id"]

    confirmed = orch.handle_trigger(_trigger(f"@GM 确认 {proposal_id}", "GM"))
    assert confirmed.action_payload["status"] == "confirmed"

    replay = orch.handle_trigger(_trigger(f"@GM 确认 {proposal_id}", "GM"))
    assert "已处理" in replay.text
    assert replay.action_payload is None
    print("[OK] repeated proposal confirmation does not requeue confirmed action")


def test_duplicate_trigger_reuses_existing_proposal_id():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    trigger = _trigger("@GM 用户A和用户B对桌子位置有冲突", "GM")
    first = orch.handle_trigger(trigger)
    second = orch.handle_trigger(dict(trigger))
    assert first.proposal is True and second.proposal is True
    assert first.action_payload["proposal_id"] == second.action_payload["proposal_id"]
    print("[OK] duplicate trigger reuses existing proposal instead of creating a second one")


def test_rejected_proposal_cannot_be_confirmed_later():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    proposal = orch.handle_trigger(_trigger("@GM 删除桌子", "GM"))
    proposal_id = proposal.action_payload["proposal_id"]
    rejected = orch.handle_trigger(_trigger(f"@GM 拒绝 {proposal_id}", "GM"))
    assert "已取消" in rejected.text
    assert rejected.action_payload["status"] == "rejected"
    replay = orch.handle_trigger(_trigger(f"@GM 确认 {proposal_id}", "GM"))
    assert "已处理" in replay.text
    assert replay.action_payload is None
    print("[OK] rejected proposal cannot be confirmed later")


def test_host_confirmation_rejects_explicit_non_host_role():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    proposal = orch.handle_trigger(_trigger("@GM 删除桌子", "GM"))
    proposal_id = proposal.action_payload["proposal_id"]
    guest_trigger = _trigger(f"@GM 确认 {proposal_id}", "GM")
    guest_trigger["sender_role"] = "guest"

    rejected = orch.handle_trigger(guest_trigger)
    assert "只有房主" in rejected.text
    assert rejected.action_payload is None

    host_trigger = _trigger(f"@GM 确认 {proposal_id}", "GM")
    host_trigger["sender_role"] = "host"
    confirmed = orch.handle_trigger(host_trigger)
    assert confirmed.action_payload["status"] == "confirmed"
    assert confirmed.action_payload["confirmation_mode"] == "verified_host"
    print("[OK] explicit non-host confirmation is rejected when role metadata exists")


def test_structured_confirmation_uses_correlation_id_and_metadata():
    orch = LanChatAgentOrchestrator(agent_factory=_agent_factory)
    proposal = orch.handle_trigger(_trigger("@GM 用户A和用户B对桌子位置有冲突", "GM"))
    assert proposal.proposal is True
    proposal_id = proposal.action_payload["proposal_id"]

    structured = _trigger("", "GM")
    structured["message_kind"] = "confirmation"
    structured["correlation_id"] = proposal_id
    structured["metadata_json"] = '{"decision":"confirm"}'

    confirmed = orch.handle_trigger(structured)
    assert confirmed.action_payload["status"] == "confirmed"
    assert confirmed.action_payload["confirmation_mode"] == "structured_confirmation"
    assert confirmed.action_payload["proposal_id"] == proposal_id
    print("[OK] structured confirmation consumes proposal by correlation_id")


def test_role_agent_api_error_is_sanitized():
    def broken_agent_factory():
        def _agent(persona, messages):
            raise RuntimeError("Error code: 401 - {'message': 'Invalid Token (request id: abc)'}")

        return _agent

    orch = LanChatAgentOrchestrator(agent_factory=broken_agent_factory)
    result = orch.handle_trigger(_trigger("@商人 你有什么建议", "商人"))
    assert result.proposal is False
    assert "当前模型服务不可用" in result.text
    assert "Invalid Token" not in result.text
    assert "request id" not in result.text
    print("[OK] role agent provider errors are sanitized before chat reply")


def test_worker_uses_orchestrator_and_sends_reply():
    engine = FakeEngine([_trigger()])
    worker = LANChatAgentWorker(
        corona_engine=engine,
        agent_factory=_agent_factory,
        async_agent_execution=False,
    )
    assert worker.process_once() is True
    assert len(engine.replies) == 1
    assert engine.replies[0][0] == "agent-b"
    assert "agent-reply" in engine.replies[0][2]
    assert engine.replies[0][3] == "agent_reply"
    print("[OK] worker polls C++ trigger and replies through C++")


def test_worker_streams_sanitized_progress_reply_before_final():
    def progress_agent_factory():
        def _agent(persona, messages):
            from plugins.AITool.services.agent_progress_context import get_current_progress_sink

            sink = get_current_progress_sink()
            assert callable(sink)
            sink("生成进度  50% [█████░░░░░] 进行中：摆放物件。开始把主要物件放进场景。")
            return "final scene reply"

        return _agent

    engine = FakeEngine([_trigger("生成一个广场场景")])
    worker = LANChatAgentWorker(
        corona_engine=engine,
        agent_factory=progress_agent_factory,
        async_agent_execution=False,
    )
    assert worker.process_once() is True
    assert len(engine.replies) == 2
    assert "生成进度" in engine.replies[0][2]
    assert engine.replies[0][3] == "progress"
    assert "final scene reply" in engine.replies[-1][2]
    assert engine.replies[-1][3] == "agent_reply"
    print("[OK] worker streams progress reply before final compose summary")


def test_worker_async_agent_execution_returns_before_slow_agent_reply():
    def slow_agent_factory():
        def _agent(persona, messages):
            time.sleep(0.05)
            return "slow final reply"

        return _agent

    engine = FakeEngine([_trigger("@小B 生成一个广场")])
    worker = LANChatAgentWorker(
        corona_engine=engine,
        agent_factory=slow_agent_factory,
        async_agent_execution=True,
    )
    started = time.time()
    assert worker.process_once() is True
    assert time.time() - started < 0.04
    deadline = time.time() + 1.0
    while time.time() < deadline and (
        not engine.replies or "slow final reply" not in engine.replies[-1][2]
    ):
        time.sleep(0.01)
    assert engine.replies
    assert "slow final reply" in engine.replies[-1][2]
    print("[OK] async worker returns before slow agent reply and sends later")


def test_worker_async_sends_fast_ack_before_agent_lock_finishes():
    def slow_agent_factory():
        def _agent(persona, messages):
            time.sleep(0.08)
            return "slow compose done"

        return _agent

    engine = FakeEngine([_trigger("@小B 生成一个卧室", "小B")])
    worker = LANChatAgentWorker(
        corona_engine=engine,
        agent_factory=slow_agent_factory,
        async_agent_execution=True,
    )
    assert worker.process_once() is True
    deadline = time.time() + 0.04
    while time.time() < deadline and not engine.replies:
        time.sleep(0.005)
    assert engine.replies
    assert engine.replies[0][3] == "progress"
    assert "已收到" in engine.replies[0][2]
    deadline = time.time() + 1.0
    while time.time() < deadline and "slow compose done" not in engine.replies[-1][2]:
        time.sleep(0.01)
    assert "slow compose done" in engine.replies[-1][2]
    print("[OK] async worker sends fast ack before long compose finishes")


def test_worker_records_busy_scene_message_without_agent_lock():
    runtime = get_lanchat_scene_runtime()
    runtime.end_compose()
    runtime.consume_notes()
    runtime.start_compose("长者", "森林奇幻集市")
    try:
        engine = FakeEngine([_trigger("@小女孩 后面再加两个摊位和灯串", "小女孩")])
        worker = LANChatAgentWorker(
            corona_engine=engine,
            agent_factory=_agent_factory,
            async_agent_execution=False,
        )
        assert worker.process_once() is True
        assert len(engine.replies) == 1
        assert engine.replies[0][1] == "小女孩"
        assert "已记录" in engine.replies[0][2]
        notes = runtime.consume_notes()
        assert notes and notes[0].kind == "generation_delta"
        assert "灯串" in notes[0].text
    finally:
        runtime.end_compose()
        runtime.consume_notes()
    print("[OK] busy scene messages are recorded and replied without entering agent lock")


def test_worker_records_busy_layout_and_edit_notes():
    runtime = get_lanchat_scene_runtime()
    runtime.end_compose()
    runtime.consume_notes()
    runtime.start_compose("长者", "森林奇幻集市")
    try:
        engine = FakeEngine([
            _trigger("@学者 后续不要挡中央活动区", "学者"),
            _trigger("@小女孩 放大摊位", "小女孩"),
        ])
        worker = LANChatAgentWorker(
            corona_engine=engine,
            agent_factory=_agent_factory,
            async_agent_execution=False,
        )
        assert worker.process_once() is True
        assert worker.process_once() is True
        assert len(engine.replies) == 2
        notes = runtime.consume_notes()
        assert [note.kind for note in notes] == ["layout_constraint", "edit_existing"]
        assert "中央活动区" in notes[0].text
        assert "放大" in notes[1].text
    finally:
        runtime.end_compose()
        runtime.consume_notes()
    print("[OK] busy path records layout constraints and edit requests for next-batch handling")


def test_planning_confirmation_gate_roundtrip():
    runtime = get_lanchat_scene_runtime()
    runtime.end_compose()
    runtime.consume_notes()
    action, reply = runtime.handle_planning_gate("长者", "我有一个计划，建立一个森林奇幻集市")
    assert action == "reply"
    assert "确认开始" in str(reply)
    assert "建议先做" in str(reply)
    action, reply = runtime.handle_planning_gate("长者", "补充：要有灯串和木牌")
    assert action == "reply"
    assert "我已更新方案" in str(reply)
    action, compose_text = runtime.handle_planning_gate("长者", "确认开始，先生成前三个")
    assert action == "compose"
    assert "森林奇幻集市" in str(compose_text)
    assert "灯串" in str(compose_text) or "木牌" in str(compose_text)
    print("[OK] planning confirmation gate returns proposal then compose text")


def test_worker_async_agent_calls_are_serialized_per_worker():
    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_agent_factory():
        def _agent(persona, messages):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return "serialized async reply"

        return _agent

    engine = FakeEngine([
        _trigger("@小B 第一条", "小B"),
        _trigger("@小B 第二条", "小B"),
    ])
    worker = LANChatAgentWorker(
        corona_engine=engine,
        agent_factory=slow_agent_factory,
        async_agent_execution=True,
    )
    assert worker.process_once() is True
    assert worker.process_once() is True
    deadline = time.time() + 1.0
    while time.time() < deadline and len(engine.replies) < 2:
        time.sleep(0.01)
    assert len(engine.replies) == 2
    assert max_active == 1
    print("[OK] async worker serializes agent/orchestrator calls per worker")


def test_worker_broadcasts_confirmed_gm_action():
    executor = FakeHostActionExecutor()
    engine = FakeEngine([
        _trigger("@GM 删除桌子", "GM"),
        _trigger("确认", "GM"),
    ])
    worker = LANChatAgentWorker(
        corona_engine=engine,
        agent_factory=_agent_factory,
        host_action_executor=executor,
        async_agent_execution=False,
    )
    assert worker.process_once() is True
    assert worker.process_once() is True
    assert engine.system_messages and engine.system_messages[0][3] == "gm_proposal"
    assert len(engine.replies) == 1
    assert engine.replies[0][3] == "agent_reply"
    assert engine.intents, "confirmed GM action should be visible to C++ intent channel"
    assert engine.intents[-1][0] == "user-a"
    statuses = [row[3] for row in engine.intents]
    assert "confirmed_gm_action" in statuses
    assert executor.payloads, "confirmed GM action should enter host single-writer queue"
    assert executor.payloads[-1]["source_user_id"] == "user-a"
    print("[OK] worker broadcasts confirmed GM action payload and queues host execution")


def test_worker_does_not_execute_discussion_only_confirmed_payload():
    executor = FakeHostActionExecutor()
    engine = FakeEngine([])
    worker = LANChatAgentWorker(
        corona_engine=engine,
        agent_factory=_agent_factory,
        host_action_executor=executor,
        async_agent_execution=False,
    )
    worker._broadcast_confirmed_action({  # noqa: SLF001 - direct unit coverage for dispatch gate
        "proposal_id": "gm-discuss",
        "status": "confirmed",
        "action_type": "discussion_only",
        "source_user_id": "user-a",
        "intent_text": "围绕暗黑集市主题讨论",
    })
    assert not executor.payloads
    assert not engine.intents
    print("[OK] discussion-only confirmed payload does not enter host executor")


def test_host_action_executor_runs_under_gate_and_reports_result():
    engine = FakeEngine([])
    gate = FakeGate()

    def agent_factory():
        def _agent(persona, messages):
            assert "host single-writer" in persona
            assert any("source_user_id=user-a" in item for item in messages)
            assert messages[-1] == "用户确认意图：添加篝火"
            assert "请在 host 机器上" not in messages[-1]
            return "scene delta applied"

        return _agent

    executor = LanChatHostActionExecutor(
        corona_engine=engine,
        agent_factory=agent_factory,
        engine_gate=gate,
    )
    result = executor.enqueue_and_process({
        "proposal_id": "gm-test",
        "status": "confirmed",
        "source_user_id": "user-a",
        "intent_text": "添加篝火",
    })
    assert gate.calls == 1
    assert result is not None and result.ok is True
    assert result.event_type == "SceneDelta"
    assert result.payload["source_user_id"] == "user-a"
    assert "peer actor sync" not in result.message
    assert [item[3] for item in engine.intents] == [
        "queued_host_action",
        "executing_host_action",
        "host_action_executed",
    ]
    assert engine.system_messages
    assert "scene delta applied" in engine.system_messages[-1][2]
    assert "host_single_writer" not in engine.system_messages[-1][2]
    assert "EngineWriteGate" not in engine.system_messages[-1][2]
    assert "peer actor sync" not in engine.system_messages[-1][2]
    assert engine.system_messages[-1][3] == "action_status"
    print("[OK] host action executor runs under EngineWriteGate and reports SceneDelta")


def test_host_action_executor_does_not_report_executed_for_empty_or_failed_result():
    engine = FakeEngine([])

    def empty_agent_factory():
        def _agent(persona, messages):
            return ""

        return _agent

    empty_executor = LanChatHostActionExecutor(
        corona_engine=engine,
        agent_factory=empty_agent_factory,
        engine_gate=None,
    )
    empty_result = empty_executor.enqueue_and_process({
        "proposal_id": "gm-empty",
        "status": "confirmed",
        "source_user_id": "user-a",
        "intent_text": "空执行",
    })
    assert empty_result is not None and empty_result.ok is False
    assert empty_result.event_type == "CommandRejected"

    def failed_agent_factory():
        def _agent(persona, messages):
            return "无法安全执行该操作"

        return _agent

    failed_executor = LanChatHostActionExecutor(
        corona_engine=engine,
        agent_factory=failed_agent_factory,
        engine_gate=None,
    )
    failed_result = failed_executor.enqueue_and_process({
        "proposal_id": "gm-failed",
        "status": "confirmed",
        "source_user_id": "user-a",
        "intent_text": "失败执行",
    })
    assert failed_result is not None and failed_result.ok is False
    assert failed_result.event_type == "CommandRejected"
    assert [item[3] for item in engine.intents].count("host_action_failed") == 2
    print("[OK] host action executor does not report complete execution for empty/failure replies")


def test_host_action_executor_reports_accepted_no_delta_when_no_executor_agent():
    engine = FakeEngine([])
    executor = LanChatHostActionExecutor(
        corona_engine=engine,
        agent_factory=None,
        engine_gate=None,
    )
    result = executor.enqueue_and_process({
        "proposal_id": "gm-no-agent",
        "status": "confirmed",
        "source_user_id": "user-a",
        "intent_text": "无执行器",
    })
    assert result is not None and result.ok is True
    assert result.event_type == "AcceptedNoDelta"
    assert "未修改场景" in result.message
    assert "typed actor delta" not in result.message
    assert [item[3] for item in engine.intents][-1] == "accepted_no_delta"
    print("[OK] host action executor separates accepted_no_delta from complete actor execution")


def test_host_action_executor_sanitizes_agent_api_error():
    engine = FakeEngine([])

    def broken_agent_factory():
        def _agent(persona, messages):
            raise RuntimeError("Error code: 401 - {'message': 'Invalid Token (request id: abc)'}")

        return _agent

    executor = LanChatHostActionExecutor(
        corona_engine=engine,
        agent_factory=broken_agent_factory,
        engine_gate=None,
    )
    result = executor.enqueue_and_process({
        "proposal_id": "gm-token",
        "status": "confirmed",
        "source_user_id": "user-a",
        "intent_text": "添加篝火",
    })
    assert result is not None and result.ok is False
    assert "Invalid Token" not in result.message
    assert "request id" not in result.message
    assert "当前模型服务不可用" in engine.system_messages[-1][2]
    assert "Invalid Token" not in engine.system_messages[-1][2]
    print("[OK] host executor provider errors are sanitized before chat status")


def test_host_action_executor_serializes_parallel_confirmed_actions():
    engine = FakeEngine([])
    active = 0
    max_active = 0
    lock = threading.Lock()

    def agent_factory():
        def _agent(persona, messages):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with lock:
                active -= 1
            return "parallel action done"

        return _agent

    executor = LanChatHostActionExecutor(
        corona_engine=engine,
        agent_factory=agent_factory,
        engine_gate=None,
    )
    payloads = [
        {
            "proposal_id": "gm-a",
            "status": "confirmed",
            "source_user_id": "user-a",
            "intent_text": "action A",
        },
        {
            "proposal_id": "gm-b",
            "status": "confirmed",
            "source_user_id": "user-b",
            "intent_text": "action B",
        },
    ]
    threads = [
        threading.Thread(target=executor.enqueue_and_process, args=(payload,))
        for payload in payloads
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1.0)

    assert max_active == 1
    statuses = [item[3] for item in engine.intents]
    assert statuses.count("executing_host_action") == 2
    assert statuses.count("host_action_executed") == 2
    print("[OK] host action executor serializes parallel confirmed actions")


if __name__ == "__main__":
    test_regular_role_agent_reply()
    test_current_mentioned_agent_identity_overrides_history_mentions()
    test_gm_proposal_for_conflict()
    test_gm_summary_does_not_create_proposal()
    test_role_agent_not_hijacked_by_prior_agent_or_gm_messages()
    test_role_agent_theme_discussion_not_hijacked_by_gm()
    test_role_agent_advice_request_not_hijacked_by_gm()
    test_agent_plan_reference_resolves_before_gm_proposal()
    test_agent_plan_reference_does_not_cross_agents()
    test_agent_plan_reference_after_stale_marker_is_rejected()
    test_gm_pause_and_discussion_controls_do_not_reject_pending_proposal()
    test_single_user_major_action_stays_on_role_agent_path()
    test_host_confirmation_consumes_pending_proposal()
    test_host_confirmation_rejects_wrong_proposal_id()
    test_host_confirmation_replay_does_not_requeue_action()
    test_duplicate_trigger_reuses_existing_proposal_id()
    test_rejected_proposal_cannot_be_confirmed_later()
    test_host_confirmation_rejects_explicit_non_host_role()
    test_structured_confirmation_uses_correlation_id_and_metadata()
    test_role_agent_api_error_is_sanitized()
    test_worker_uses_orchestrator_and_sends_reply()
    test_worker_streams_sanitized_progress_reply_before_final()
    test_worker_async_agent_execution_returns_before_slow_agent_reply()
    test_worker_async_sends_fast_ack_before_agent_lock_finishes()
    test_worker_records_busy_scene_message_without_agent_lock()
    test_worker_records_busy_layout_and_edit_notes()
    test_planning_confirmation_gate_roundtrip()
    test_worker_async_agent_calls_are_serialized_per_worker()
    test_worker_broadcasts_confirmed_gm_action()
    test_worker_does_not_execute_discussion_only_confirmed_payload()
    test_host_action_executor_runs_under_gate_and_reports_result()
    test_host_action_executor_does_not_report_executed_for_empty_or_failed_result()
    test_host_action_executor_reports_accepted_no_delta_when_no_executor_agent()
    test_host_action_executor_sanitizes_agent_api_error()
    test_host_action_executor_serializes_parallel_confirmed_actions()
    print("\n=== LANChat agent orchestrator ALL PASS ===")
