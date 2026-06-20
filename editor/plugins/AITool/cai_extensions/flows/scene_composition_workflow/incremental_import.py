"""渐进式增量导入（突击方案 §2.1 / §C3 — 只 add 不 clear）。

为什么不复用 import_to_engine_node：那个是**清场式**——每轮先 _remove_previous_actors
清掉上一批，再导入。渐进生成里这会抹掉用户中途新增/移动的物体，违反\"后续生成不
覆盖用户操作\"铁律。本模块**只导入本批新模型，绝不清场、绝不删已有 actor**。

职责（突击方案 §C3 验收）：
- 只导入本批 batch_assets。
- 不清场、不删用户物体、不覆盖已有 actor。
- 导入后立刻写 provenance=AGENT + batch_id 进 SceneLayout（唯一事实源）。
- 所有引擎写入经 EngineWriteGate（串行收口）。

纯导入逻辑：引擎工具 + SceneLayout 由调用方注入，便于离线测（注入假工具/假 layout）。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def _parse_actor_id(raw: Any, fallback_name: str) -> str:
    """从 import_model 返回里解析 actor_id（兼容 envelope/dict/裸串）。"""
    if isinstance(raw, dict):
        for k in ("actor_name", "actor_id", "name"):
            v = raw.get(k)
            if v:
                return str(v)
        actor = raw.get("actor")
        if isinstance(actor, dict):
            for k in ("name", "actor_name", "actor_id"):
                v = actor.get(k)
                if v:
                    return str(v)
    return fallback_name


def incremental_import(
    batch_assets: List[Dict[str, Any]],
    *,
    batch_id: str,
    import_tool: Any,
    scene_layout: Any,
    engine_gate: Any,
    asset_pool: Any = None,
    current_round: int = 0,
    parse_result: Optional[Callable[[Any], Dict[str, Any]]] = None,
    layout_instance_cls: Any = None,
) -> Dict[str, Any]:
    """增量导入一批资产，导入后写 provenance 元数据。

    batch_assets: [{name, path/model_path/local_path, pos?, rot?, scale?, anchor_ref?, zone_id?}]
    import_tool:  import_model StructuredTool（经 engine_gate.invoke_tool 调）
    scene_layout: SceneLayout（唯一事实源，导入后 add LayoutInstance）
    engine_gate:  EngineWriteGate（串行收口）
    layout_instance_cls: 注入点——默认用真 LayoutInstance，离线测可注入假类。

    返回 {imported: [actor_id], failed: [{name, error}]}。
    失败不抛、不影响其它资产（best-effort），整批不因单个失败中断。
    """
    if layout_instance_cls is None:
        from ...data_model.layout import LayoutInstance
    else:
        LayoutInstance = layout_instance_cls

    imported: List[str] = []
    failed: List[Dict[str, str]] = []

    if not batch_assets:
        return {"imported": imported, "failed": failed, "batch_id": batch_id}

    if import_tool is None:
        logger.warning("[IncrementalImport] import_model 工具未注册，整批跳过")
        return {"imported": imported,
                "failed": [{"name": a.get("name", "?"), "error": "import_model 未注册"}
                           for a in batch_assets],
                "batch_id": batch_id}

    for asset in batch_assets:
        name = (asset.get("name") or "").strip() or Path(asset.get("path", "")).stem
        path = asset.get("path") or asset.get("model_path") or asset.get("local_path") or ""
        if not path:
            failed.append({"name": name, "error": "无模型路径"})
            continue
        payload = {
            "model_path": path,
            "actor_name": name,
            "position": asset.get("pos", [0.0, 0.0, 0.0]),
            "rotation": asset.get("rot", [0.0, 0.0, 0.0]),
            "scale": asset.get("scale", [1.0, 1.0, 1.0]),
        }
        try:
            # ★ 经 EngineWriteGate 串行收口（绝不绕过）
            raw = engine_gate.invoke_tool(import_tool, payload)
            parsed = parse_result(raw) if parse_result else raw
            if isinstance(parsed, dict) and parsed.get("error"):
                failed.append({"name": name, "error": str(parsed["error"])})
                continue
            actor_id = _parse_actor_id(parsed, name)

            # ★ 导入后立刻写 provenance（唯一事实源 = SceneLayout）
            inst = LayoutInstance(
                instance_id=actor_id,
                asset_id=asset.get("asset_id", name),
                zone_id=asset.get("zone_id", "default"),
                transform={
                    "pos": list(payload["position"]),
                    "rot": list(payload["rotation"]),
                    "scale": list(payload["scale"]),
                },
                provenance="AGENT",      # 渐进导入的都是 AGENT，用户介入后才转 USER
                batch_id=batch_id,
                anchor_ref=asset.get("anchor_ref"),
                intervention_round=-1,    # 从未被用户介入
            )
            scene_layout.add(inst)
            imported.append(actor_id)
            logger.info("[IncrementalImport] 导入 %s (batch=%s, zone=%s)",
                        actor_id, batch_id, inst.zone_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("[IncrementalImport] 导入 %s 失败: %s", name, exc)
            failed.append({"name": name, "error": str(exc)})

    logger.info("[IncrementalImport] 批 %s 完成 — 成功 %d, 失败 %d (不清场)",
                batch_id, len(imported), len(failed))
    return {"imported": imported, "failed": failed, "batch_id": batch_id}


__all__ = ["incremental_import"]
