from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
EDITOR_ROOT = os.path.join(REPO_ROOT, "editor")
AI_TOOL_ROOT = os.path.join(EDITOR_ROOT, "plugins", "AITool")
for path in (EDITOR_ROOT, AI_TOOL_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from plugins.AITool.services.intent_understanding import IntentUnderstandingService  # noqa: E402
from plugins.AITool.services.lanchat_scene_runtime import LanChatSceneRuntime  # noqa: E402


def test_status_query_overrides_bad_llm_generation_start() -> None:
    service = IntentUnderstandingService(lambda _text: {
        "intent": "generation_start",
        "confidence": 0.99,
        "reason": "bad llm",
    })
    decision = service.classify("@GM 现在生成到哪里了")
    assert decision.intent == "status_query"


def test_generation_start_requires_explicit_confirmation_language() -> None:
    service = IntentUnderstandingService(lambda _text: {
        "intent": "generation_start",
        "confidence": 0.96,
        "reason": "over eager llm",
    })
    decision = service.classify("@商人 帮我写一个可爱卧室的生成方案")
    assert decision.intent == "plan_drafting"


def test_active_generation_add_is_pending_intervention() -> None:
    service = IntentUnderstandingService()
    decision = service.classify("后面再加入一个天使雕像", allow_llm=False, generation_active=True)
    assert decision.intent == "intervention_add"
    assert service.scene_note_kind("后面再加入一个天使雕像") == "generation_delta"


def test_structured_route_exposes_agent_self_and_scene_actions() -> None:
    service = IntentUnderstandingService()
    identity = service.classify("@小女孩 你是谁", allow_llm=False)
    performance = service.classify("@小女孩 我想看你在大草原上跳舞", allow_llm=False)
    plan = service.classify("@小女孩 帮我设计一个可爱的卧室", allow_llm=False)
    supplement = service.classify("补充要求，减少方案中的细碎物体", allow_llm=False)
    start = service.classify("确认开始", allow_llm=False)
    edit = service.classify("把床放大一点", allow_llm=False)
    gm = service.classify("@GM 整理一下大家的想法", allow_llm=False)

    assert identity.as_dict()["route"] == "agent_self"
    assert performance.as_dict()["route"] == "agent_self"
    assert plan.as_dict()["route"] == "plan_drafting"
    assert supplement.as_dict()["route"] == "plan_revision"
    assert start.as_dict()["route"] == "generation_start"
    assert edit.as_dict()["route"] == "edit_existing"
    assert edit.as_dict()["state_hint"] == "completed_scene"
    assert gm.as_dict()["route"] == "gm_control"


def test_planning_disclosure_splits_models_from_scene_substrate() -> None:
    runtime = LanChatSceneRuntime()
    action, reply = runtime.handle_planning_gate(
        "小女孩",
        "我想做一个草原天空森林里的可爱卧室，有床和台灯",
    )
    assert action == "reply"
    assert reply is not None
    assert "提炼结果" in reply
    assert "准备生成模型" in reply
    assert "床" in reply
    assert "台灯" in reply
    assert "环境/地形" in reply
    assert "草原" in reply
    assert "天空" in reply
    assert "森林" in reply


if __name__ == "__main__":
    test_status_query_overrides_bad_llm_generation_start()
    test_generation_start_requires_explicit_confirmation_language()
    test_active_generation_add_is_pending_intervention()
    test_structured_route_exposes_agent_self_and_scene_actions()
    test_planning_disclosure_splits_models_from_scene_substrate()
    print("[OK] Intent understanding service tests passed")
