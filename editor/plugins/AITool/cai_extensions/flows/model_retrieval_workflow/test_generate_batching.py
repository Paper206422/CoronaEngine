"""Offline self-check for Hunyuan3D generation batching.

This test only validates batching helpers. It does not call any model provider.
"""
from __future__ import annotations

import os
import sys
import types
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

_PKG = "cai_extensions.flows.model_retrieval_workflow"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [os.path.dirname(__file__)]  # type: ignore[attr-defined]
    sys.modules[_PKG] = pkg

_GENERATE_PATH = Path(__file__).with_name("generate.py")
_SPEC = importlib.util.spec_from_file_location(f"{_PKG}.generate", _GENERATE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[f"{_PKG}.generate"] = _MODULE
_SPEC.loader.exec_module(_MODULE)

_split_generation_batches = _MODULE._split_generation_batches


def test_generation_batches_default_count():
    old_count = os.environ.get("CORONA_HUNYUAN_GENERATION_BATCH_COUNT")
    old_size = os.environ.get("CORONA_HUNYUAN_GENERATION_BATCH_SIZE")
    try:
        os.environ["CORONA_HUNYUAN_GENERATION_BATCH_COUNT"] = "4"
        os.environ.pop("CORONA_HUNYUAN_GENERATION_BATCH_SIZE", None)
        tasks = [{"item_name": f"item-{idx}", "task_index": idx} for idx in range(10)]
        batches = _split_generation_batches(tasks)
        assert [len(batch) for batch in batches] == [3, 3, 2, 2]
        assert [row["task_index"] for batch in batches for row in batch] == list(range(10))
    finally:
        if old_count is None:
            os.environ.pop("CORONA_HUNYUAN_GENERATION_BATCH_COUNT", None)
        else:
            os.environ["CORONA_HUNYUAN_GENERATION_BATCH_COUNT"] = old_count
        if old_size is None:
            os.environ.pop("CORONA_HUNYUAN_GENERATION_BATCH_SIZE", None)
        else:
            os.environ["CORONA_HUNYUAN_GENERATION_BATCH_SIZE"] = old_size
    print("[OK] generation batching splits 10 tasks into 4 ordered batches")


def test_generation_batches_explicit_size_wins():
    old_count = os.environ.get("CORONA_HUNYUAN_GENERATION_BATCH_COUNT")
    old_size = os.environ.get("CORONA_HUNYUAN_GENERATION_BATCH_SIZE")
    try:
        os.environ["CORONA_HUNYUAN_GENERATION_BATCH_COUNT"] = "4"
        os.environ["CORONA_HUNYUAN_GENERATION_BATCH_SIZE"] = "2"
        tasks = [{"item_name": f"item-{idx}", "task_index": idx} for idx in range(5)]
        batches = _split_generation_batches(tasks)
        assert [len(batch) for batch in batches] == [2, 2, 1]
    finally:
        if old_count is None:
            os.environ.pop("CORONA_HUNYUAN_GENERATION_BATCH_COUNT", None)
        else:
            os.environ["CORONA_HUNYUAN_GENERATION_BATCH_COUNT"] = old_count
        if old_size is None:
            os.environ.pop("CORONA_HUNYUAN_GENERATION_BATCH_SIZE", None)
        else:
            os.environ["CORONA_HUNYUAN_GENERATION_BATCH_SIZE"] = old_size
    print("[OK] explicit generation batch size overrides batch count")


if __name__ == "__main__":
    test_generation_batches_default_count()
    test_generation_batches_explicit_size_wins()
    print("\n=== generation batching ALL PASS ===")
