from __future__ import annotations

import time
from typing import Any, Dict


_DEFAULT_MIN_INTERVAL_SECONDS = 8.0
_HEARTBEAT_INTERVAL_SECONDS = 60.0


def publish_user_progress(
    state: Dict[str, Any],
    stage: str,
    message: str,
    *,
    progress: int | None = None,
    force: bool = False,
) -> None:
    """Publish a user-safe resource progress message through SceneComposer's sink."""

    metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
    if not isinstance(metadata, dict):
        return
    sink = metadata.get("progress_sink")
    if not callable(sink):
        return

    safe_message = _format_message(stage, message, progress=progress)
    if not safe_message:
        return

    now = time.time()
    throttle_state = metadata.setdefault("_resource_progress_throttle", {})
    if not isinstance(throttle_state, dict):
        throttle_state = {}
        metadata["_resource_progress_throttle"] = throttle_state

    last_by_stage = throttle_state.setdefault("last_by_stage", {})
    if not isinstance(last_by_stage, dict):
        last_by_stage = {}
        throttle_state["last_by_stage"] = last_by_stage

    last = last_by_stage.get(stage)
    if not force and isinstance(last, dict):
        last_at = float(last.get("at") or 0.0)
        last_text = str(last.get("text") or "")
        min_interval = _HEARTBEAT_INTERVAL_SECONDS if stage.endswith("_heartbeat") else _DEFAULT_MIN_INTERVAL_SECONDS
        if safe_message == last_text and now - last_at < min_interval:
            return

    last_by_stage[stage] = {"at": now, "text": safe_message}
    try:
        sink(safe_message)
    except Exception:
        return


def _format_message(stage: str, message: str, *, progress: int | None = None) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    prefix = _stage_prefix(stage)
    if progress is None:
        return f"{prefix}：{text}" if prefix else text
    pct = max(0, min(100, int(progress)))
    return f"生成进度 {pct}%：{prefix}：{text}" if prefix else f"生成进度 {pct}%：{text}"


def _stage_prefix(stage: str) -> str:
    stage = str(stage or "").strip().lower()
    if stage.startswith("image"):
        return "资源准备-图片"
    if stage.startswith("retrieval"):
        return "资源准备-检索"
    if stage.startswith("model") or stage.startswith("generation"):
        return "资源准备-模型"
    if stage.startswith("register"):
        return "资源准备-入库"
    if stage.startswith("import"):
        return "分批导入"
    return "资源准备"


__all__ = ["publish_user_progress"]
