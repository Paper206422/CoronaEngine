"""
import_to_engine 节点 — 将 scene.json 中的 actor 导入运行中的引擎。

改进 (fanzemin):
- executor 参数支持从 PipelineGovernor 注入 per-pipeline ThreadPoolExecutor
  替代原每次调用新建池的反模式
- 未注入时回退到兼容行为（每次新建 pool）
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional

from Quasar.ai_workflow.streaming import stream_output_node

from .constants import IMPORT_MAX_WORKERS
from .formatters import NO_OUTPUT
from .helpers import get_tool, parse_import_result

logger = logging.getLogger(__name__)


def _import_single_actor(
    tool,
    actor: Dict[str, Any],
    scene_name: str,
) -> Dict[str, Any]:
    """导入单个 actor 到引擎，返回结果字典。"""
    name = actor.get("source_name") or actor.get("name", "unknown")
    # 传给引擎的 actor 名使用无扩展名版本（与 place_scene_from_items 中 display_name 保持一致）
    actor_name = actor.get("name") or Path(name).stem
    model_path = actor.get("path", "")
    geometry = actor.get("geometry", {})

    try:
        raw = tool.invoke({
            "model_path": model_path,
            "actor_name": actor_name,
            "position": geometry.get("pos", [0, 0, 0]),
            "rotation": geometry.get("rot", [0, 0, 0]),
            "scale": geometry.get("scale", [1, 1, 1]),
            "scene_name": scene_name,
        })
        parsed = parse_import_result(raw)
        if parsed.get("error"):
            return {"name": actor_name, "error": parsed["error"]}
        return {"name": parsed.get("actor_name", actor_name), "model_path": model_path, "status": "success"}
    except Exception as exc:
        logger.error("导入 actor %s 失败: %s", name, exc, exc_info=True)
        return {"name": name, "error": str(exc)}


def _remove_previous_actors(
    actors: List[Dict[str, Any]],
    scene_name: str,
) -> None:
    """清除上一轮已导入的 actor，避免重试时模型重复叠加。"""
    if not actors:
        return

    tool = get_tool("remove_model")
    if tool is None:
        logger.warning("import_to_engine: remove_model 工具未注册，跳过清场")
        return

    logger.info("import_to_engine: 清除上一轮 %d 个 actor...", len(actors))
    for actor in actors:
        name = actor.get("name", "")
        if not name:
            continue
        try:
            tool.invoke({"actor_name": name, "scene_name": scene_name})
            logger.debug("import_to_engine: 已删除 actor %s", name)
        except Exception as exc:
            logger.warning("import_to_engine: 删除 actor %s 失败: %s", name, exc)


def _get_import_executor(state, n_actors: int):
    """从 state 提取注入的 executor，未注入时回退兼容。"""
    injected = state.get("__governor__")
    if injected is not None:
        session_id = state.get("session_id", "") or "default"
        return injected.get_import_executor(session_id)
    # 回退: 每次新建池（保持兼容性）
    logger.debug("import_to_engine: 未注入 executor，回退兼容模式 (workers=%d)", IMPORT_MAX_WORKERS)
    return ThreadPoolExecutor(max_workers=min(n_actors, IMPORT_MAX_WORKERS))


@stream_output_node("integrated", NO_OUTPUT)
def import_to_engine_node(state) -> Dict[str, Any]:
    """并发导入所有 actor 到引擎场景中。"""
    intermediate = state.get("intermediate", {})
    actors = intermediate.get("scene_actors", [])
    scene_name = intermediate.get("scene_name", "composed_scene")

    if not actors:
        return {"error": "scene_actors 为空，无法导入"}

    tool = get_tool("import_model")
    if tool is None:
        return {"error": "import_model 工具未注册"}

    previous_imported = intermediate.get("imported_actors", [])
    if previous_imported:
        _remove_previous_actors(previous_imported, scene_name)

    pool = _get_import_executor(state, len(actors))
    injected = state.get("__governor__") is not None
    if injected:
        logger.info(
            "import_to_engine: [governor] 开始导入 %d 个 actor", len(actors)
        )
    else:
        logger.info(
            "import_to_engine: 开始导入 %d 个 actor (max_workers=%d)",
            len(actors), IMPORT_MAX_WORKERS,
        )

    imported: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    try:
        future_map = {
            pool.submit(_import_single_actor, tool, actor, scene_name): actor
            for actor in actors
        }
        for future in as_completed(future_map):
            result = future.result()
            if result.get("error"):
                failed.append(result)
            else:
                imported.append(result)
    finally:
        # 注入的 executor 由 PipelineGovernor 管理生命周期，不在此处 shutdown
        # 回退模式下才需要显式 shutdown
        if not injected:
            pool.shutdown(wait=True, cancel_futures=False)

    logger.info(
        "import_to_engine: 完成 — 成功 %d, 失败 %d",
        len(imported),
        len(failed),
    )

    return {
        "intermediate": {
            "imported_actors": imported,
            "failed_actors": failed,
        },
    }
