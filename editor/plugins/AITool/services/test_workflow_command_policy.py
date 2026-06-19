from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
EDITOR_ROOT = os.path.join(REPO_ROOT, "editor")
AI_TOOL_ROOT = os.path.join(EDITOR_ROOT, "plugins", "AITool")
for path in (EDITOR_ROOT, AI_TOOL_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from plugins.AITool.services.workflow_command_policy import (  # noqa: E402
    DEPRECATED_WORKFLOW_COMMAND_MESSAGE,
    is_deprecated_user_workflow_command,
    should_register_workflow_command,
)


def test_deprecated_workflow_commands_are_hidden_by_default() -> None:
    old = os.environ.pop("CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS", None)
    try:
        assert not should_register_workflow_command("/scene_agent")
        assert not should_register_workflow_command("/full_pipeline")
        assert not should_register_workflow_command("/parallel_generate_v2")
    finally:
        if old is not None:
            os.environ["CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS"] = old


def test_internal_debug_commands_require_explicit_env() -> None:
    old = os.environ.pop("CORONA_ENABLE_INTERNAL_WORKFLOW_COMMANDS", None)
    try:
        assert not should_register_workflow_command("/model_retrieval")
        os.environ["CORONA_ENABLE_INTERNAL_WORKFLOW_COMMANDS"] = "1"
        assert should_register_workflow_command("/model_retrieval")
    finally:
        os.environ.pop("CORONA_ENABLE_INTERNAL_WORKFLOW_COMMANDS", None)
        if old is not None:
            os.environ["CORONA_ENABLE_INTERNAL_WORKFLOW_COMMANDS"] = old


def test_legacy_env_can_reenable_old_commands_for_debug() -> None:
    old = os.environ.get("CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS")
    os.environ["CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS"] = "1"
    try:
        assert should_register_workflow_command("/scene_composition")
    finally:
        if old is None:
            os.environ.pop("CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS", None)
        else:
            os.environ["CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS"] = old


def test_deprecated_command_message_points_to_unified_chain() -> None:
    assert is_deprecated_user_workflow_command("/sc_v2")
    assert "统一" in DEPRECATED_WORKFLOW_COMMAND_MESSAGE
    assert "场景生成链路" in DEPRECATED_WORKFLOW_COMMAND_MESSAGE


if __name__ == "__main__":
    test_deprecated_workflow_commands_are_hidden_by_default()
    test_internal_debug_commands_require_explicit_env()
    test_legacy_env_can_reenable_old_commands_for_debug()
    test_deprecated_command_message_points_to_unified_chain()
    print("[OK] Workflow command policy tests passed")
