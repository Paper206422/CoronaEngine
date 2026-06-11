"""3D 模型自动导入引擎 helper。

供 LANChat 在 agent 生成 3D 模型后调用：等待模型文件就绪 →
调用 import_model 工具把模型导入当前引擎场景。

阻塞执行，调用方负责丢线程池。全程详细日志便于验收追踪。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SUPPORTED_EXTS = {".glb", ".gltf", ".obj", ".fbx", ".dae"}
_WAIT_TIMEOUT = 180.0      # 等待模型文件最长 180s（混元生成较慢）
_WAIT_INTERVAL = 2.0       # 每 2s 轮询一次


def _candidate_roots() -> List[Path]:
    """可能的项目根目录（模型相对路径基于此解析）。"""
    roots: List[Path] = []
    try:
        from CoronaCore.core.corona_editor import CoronaEditor
        active = getattr(CoronaEditor.CoronaEngine, "active_project_path", None)
        if active:
            roots.append(Path(active))
    except Exception:
        pass
    # 常见落地根：F:/GitHub/01 等（混元默认输出位置）
    roots.append(Path.cwd())
    return roots


def _resolve_dir(model_dir: str) -> Optional[Path]:
    """把模型目录字符串解析为实际存在的绝对路径。"""
    d = model_dir.strip().strip("`\"").replace("\\", "/")
    p = Path(d)
    if p.is_absolute() and p.exists():
        return p
    for root in _candidate_roots():
        cand = (root / d)
        if cand.exists():
            return cand
    # 兜底：全盘常见位置扫描 hunyuan 目录名
    base = os.path.basename(d)
    if base.startswith("hunyuan_"):
        for root in _candidate_roots():
            for found in root.rglob(base):
                if found.is_dir():
                    return found
    return None


def _pick_model_file(dir_path: Path) -> Optional[Path]:
    """从目录中挑选可导入的模型文件，优先 .glb。"""
    if not dir_path.is_dir():
        return None
    # 优先级顺序
    for ext in (".glb", ".gltf", ".fbx", ".obj", ".dae"):
        for entry in sorted(dir_path.iterdir()):
            if entry.is_file() and entry.suffix.lower() == ext:
                return entry
    return None


def _wait_for_model(model_dir: str) -> Optional[Path]:
    """轮询等待模型目录中出现可用模型文件。"""
    logger.info("[SceneImport] 等待模型就绪: %s (timeout=%.0fs)", model_dir, _WAIT_TIMEOUT)
    started = time.perf_counter()
    while time.perf_counter() - started < _WAIT_TIMEOUT:
        dir_path = _resolve_dir(model_dir)
        if dir_path:
            model_file = _pick_model_file(dir_path)
            if model_file and model_file.stat().st_size > 0:
                elapsed = time.perf_counter() - started
                logger.info("[SceneImport] 模型就绪: %s (%.1fKB, 等待 %.1fs)",
                            model_file, model_file.stat().st_size / 1024, elapsed)
                return model_file
        time.sleep(_WAIT_INTERVAL)
    logger.warning("[SceneImport] 等待模型超时: %s", model_dir)
    return None


def _get_import_tool():
    """获取 import_model 工具。"""
    try:
        from Quasar.ai_tools.registry import get_tool_registry
        registry = get_tool_registry()
        tools = registry.list_tools()
        if not tools:
            from Quasar.ai_tools.load_tools import load_tools
            from Quasar.ai_config.ai_config import get_ai_config
            load_tools(get_ai_config())
            tools = registry.list_tools()
        return {t.name: t for t in tools}.get("import_model")
    except Exception as e:
        logger.warning("[SceneImport] 获取 import_model 工具失败: %s", e)
        return None


def import_model_dirs_blocking(model_dirs: List[str]) -> Dict[str, Any]:
    """阻塞导入一批模型目录到引擎场景。

    Returns:
        {"imported": [actor_name, ...], "failed": [...], "error": str|None}
    """
    logger.info("[SceneImport] === 开始自动导入 %d 个模型目录 ===", len(model_dirs))
    tool = _get_import_tool()
    if tool is None:
        return {"imported": [], "failed": model_dirs, "error": "import_model 工具不可用"}

    imported: List[str] = []
    failed: List[str] = []

    for idx, model_dir in enumerate(model_dirs):
        model_file = _wait_for_model(model_dir)
        if not model_file:
            failed.append(model_dir)
            continue

        # 简单错开位置，避免多个模型叠在原点
        position = [float(idx) * 1.5, 0.0, 0.0]
        actor_name = model_file.parent.name  # 用目录名作为 actor 名

        logger.info("[SceneImport] 导入 %s → actor=%s pos=%s",
                    model_file, actor_name, position)
        try:
            raw = tool.invoke({
                "model_path": str(model_file),
                "actor_name": actor_name,
                "position": position,
            })
            ok = _is_import_success(raw)
            if ok:
                logger.info("[SceneImport] 导入成功: %s", actor_name)
                imported.append(actor_name)
            else:
                logger.warning("[SceneImport] 导入失败: %s, raw=%r", actor_name, str(raw)[:200])
                failed.append(model_dir)
        except Exception as e:
            logger.exception("[SceneImport] 导入异常: %s", e)
            failed.append(model_dir)

    logger.info("[SceneImport] === 完成: 成功 %d, 失败 %d ===", len(imported), len(failed))
    return {"imported": imported, "failed": failed, "error": None}


def _is_import_success(raw: Any) -> bool:
    """判断 import_model 工具返回是否成功。"""
    import json
    try:
        data = raw if isinstance(raw, dict) else json.loads(raw)
        if data.get("error_code", 0):
            return False
        # 检查 part 内的 status
        parts = data.get("llm_content", [{}])[0].get("part", [])
        for part in parts:
            txt = part.get("content_text", "")
            if txt:
                try:
                    inner = json.loads(txt)
                    if inner.get("status") == "success":
                        return True
                except (json.JSONDecodeError, TypeError):
                    if "success" in txt.lower():
                        return True
        return False
    except Exception:
        return False


__all__ = ["import_model_dirs_blocking", "_extract_model_dirs"]
