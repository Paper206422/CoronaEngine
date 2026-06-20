from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
EDITOR_ROOT = os.path.join(REPO_ROOT, "editor")
AI_TOOL_ROOT = os.path.join(EDITOR_ROOT, "plugins", "AITool")
for path in (EDITOR_ROOT, AI_TOOL_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)

from plugins.AITool.cai_extensions.agent.agent_adapter import MasterAgent  # noqa: E402
from plugins.AITool.services.agent_progress_context import agent_progress_sink  # noqa: E402
from plugins.AITool.services.workflow_command_policy import DEPRECATED_WORKFLOW_COMMAND_MESSAGE  # noqa: E402


def test_lanchat_progress_context_blocks_direct_roleagent_compose() -> None:
    agent = MasterAgent(fallback_chat=lambda _system, _messages: "fallback")
    progress: list[str] = []
    with agent_progress_sink(progress.append):
        reply = agent._handle_scene(  # noqa: SLF001
            "帮我设计一个可爱的卧室",
            "小女孩",
            ["房主: @小女孩 帮我设计一个可爱的卧室"],
            force_compose=True,
        )
    assert "通过生成队列执行" in reply


def test_deprecated_workflow_command_is_not_executed_by_role_agent() -> None:
    agent = MasterAgent(fallback_chat=lambda _system, _messages: "fallback")
    reply = agent("小女孩", ["房主: @小女孩 /scene_composition 做一个卧室"])
    assert reply == DEPRECATED_WORKFLOW_COMMAND_MESSAGE


if __name__ == "__main__":
    test_lanchat_progress_context_blocks_direct_roleagent_compose()
    test_deprecated_workflow_command_is_not_executed_by_role_agent()
    print("[OK] LANChat compose requests do not enter direct RoleAgent compose")
    print("\n=== LANChat compose trigger classifier ALL PASS ===")
