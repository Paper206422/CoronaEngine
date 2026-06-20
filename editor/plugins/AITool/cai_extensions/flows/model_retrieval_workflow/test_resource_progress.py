"""Offline self-check for user-safe resource progress publishing."""
from __future__ import annotations

import os
import sys
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

_PROGRESS_PATH = Path(__file__).with_name("progress.py")
_WORKFLOW_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("resource_progress_under_test", _PROGRESS_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
publish_user_progress = _MODULE.publish_user_progress


def test_progress_messages_are_user_safe_and_throttled():
    messages: list[str] = []
    state = {"metadata": {"progress_sink": messages.append}}

    publish_user_progress(state, "model_batch_start", "第 1/2 批模型生成中：摊位。", progress=45)
    publish_user_progress(state, "model_batch_start", "第 1/2 批模型生成中：摊位。", progress=45)
    publish_user_progress(state, "model_batch_start", "第 1/2 批模型生成中：摊位。", progress=45, force=True)

    assert len(messages) == 2
    assert messages[0].startswith("生成进度 45%：资源准备-模型")
    assert "job_id" not in messages[0]
    assert "ThreadPool" not in messages[0]
    print("[OK] resource progress is user-safe and throttled")


def test_resource_workflow_nodes_publish_long_running_stage_progress():
    dispatch = (_WORKFLOW_DIR / "dispatch.py").read_text(encoding="utf-8")
    retrieve = (_WORKFLOW_DIR / "retrieve.py").read_text(encoding="utf-8")
    generate = (_WORKFLOW_DIR / "generate.py").read_text(encoding="utf-8")

    assert "publish_user_progress(" in dispatch
    assert '"retrieval_prepare"' in dispatch
    assert "准备检索本地素材或生成模型" in dispatch
    assert "_start_image_retry_heartbeat" in dispatch
    assert '"image_heartbeat"' in dispatch
    assert "参考图片仍在准备中" in dispatch

    assert '"retrieval_degraded"' in retrieve
    assert "素材检索当前不可用，已切换为直接生成模型" in retrieve
    assert '"retrieval_start"' in retrieve
    assert '"retrieval_done"' in retrieve

    assert '"model_start"' in generate
    assert '"model_batch_start"' in generate
    assert '"model_batch_done"' in generate
    assert "第 {batch_index}/{len(generation_batches)} 批模型生成中" in generate
    assert "concurrent.futures.wait(" in generate
    assert "return_when=concurrent.futures.FIRST_COMPLETED" in generate
    assert '"model_batch_heartbeat"' in generate
    assert "批模型仍在生成" in generate

    print("[OK] resource workflow nodes publish long-running image/retrieval/model progress")


if __name__ == "__main__":
    test_progress_messages_are_user_safe_and_throttled()
    test_resource_workflow_nodes_publish_long_running_stage_progress()
    print("\n=== resource progress ALL PASS ===")
