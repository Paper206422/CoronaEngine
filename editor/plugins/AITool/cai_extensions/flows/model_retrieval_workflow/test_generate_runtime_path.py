from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

_PKG = "cai_extensions.flows.model_retrieval_workflow"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [os.path.dirname(__file__)]  # type: ignore[attr-defined]
    sys.modules[_PKG] = pkg


def _install_generate_stubs(calls: dict) -> None:
    sys.modules.setdefault("Quasar", types.ModuleType("Quasar"))
    sys.modules.setdefault("Quasar.ai_workflow", types.ModuleType("Quasar.ai_workflow"))
    state_mod = types.ModuleType("Quasar.ai_workflow.state")
    state_mod.ModelRetrievalWorkflowState = dict
    streaming_mod = types.ModuleType("Quasar.ai_workflow.streaming")
    streaming_mod.stream_output_node = lambda *_args, **_kwargs: (lambda fn: fn)
    sys.modules["Quasar.ai_workflow.state"] = state_mod
    sys.modules["Quasar.ai_workflow.streaming"] = streaming_mod

    sys.modules.setdefault("Quasar.ai_tools", types.ModuleType("Quasar.ai_tools"))
    context_mod = types.ModuleType("Quasar.ai_tools.context")
    context_mod.set_current_session = lambda _session_id: "token"
    context_mod.reset_current_session = lambda _token: None
    sys.modules["Quasar.ai_tools.context"] = context_mod

    constants_mod = types.ModuleType(f"{_PKG}.constants")
    constants_mod.GENERATION_MAX_WORKERS = 1
    constants_mod.GENERATION_MAX_RETRIES = 0
    constants_mod.GENERATION_RETRY_DELAY = 0
    sys.modules[f"{_PKG}.constants"] = constants_mod

    formatters_mod = types.ModuleType(f"{_PKG}.formatters")
    formatters_mod.NO_OUTPUT = lambda *_args, **_kwargs: None
    formatters_mod.publish_node_progress = lambda *_args, **_kwargs: None
    sys.modules[f"{_PKG}.formatters"] = formatters_mod

    progress_mod = types.ModuleType(f"{_PKG}.progress")
    progress_mod.publish_user_progress = lambda *_args, **_kwargs: None
    sys.modules[f"{_PKG}.progress"] = progress_mod

    helpers_mod = types.ModuleType(f"{_PKG}.helpers")
    helpers_mod.get_3d_generate_tool = lambda: None
    helpers_mod.parse_3d_result = lambda raw: raw
    helpers_mod.wait_mesh_then_resolve_model_file = lambda **_kwargs: "models/chair/base.glb"
    sys.modules[f"{_PKG}.helpers"] = helpers_mod

    local_model_mod = types.ModuleType(f"{_PKG}.local_model_library")
    local_model_mod.save_model = lambda _name, path: calls.setdefault("saved_path", path)
    sys.modules[f"{_PKG}.local_model_library"] = local_model_mod

    runtime_mod = types.ModuleType(f"{_PKG}.runtime_assets")

    class FakeBundle:
        original_model_path = "models/chair/base.glb"
        runtime_model_path = "models/chair/runtime/base.glb"

    def prepare_runtime_model_bundle(path):
        calls["prepared_path"] = path
        return FakeBundle()

    runtime_mod.prepare_runtime_model_bundle = prepare_runtime_model_bundle
    sys.modules[f"{_PKG}.runtime_assets"] = runtime_mod

    test_cases_mod = types.ModuleType(f"{_PKG}.test_cases")
    test_cases_mod.get_test_case = lambda _key: {}
    sys.modules[f"{_PKG}.test_cases"] = test_cases_mod


def _load_generate_module(calls: dict):
    _install_generate_stubs(calls)
    path = Path(__file__).with_name("generate.py")
    spec = importlib.util.spec_from_file_location(f"{_PKG}.generate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{_PKG}.generate"] = module
    spec.loader.exec_module(module)
    return module


class FakeGenerateTool:
    def invoke(self, _payload):
        return {
            "model_path": "models/chair",
            "parameter": {"object_id": "chair", "has_mesh_pending": True},
        }


class GenerateRuntimePathTests(unittest.TestCase):
    def test_generate_single_item_returns_runtime_model_path_and_saves_runtime(self):
        calls: dict = {}
        generate = _load_generate_module(calls)

        result = generate.generate_single_item(
            {
                "item_name": "椅子",
                "object_id": "chair",
                "input_image_url": "file:///tmp/chair.png",
            },
            FakeGenerateTool(),
            "session-1",
        )

        self.assertEqual(calls["prepared_path"], "models/chair/base.glb")
        self.assertEqual(calls["saved_path"], "models/chair/runtime/base.glb")
        self.assertEqual(result["model_path"], "models/chair/runtime/base.glb")


if __name__ == "__main__":
    unittest.main()
