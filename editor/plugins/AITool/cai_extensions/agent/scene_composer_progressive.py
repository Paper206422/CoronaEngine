"""SceneComposer 渐进式工作流接入（突击方案 COMMIT 1-5 集成）。

本模块提供 `_run_progressive_workflow`，用于替换 scene_composer.py 的
`_run_original_workflow`（清场式一次性导入）为渐进式路径（只 add 不 clear + 视口介入）。

设计：最小侵入——复用现有框架生成（_generate_scene_framework/_place_shells），
只替换布局+导入部分（compose_scene + import_to_engine → progressive_compose +
incremental_import）。scene_composer.py 加开关，新旧路径并存，零回归。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def run_progressive_workflow(
    composer: Any,  # SceneComposer 实例
    prompt: str,
    resolved: List[Dict[str, Any]],
    all_items: List[Dict[str, Any]],
    do_import: bool,
    reviews: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """渐进式场景组合工作流（突击方案完整接入）。

    复用 composer 的框架生成（terrain/box/shell/interior/fence），
    用 progressive_compose 替代一次性布局+导入，集成：
      - SceneSession（phase 边界交错 + 近因加权保护 + FinalReview）
      - SceneDiffTracker（视口拖拽捕获，命门）
      - consistency_check（AABB 内回路，防穿模）
      - incremental_import（只 add 不 clear）
      - vlm_review_loop（外回路，advisory 建议）

    参数与 _run_original_workflow 一致，便于 compose() 开关切换。
    """
    # 1. 场景框架生成（复用现有逻辑，零改动）
    composer._generate_scene_framework(prompt)
    shell_models = getattr(composer, "_shell_models", None)
    if shell_models:
        composer._shell_report = composer._place_shells(shell_models)

    # 2. 渐进式主循环（新路径）
    from .scene_session import SceneSession, PHASE_ORDER
    from .scene_diff import SceneDiffTracker
    from .engine_write_gate import get_engine_write_gate
    from ..flows.scene_composition_workflow.incremental_import import incremental_import
    from .consistency_check import (
        CheckResult,
        check_out_of_zone,
        reasonable_map_from_result,
        run_furniture_checks,
    )

    # 取 SceneLayout（唯一事实源）
    scene_layout = getattr(composer, "scene_layout", None)
    if scene_layout is None:
        # 如果 composer 还没有 scene_layout，创建一个
        from ..data_model.layout import SceneLayout
        scene_layout = SceneLayout()
        composer.scene_layout = scene_layout

    # 初始化 session + diff tracker
    diff_tracker = SceneDiffTracker()
    engine_gate = get_engine_write_gate()
    session = SceneSession(
        scene_layout,
        diff_tracker=diff_tracker,
        engine_gate=engine_gate,
        scene_name=composer.scene_name or "progressive_scene",
    )

    # 设置基线快照（框架已生成，作为初始状态）
    initial_snapshot = _capture_viewport_snapshot(composer)
    if initial_snapshot:
        diff_tracker.set_baseline(initial_snapshot)

    # 3. Phase generators（按 PHASE_ORDER 生成资产）
    # 简化版：这里先把 resolved 按名字分配到各 phase（真实逻辑可按 placement_type 等分类）
    phase_assets = _distribute_assets_to_phases(resolved, all_items, composer)

    def make_phase_gen(phase: str):
        def gen(sess: SceneSession, ph: str) -> List[Dict[str, Any]]:
            assets = phase_assets.get(phase, [])
            logger.info("[ProgressiveWorkflow] phase %s: %d assets", phase, len(assets))
            return assets
        return gen

    phase_generators = {ph: make_phase_gen(ph) for ph in PHASE_ORDER
                        if phase_assets.get(ph)}

    # 4. Importer（调 incremental_import）
    from ..flows.scene_composition_workflow.helpers import get_tool, parse_import_result
    import_tool = get_tool("import_model")

    def importer(assets: List[Dict[str, Any]], batch_id: str) -> Dict[str, Any]:
        return incremental_import(
            assets,
            batch_id=batch_id,
            import_tool=import_tool,
            scene_layout=scene_layout,
            engine_gate=engine_gate,
            current_round=session.current_round,
            parse_result=parse_import_result,
        )

    # 5. Viewport sampler（采集视口快照）
    def viewport_sampler() -> Dict[str, Any]:
        return _capture_viewport_snapshot(composer)

    # 6. Reasonable provider（E5 AABB 检查）
    def reasonable_provider() -> Dict[str, bool]:
        aabbs = _collect_aabbs(scene_layout)
        door_aabbs = _collect_door_clearance_aabbs(getattr(composer, "zone_tree", None))
        zone_aabbs = _collect_zone_aabbs(getattr(composer, "zone_tree", None))

        # 全局先做便宜硬检查：悬空、穿模、挡门。门洞 clearance 来自 ZoneTree connector。
        result = run_furniture_checks(aabbs, ground_y=0.0, door_aabbs=door_aabbs)

        # 再按 LayoutInstance.zone_id 分组做 zone 约束，避免把室外篝火/围栏误判为室内越界。
        for zone_id, zone_aabb in zone_aabbs.items():
            scoped = _filter_aabbs_by_zone(scene_layout, aabbs, zone_id)
            if not scoped:
                continue
            result.issues.extend(check_out_of_zone(scoped, zone_aabb, zone_id=zone_id))

        actor_ids = list(aabbs.keys())
        return reasonable_map_from_result(result, actor_ids)

    # 7. 运行渐进主循环
    prog_result = session.progressive_compose(
        phase_generators,
        importer=importer,
        viewport_sampler=viewport_sampler,
        reasonable_provider=reasonable_provider,
    )

    # 8. 返回（格式与 _run_original_workflow 一致）
    imported = prog_result.get("imported", [])
    failed = [it["name"] for it in resolved if it["name"] not in imported]
    return {
        "items": resolved,
        "imported": imported,
        "failed": failed,
        "extracted_count": len(all_items),
        "model_count": len(resolved),
        "scene_path": None,  # 渐进式不用 scene.json
        "error": None,
        "progressive": True,
        "final_report": prog_result.get("final_report"),
        "phases_run": prog_result.get("phases_run", []),
    }


def _capture_viewport_snapshot(composer: Any) -> Dict[str, Any]:
    """采集当前视口的 transform 快照（喂给 SceneDiffTracker）。"""
    try:
        from CoronaCore.core.managers import scene_manager
        from .scene_diff import make_transform
        scene = scene_manager.get_active_scene()
        if scene is None:
            return {}
        snapshot = {}
        for actor in scene.get_actors():
            aid = actor.get_name()
            pos = actor.get_position()
            rot = actor.get_rotation()
            scale = actor.get_scale()
            snapshot[aid] = make_transform(pos, rot, scale)
        return snapshot
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProgressiveWorkflow] 采集快照失败: %s", exc)
        return {}


def _distribute_assets_to_phases(
    resolved: List[Dict[str, Any]],
    all_items: List[Dict[str, Any]],
    composer: Any,
) -> Dict[str, List[Dict[str, Any]]]:
    """把资产分配到各 phase（简化版：按名字关键词）。

    真实逻辑应读 placement_type / asset_metadata 分类。
    这里先用关键词兜底，让流程能跑通。
    """
    from .scene_session import PHASE_ORDER
    phase_map = {ph: [] for ph in PHASE_ORDER}
    indoor_zone_id, outdoor_zone_id, shell_zone_id = _infer_primary_zone_ids(composer)

    for asset in resolved:
        asset = dict(asset)
        name = (asset.get("name") or "").lower()
        # 简单分类（可扩展为查 placement_type）
        if any(kw in name for kw in ["地毯", "rug", "floor", "桌", "table", "椅", "chair", "床", "bed"]):
            if indoor_zone_id:
                asset.setdefault("zone_id", indoor_zone_id)
            if shell_zone_id:
                asset.setdefault("anchor_ref", shell_zone_id)
            phase_map["INTERIOR"].append(asset)
        elif any(kw in name for kw in ["栅栏", "fence", "boundary", "围栏"]):
            if outdoor_zone_id:
                asset.setdefault("zone_id", outdoor_zone_id)
            phase_map["BOUNDARY"].append(asset)
        elif any(kw in name for kw in ["篝火", "火堆", "campfire", "bonfire", "木柴", "log", "horse", "马"]):
            if outdoor_zone_id:
                asset.setdefault("zone_id", outdoor_zone_id)
            phase_map["OBJECTS"].append(asset)
        elif any(kw in name for kw in ["灯", "lamp", "light", "装饰", "deco"]):
            if indoor_zone_id:
                asset.setdefault("zone_id", indoor_zone_id)
            if shell_zone_id:
                asset.setdefault("anchor_ref", shell_zone_id)
            phase_map["DECORATION"].append(asset)
        else:
            if indoor_zone_id:
                asset.setdefault("zone_id", indoor_zone_id)
            phase_map["OBJECTS"].append(asset)

    return phase_map


def _infer_primary_zone_ids(composer: Any) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """推断当前混合环境的主要 indoor/outdoor/shell zone。

    只从 ZoneTree 读事实，不写死蒙古包；草原蒙古包、庭院建筑、洞穴营地都走同一逻辑。
    """
    tree = getattr(composer, "zone_tree", None)
    if tree is None or getattr(tree, "root", None) is None:
        return None, None, None

    indoor_zone_id = None
    outdoor_zone_id = None
    shell_zone_id = None
    for zone in tree.list_all_zones():
        enclosure = (getattr(zone, "enclosure", "") or "").lower()
        role = (getattr(zone, "role", "") or "").lower()
        if outdoor_zone_id is None and (role == "outdoor" or enclosure == "terrain"):
            outdoor_zone_id = zone.zone_id
        if indoor_zone_id is None and (role == "indoor" or enclosure in ("box", "shell")):
            indoor_zone_id = zone.zone_id
        if shell_zone_id is None and enclosure == "shell":
            shell_zone_id = zone.zone_id
    return indoor_zone_id, outdoor_zone_id, shell_zone_id


def _zone_to_aabb(zone: Any) -> Optional[List[float]]:
    volume = getattr(zone, "volume", None)
    if volume is None:
        return None
    center = list(getattr(volume, "center", []) or [])
    size = list(getattr(volume, "size", []) or [])
    if len(center) < 3 or len(size) < 2:
        return None
    width = float(size[0])
    depth = float(size[1])
    height = float(size[2]) if len(size) > 2 and float(size[2] or 0.0) > 0.0 else 0.2
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    return [
        cx - width / 2.0,
        cy - height / 2.0,
        cz - depth / 2.0,
        cx + width / 2.0,
        cy + height / 2.0,
        cz + depth / 2.0,
    ]


def _collect_zone_aabbs(zone_tree: Any) -> Dict[str, List[float]]:
    """从 ZoneTree 派生各 zone 的 XZ 检查边界。"""
    if zone_tree is None or getattr(zone_tree, "root", None) is None:
        return {}
    out: Dict[str, List[float]] = {}
    for zone in zone_tree.list_all_zones():
        aabb = _zone_to_aabb(zone)
        if aabb:
            out[zone.zone_id] = aabb
    return out


def _connector_to_clearance_aabb(connector: Any, owner_zone: Any, clearance_depth: float = 1.0) -> Optional[List[float]]:
    """把 door/passsage connector 转成禁入 AABB，防止家具/装饰堵门。

    Connector position 使用现有约定：位于 owner zone 局部空间。当前 ZoneTree 还不支持旋转，
    因此这里按世界轴对齐计算；以后支持旋转时只需要替换这一层。
    """
    if getattr(connector, "type", "") not in ("door", "passage"):
        return None
    pos = list(getattr(connector, "position", []) or [])
    size = list(getattr(connector, "size", []) or [])
    if len(pos) < 3 or len(size) < 2:
        return None
    volume = getattr(owner_zone, "volume", None)
    center = list(getattr(volume, "center", []) or [0.0, 0.0, 0.0])
    if len(center) < 3:
        center = [0.0, 0.0, 0.0]
    x = float(center[0]) + float(pos[0])
    z = float(center[2]) + float(pos[2])
    width = max(0.3, float(size[0]))
    height = max(1.0, float(size[1]))
    depth = max(0.5, float(clearance_depth))
    return [
        x - width / 2.0,
        0.0,
        z - depth / 2.0,
        x + width / 2.0,
        height,
        z + depth / 2.0,
    ]


def _collect_door_clearance_aabbs(zone_tree: Any) -> Dict[str, List[float]]:
    """收集所有门洞/通道清空区，作为 AABB 硬约束输入。"""
    if zone_tree is None or getattr(zone_tree, "root", None) is None:
        return {}
    out: Dict[str, List[float]] = {}
    for zone in zone_tree.list_all_zones():
        for connector in getattr(zone, "connectors", []) or []:
            aabb = _connector_to_clearance_aabb(connector, zone)
            if aabb:
                cid = getattr(connector, "connector_id", None) or f"door_{zone.zone_id}_{len(out)}"
                out[str(cid)] = aabb
    return out


def _filter_aabbs_by_zone(scene_layout: Any, aabbs: Dict[str, List[float]], zone_id: str) -> Dict[str, List[float]]:
    """只取属于某个 zone 的实例，避免混合环境中 indoor/outdoor 互相误判。"""
    out: Dict[str, List[float]] = {}
    try:
        instances = scene_layout.list_active()
    except Exception:
        return out
    for inst in instances:
        actor_id = getattr(inst, "instance_id", None)
        if actor_id in aabbs and getattr(inst, "zone_id", None) == zone_id:
            out[actor_id] = aabbs[actor_id]
    return out


def _collect_aabbs(scene_layout: Any) -> Dict[str, List[float]]:
    """从 scene_layout 采集各 actor 的 AABB（喂给 consistency_check）。"""
    try:
        from CoronaCore.core.managers import scene_manager
        scene = scene_manager.get_active_scene()
        if scene is None:
            return {}
        aabbs = {}
        for inst in scene_layout.list_active():
            actor = scene.get_actor_by_name(inst.instance_id)
            if actor is None:
                continue
            bb = actor.get_bounding_box()
            if bb and len(bb) >= 6:
                aabbs[inst.instance_id] = list(bb)
        return aabbs
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProgressiveWorkflow] 采集 AABB 失败: %s", exc)
        return {}


__all__ = ["run_progressive_workflow"]
