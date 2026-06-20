"""Focused tests for RoleAgent template injection."""
from __future__ import annotations

import os
import sys
import math

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from cai_extensions.agent.role_registry import (  # noqa: E402
    get_role_registry,
    inject_persona_voice,
    resolve_role_template,
)
from cai_extensions.agent import agent_adapter  # noqa: E402
from cai_extensions.agent.agent_adapter import MasterAgent  # noqa: E402


class FakeRotActor:
    def __init__(self, name: str = "chair"):
        self.name = name
        self._rotation = [0.0, 0.0, 0.0]
        self._position = [0.0, 0.0, 0.0]
        self._scale = [1.0, 1.0, 1.0]
        self._color = None

    def get_rotation(self):
        return list(self._rotation)

    def set_rotation(self, value):
        self._rotation = list(value)

    def get_position(self):
        return list(self._position)

    def get_scale(self):
        return list(self._scale)

    def set_scale(self, value):
        self._scale = list(value)

    def set_color(self, value):
        self._color = list(value)


def test_builtin_role_has_structured_biases():
    tpl = resolve_role_template("小女孩")
    assert tpl is not None
    assert tpl.name == "小女孩"
    assert tpl.object_bias
    assert tpl.layout_bias
    assert tpl.forbidden_bias
    context = tpl.to_compose_context()
    assert "RoleAgent: 小女孩" in context
    assert "object_bias_reference_only" in context
    assert "do not add these as new objects" in context


def test_role_voice_injection_keeps_persona_visible():
    system = inject_persona_voice("base", "山贼")
    assert "【你的角色】山贼" in system
    assert "【偏好物件】" in system
    assert "【布局偏好】" in system
    assert "【视野边界】" in system
    assert "不要凭角色口吻臆造执行结果" in system
    assert "始终以该角色的口吻回复" in system


def test_custom_role_is_supported_without_overwriting_builtin():
    reg = get_role_registry()
    tpl = reg.register_custom("elder", "赛博商人", "霓虹、市井、会砍价", "偏好霓虹摊位")
    assert tpl.key == "elder_custom"
    resolved = resolve_role_template("elder_custom")
    assert resolved is tpl
    assert resolve_role_template("长者").name == "长者"


def test_master_agent_can_build_role_compose_context():
    ctx = MasterAgent()._role_compose_context("商人")
    assert "RoleAgent: 商人" in ctx
    assert "layout_bias" in ctx
    assert "SceneState, AABB, VLM and user intent have priority" in ctx


def test_structured_scene_intent_keeps_agent_performance_request_as_chat():
    old_structured = getattr(agent_adapter, "_llm_classify_scene_intent", None)
    old_legacy = agent_adapter._llm_classify_intent

    def structured(_text, timeout=20.0):
        return {
            "intent": "compose",
            "scene_write_intent": False,
            "target": "agent_self",
            "confidence": 0.95,
            "reason": "User asks the addressed agent to perform, not to write the 3D scene.",
        }

    agent_adapter._llm_classify_scene_intent = structured
    agent_adapter._llm_classify_intent = lambda _text, timeout=20.0: "compose"
    try:
        intent = agent_adapter.classify_intent("@小女孩 我想看你在大草原上跳舞")
    finally:
        if old_structured is None:
            delattr(agent_adapter, "_llm_classify_scene_intent")
        else:
            agent_adapter._llm_classify_scene_intent = old_structured
        agent_adapter._llm_classify_intent = old_legacy

    assert intent == "chat"


def test_structured_scene_intent_allows_explicit_scene_write_request():
    old_structured = getattr(agent_adapter, "_llm_classify_scene_intent", None)
    old_legacy = agent_adapter._llm_classify_intent

    def structured(_text, timeout=20.0):
        return {
            "intent": "compose",
            "scene_write_intent": True,
            "target": "scene_world",
            "confidence": 0.9,
            "reason": "User asks to create a 3D scene.",
        }

    agent_adapter._llm_classify_scene_intent = structured
    agent_adapter._llm_classify_intent = lambda _text, timeout=20.0: "chat"
    try:
        intent = agent_adapter.classify_intent("生成一个小女孩在大草原跳舞的场景")
    finally:
        if old_structured is None:
            delattr(agent_adapter, "_llm_classify_scene_intent")
        else:
            agent_adapter._llm_classify_scene_intent = old_structured
        agent_adapter._llm_classify_intent = old_legacy

    assert intent == "compose"


def test_fast_rotation_converts_degrees_to_radians():
    agent = MasterAgent()
    actor = FakeRotActor()
    reply = agent._try_fast_transform_edit("旋转chair90度", [actor])
    assert reply and "弧度" in reply
    assert math.isclose(actor.get_rotation()[1], math.pi / 2, abs_tol=0.0015)

    reply = agent._try_fast_transform_edit("逆时针旋转chair45度", [actor])
    assert reply and "弧度" in reply
    assert math.isclose(actor.get_rotation()[1], math.pi / 4, abs_tol=0.0015)


def test_boundary_alias_prefers_system_boundary_over_entrance_actor():
    agent = MasterAgent()
    boundary = FakeRotActor("__terrain_boundary")
    arch = FakeRotActor("入口拱门")

    picked = agent._pick_edit_actor("这个栅栏有点奇怪，换成低矮木栏/藤蔓围栏", [arch, boundary])

    assert picked is boundary


def test_boundary_fast_edit_uses_low_risk_boundary_adjustment():
    agent = MasterAgent()
    boundary = FakeRotActor("__terrain_boundary")
    arch = FakeRotActor("入口拱门")

    reply = agent._try_fast_transform_edit("换成更幻想集市风的低矮木栏/藤蔓围栏", [arch, boundary])

    assert reply and "__terrain_boundary" in reply
    assert boundary.get_scale()[1] <= 0.55
    assert arch.get_scale() == [1.0, 1.0, 1.0]


if __name__ == "__main__":
    test_builtin_role_has_structured_biases()
    test_role_voice_injection_keeps_persona_visible()
    test_custom_role_is_supported_without_overwriting_builtin()
    test_master_agent_can_build_role_compose_context()
    test_structured_scene_intent_keeps_agent_performance_request_as_chat()
    test_structured_scene_intent_allows_explicit_scene_write_request()
    test_fast_rotation_converts_degrees_to_radians()
    test_boundary_alias_prefers_system_boundary_over_entrance_actor()
    test_boundary_fast_edit_uses_low_risk_boundary_adjustment()
    print("\n=== Role registry ALL PASS ===")
