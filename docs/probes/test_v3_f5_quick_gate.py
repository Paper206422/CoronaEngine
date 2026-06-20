"""Offline self-checks for docs/probes/v3_f5_quick_gate.py."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path


_GATE_PATH = Path(__file__).with_name("v3_f5_quick_gate.py")
_SPEC = importlib.util.spec_from_file_location("v3_f5_quick_gate_under_test", _GATE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)


def _test_temp_root() -> Path:
    root = Path(__file__).resolve().parents[2] / ".tmp" / "test-temp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _named_test_dir(name: str) -> Path:
    path = _test_temp_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_log(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        suffix="_corona.log",
        delete=False,
        dir=_test_temp_root(),
    )
    with handle:
        handle.write(text)
    return Path(handle.name)


def test_report_writer_records_probe_summary():
    log_path = _write_log(
        "\n".join(
            [
                "[2026-06-19T04:00:00.000000][1][INFO] network_send_system_message 生成进度 10%：资源准备-图片：参考图片仍在准备中",
                "[2026-06-19T04:00:30.000000][1][INFO] network_send_system_message 生成进度 55%：资源准备-模型：第 1/2 批模型仍在生成",
                "[2026-06-19T04:00:31.000000][1][INFO] NetworkSystem: Broadcast actor create — actor='actor-a' scene='Scene/场景1.scene' model='Resource/terrain.obj' deps=1",
                "[2026-06-19T04:00:32.000000][1][INFO] NetworkSystem: Received FILE_REQUEST from peer — id=2 path='Resource/terrain.obj'",
                "[2026-06-19T04:00:33.000000][1][DEBUG] [MeshOpt] Mesh 'terrain': split 1",
                "[2026-06-19T04:00:34.000000][1][DEBUG] [MeshOpt] Mesh 'terrain_detail': split 1",
                "[2026-06-19T04:00:34.500000][1][INFO] network_send_system_message 可介入窗口：已记录“新增一只小狗”，会优先进入下一批或最终调整。",
                "[2026-06-19T04:00:35.000000][1][INFO] network_send_agent_reply [场景设计大师] 场景组合完成 • 导入引擎：1 个 ✅ 已放入场景：terrain",
                "[2026-06-19T04:00:36.000000][1][INFO] network_send_agent_reply • 生成中吸收：1 条后续要求",
            ]
        )
    )
    temp_dir = _named_test_dir("v3_f5_quick_gate_report")
    original_dir = _MODULE.REPORT_DIR
    try:
        _MODULE.REPORT_DIR = Path(temp_dir)
        report_path = _MODULE._write_report(log_path, verify_exit=None)
    finally:
        _MODULE.REPORT_DIR = original_dir

    report = report_path.read_text(encoding="utf-8")
    assert "V3 F5 运行报告" in report
    assert str(log_path) in report
    assert "非 native 总门禁：skipped" in report
    assert "日志新鲜度：" in report
    assert "F5_READY: PASS=9 WARN=0 FAIL=0" in report
    assert "| 级别 | 检查项 | 说明 | 处置建议 |" in report
    assert "| PASS | actor-create |" in report
    assert "actor create 去重" in report
    print("[OK] V3 F5 quick gate writes Markdown report")


def test_freshness_status_detects_stale_log():
    temp_dir = _named_test_dir("v3_f5_quick_gate_freshness")
    sentinel = Path(temp_dir) / "sentinel.py"
    log_path = _write_log("[2026-06-19T04:00:00.000000][1][INFO] empty")
    sentinel.write_text("# changed after log\n", encoding="utf-8")
    now = time.time()
    os.utime(log_path, (now - 10, now - 10))
    os.utime(sentinel, (now, now))

    original_sentinels = _MODULE.FRESHNESS_SENTINELS
    try:
        _MODULE.FRESHNESS_SENTINELS = (sentinel,)
        level, detail = _MODULE._freshness_status(log_path)
    finally:
        _MODULE.FRESHNESS_SENTINELS = original_sentinels

    assert level == "STALE"
    assert "重新 F5" in detail
    print("[OK] V3 F5 quick gate detects stale logs")


def test_require_fresh_fails_stale_log_without_blocking_review_mode():
    class _Probe:
        def _latest_log(self):
            return Path("stale_corona.log")

    original_run = _MODULE._run
    original_load = _MODULE._load_log_probe
    original_freshness = _MODULE._freshness_status
    try:
        _MODULE._run = lambda *args, **kwargs: 0
        _MODULE._load_log_probe = lambda: _Probe()
        _MODULE._freshness_status = lambda path: ("STALE", "旧日志")

        assert _MODULE.main(["--skip-verify"]) == 0
        assert _MODULE.main(["--skip-verify", "--require-fresh"]) == 1
    finally:
        _MODULE._run = original_run
        _MODULE._load_log_probe = original_load
        _MODULE._freshness_status = original_freshness
    print("[OK] V3 F5 quick gate require-fresh blocks stale sign-off")


if __name__ == "__main__":
    test_report_writer_records_probe_summary()
    test_freshness_status_detects_stale_log()
    test_require_fresh_fails_stale_log_without_blocking_review_mode()
    print("\n=== V3 F5 quick gate ALL PASS ===")
