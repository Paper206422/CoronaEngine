"""Run the non-native verification suite for docs/终极计划.md.

This runner intentionally avoids C++/Ninja/CEF/F5/native build steps. It is the
repeatable gate for the Python, Node, protocol, and static checks that can be
validated in this workstream.
"""

from __future__ import annotations

import subprocess
import sys
import os
import tokenize
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
PYCACHE_PREFIX = REPO_ROOT / ".tmp" / "ultimate_plan_pycache"


PYTHON_TESTS = [
    "editor/plugins/AITool/services/test_seed_plan.py",
    "editor/plugins/AITool/services/test_interaction_coordinator.py",
    "editor/plugins/AITool/services/test_memory_scope.py",
    "editor/plugins/AITool/services/test_legacy_memory_scope.py",
    "editor/plugins/AITool/services/test_generation_scheduler.py",
    "editor/plugins/AITool/services/test_disclosure_policy.py",
    "editor/plugins/AITool/services/test_intent_understanding.py",
    "editor/plugins/AITool/services/test_workflow_command_policy.py",
    "editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py",
    "editor/plugins/AITool/services/test_lanchat_compose_trigger_classifier.py",
    "editor/plugins/AITool/services/test_native_lanchat_bridge_static.py",
    "editor/plugins/AITool/cai_extensions/agent/test_scene_composer_element_routing.py",
    "editor/plugins/AITool/cai_extensions/agent/test_scene_element_classifier.py",
    "editor/plugins/AITool/cai_extensions/agent/test_scene_session.py",
    "editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py",
    "editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/test_resource_progress.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/test_search_tool_precheck.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/test_retrieve_search_circuit.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/test_dispatch_image_retry.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/test_generate_batching.py",
    "editor/plugins/AITool/cai_extensions/flows/scene_composition_workflow/test_incremental_import.py",
    "editor/plugins/LANChat/server/test_gm_arbiter.py",
    "docs/probes/test_v3_f5_log_check.py",
    "docs/probes/test_v3_f5_quick_gate.py",
]

NODE_TESTS = [
    "editor/Frontend/src/stores/lanchatDisclosure.test.mjs",
    "editor/Frontend/scripts/test-lanchat-roster.mjs",
    "editor/Frontend/scripts/test-network-ai-framework-sync.mjs",
]

PY_COMPILE_TARGETS = [
    "editor/plugins/AITool/services/seed_plan.py",
    "editor/plugins/AITool/services/interaction_coordinator.py",
    "editor/plugins/AITool/services/generation_scheduler.py",
    "editor/plugins/AITool/services/generation_composer_adapter.py",
    "editor/plugins/AITool/services/generation_provider_adapter.py",
    "editor/plugins/AITool/services/disclosure_policy.py",
    "editor/plugins/AITool/services/memory_scope.py",
    "editor/plugins/AITool/services/lanchat_agent_orchestrator.py",
    "editor/plugins/AITool/services/intent_understanding.py",
    "editor/plugins/AITool/services/workflow_command_policy.py",
    "editor/plugins/AITool/cai_extensions/agent/memory.py",
    "editor/plugins/AITool/cai_extensions/agent/coordinator.py",
    "editor/plugins/AITool/cai_extensions/agent/agent_adapter.py",
    "editor/plugins/AITool/cai_extensions/agent/scene_element_classifier.py",
    "editor/plugins/AITool/cai_extensions/agent/test_scene_composer_element_routing.py",
    "editor/plugins/AITool/cai_extensions/agent/test_scene_element_classifier.py",
    "editor/plugins/AITool/services/lanchat_agent_worker.py",
    "editor/plugins/AITool/services/test_lanchat_compose_trigger_classifier.py",
    "editor/plugins/AITool/services/test_native_lanchat_bridge_static.py",
    "editor/plugins/AITool/cai_extensions/agent/scene_session.py",
    "editor/plugins/AITool/cai_extensions/agent/scene_composer.py",
    "editor/plugins/AITool/cai_extensions/agent/scene_composer_progressive.py",
    "editor/plugins/AITool/cai_extensions/agent/vlm_review_loop.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/dispatch.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/retrieve.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/generate.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/formatters.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/helpers.py",
    "editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/progress.py",
    "editor/plugins/LANChat/server/gm_arbiter.py",
    "docs/probes/v3_f5_log_check.py",
    "docs/probes/v3_f5_quick_gate.py",
]


def _run(label: str, command: list[str]) -> bool:
    print(f"[RUN] {label}")
    env = os.environ.copy()
    if command and Path(command[0]).name.lower().startswith("python"):
        PYCACHE_PREFIX.mkdir(parents=True, exist_ok=True)
        env["PYTHONPYCACHEPREFIX"] = str(PYCACHE_PREFIX)
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env)
    if completed.returncode == 0:
        print(f"[OK]  {label}")
        return True
    print(f"[FAIL] {label} (exit={completed.returncode})")
    return False


def _syntax_check(paths: list[str]) -> bool:
    print("[RUN] syntax compile core ultimate-plan modules")
    for path in paths:
        source_path = REPO_ROOT / path
        try:
            with tokenize.open(source_path) as handle:
                source = handle.read()
            compile(source, str(source_path), "exec")
        except Exception as exc:
            print(f"[FAIL] syntax compile core ultimate-plan modules: {path}: {exc}")
            return False
    print("[OK]  syntax compile core ultimate-plan modules")
    return True


def main() -> int:
    checks: list[tuple[str, list[str]]] = []

    for path in PYTHON_TESTS:
        checks.append((path, [sys.executable, path]))

    for path in NODE_TESTS:
        checks.append((path, ["node", path]))

    failed = 0
    for label, command in checks:
        if not _run(label, command):
            failed += 1

    if not _syntax_check(PY_COMPILE_TARGETS):
        failed += 1

    if failed:
        print(f"[SUMMARY] {failed} non-native check(s) failed.")
        return 1

    print("[SUMMARY] All non-native ultimate-plan checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
