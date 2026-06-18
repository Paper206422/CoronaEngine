"""Offline self-check for retrieval search fast-fail behavior."""
from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

_PKG = "cai_extensions.flows.model_retrieval_workflow"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [os.path.dirname(__file__)]  # type: ignore[attr-defined]
    sys.modules[_PKG] = pkg


def _install_quasar_stubs() -> None:
    state_mod = types.ModuleType("Quasar.ai_workflow.state")
    state_mod.ModelRetrievalWorkflowState = dict

    streaming_mod = types.ModuleType("Quasar.ai_workflow.streaming")
    streaming_mod.stream_output_node = lambda *_args, **_kwargs: (lambda fn: fn)

    sys.modules.setdefault("Quasar", types.ModuleType("Quasar"))
    sys.modules.setdefault("Quasar.ai_workflow", types.ModuleType("Quasar.ai_workflow"))
    sys.modules["Quasar.ai_workflow.state"] = state_mod
    sys.modules["Quasar.ai_workflow.streaming"] = streaming_mod


def _install_retrieve_dependency_stubs(fake_tool) -> None:
    constants_mod = types.ModuleType(f"{_PKG}.constants")
    constants_mod.SEARCH_MAX_WORKERS = 4

    formatters_mod = types.ModuleType(f"{_PKG}.formatters")
    formatters_mod.NO_OUTPUT = lambda *_args, **_kwargs: None
    formatters_mod.publish_node_progress = lambda *_args, **_kwargs: None

    helpers_mod = types.ModuleType(f"{_PKG}.helpers")
    helpers_mod.get_search_tool = lambda: fake_tool
    helpers_mod.parse_search_result = lambda raw: raw

    local_model_mod = types.ModuleType(f"{_PKG}.local_model_library")
    local_model_mod.lookup_model = lambda _name: None

    test_cases_mod = types.ModuleType(f"{_PKG}.test_cases")
    test_cases_mod.get_test_case = lambda _key: {}

    sys.modules[f"{_PKG}.constants"] = constants_mod
    sys.modules[f"{_PKG}.formatters"] = formatters_mod
    sys.modules[f"{_PKG}.helpers"] = helpers_mod
    sys.modules[f"{_PKG}.local_model_library"] = local_model_mod
    sys.modules[f"{_PKG}.test_cases"] = test_cases_mod


def _load_retrieve_module(fake_tool):
    _install_quasar_stubs()
    _install_retrieve_dependency_stubs(fake_tool)
    path = Path(__file__).with_name("retrieve.py")
    spec = importlib.util.spec_from_file_location(f"{_PKG}.retrieve", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{_PKG}.retrieve"] = module
    spec.loader.exec_module(module)
    return module


class InvalidTokenSearchTool:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, _payload):
        self.calls += 1
        raise RuntimeError("Error code: 401 - {'message': 'Invalid Token (request id: abc)'}")


def test_search_config_error_fast_fails_remaining_tasks():
    tool = InvalidTokenSearchTool()
    retrieve = _load_retrieve_module(tool)
    result = retrieve.retrieve_node(
        {
            "intermediate": {
                "retrieval_tasks": [
                    {
                        "item_name": "灯笼",
                        "object_id": "lantern",
                        "image_url": "file:///tmp/lantern.png",
                        "image_prompt": "warm lantern",
                    },
                    {
                        "item_name": "导视牌",
                        "object_id": "sign",
                        "image_url": "file:///tmp/sign.png",
                        "image_prompt": "market sign",
                    },
                    {
                        "item_name": "长椅",
                        "object_id": "bench",
                        "image_url": "file:///tmp/bench.png",
                        "image_prompt": "wood bench",
                    },
                ]
            }
        }
    )

    pending = result["intermediate"]["pending_generation"]
    assert tool.calls == 1
    assert len(pending) == 3
    assert pending[0]["search_status"] == "error"
    assert pending[1]["search_status"] == "search_unavailable_fatal"
    assert pending[2]["search_status"] == "search_unavailable_fatal"
    assert "Invalid Token" not in pending[0]["search_error"]
    assert "request id" not in pending[1]["search_error"]
    assert pending[1]["image_prompt"] == "market sign"
    assert pending[2]["input_image_url"] == "file:///tmp/bench.png"
    print("[OK] search 401 fast-fails remaining retrieval tasks without fanout")


if __name__ == "__main__":
    test_search_config_error_fast_fails_remaining_tasks()
    print("\n=== retrieve search circuit ALL PASS ===")
