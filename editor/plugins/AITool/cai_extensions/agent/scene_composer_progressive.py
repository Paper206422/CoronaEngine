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
    progress_sink: Optional[Any] = None,
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
    _generate_post_shell_framework(composer)

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
    progress_events: List[str] = []
    def _progress_sink(message: str) -> None:
        progress_events.append(message)
        if callable(progress_sink):
            try:
                progress_sink(message)
            except Exception as exc:  # noqa: BLE001
                logger.debug("[ProgressiveWorkflow] progress sink skipped: %s", exc)

    session.set_progress_sink(_progress_sink)

    # 设置基线快照（框架已生成，作为初始状态）
    initial_snapshot = _capture_viewport_snapshot(composer)
    if initial_snapshot:
        diff_tracker.set_baseline(initial_snapshot)

    # 3. Phase generators（按 PHASE_ORDER 生成资产）
    # 简化版：这里先把 resolved 按名字分配到各 phase（真实逻辑可按 placement_type 等分类）
    phase_assets = _distribute_assets_to_phases(resolved, all_items, composer)
    phase_sequence, phase_metadata, micro_phase_assets = _build_micro_batch_phase_plan(phase_assets)
    _refresh_micro_batch_metadata(phase_sequence, phase_metadata, micro_phase_assets)
    batch_size = max(1, int(os.getenv("CORONA_PROGRESSIVE_BATCH_SIZE", "3") or "3"))

    def make_phase_gen(phase: str):
        def gen(sess: SceneSession, ph: str) -> List[Dict[str, Any]]:
            assets = list(micro_phase_assets.get(phase, []) or [])
            notes = _consume_runtime_scene_notes()
            if notes:
                assets = _apply_pending_notes_to_batch(
                    assets,
                    notes,
                    sess,
                    current_phase=phase,
                    micro_phase_assets=micro_phase_assets,
                    phase_sequence=phase_sequence,
                    max_batch_size=batch_size + 2,
                )
                micro_phase_assets[phase] = assets
                _refresh_micro_batch_metadata(phase_sequence, phase_metadata, micro_phase_assets)
            logger.info("[ProgressiveWorkflow] phase %s: %d assets", phase, len(assets))
            return assets
        return gen

    phase_generators = {ph: make_phase_gen(ph) for ph in phase_sequence
                        if micro_phase_assets.get(ph)}

    def runtime_mode_provider() -> str:
        try:
            from plugins.AITool.services.lanchat_scene_runtime import get_lanchat_scene_runtime
        except Exception:  # noqa: BLE001
            try:
                from services.lanchat_scene_runtime import get_lanchat_scene_runtime  # type: ignore
            except Exception:
                return ""
        try:
            return get_lanchat_scene_runtime().mode()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ProgressiveWorkflow] runtime mode unavailable: %s", exc)
            return ""

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
        post_import_hook=lambda imported_ids, _batch_id: _repair_recent_imports(
            imported_ids,
            scene_layout,
            engine_gate,
            zone_aabbs=_collect_zone_aabbs(getattr(composer, "zone_tree", None)),
            door_aabbs=_collect_door_clearance_aabbs(getattr(composer, "zone_tree", None)),
            issue_sink=session.pending_tasks,
        ),
        phase_sequence=phase_sequence,
        phase_metadata=phase_metadata,
        runtime_mode_provider=runtime_mode_provider,
    )

    # 8. 返回（格式与 _run_original_workflow 一致）
    imported = prog_result.get("imported", [])
    failed = [it["name"] for it in resolved if it["name"] not in imported]
    final_report = prog_result.get("final_report")
    final_report_text = (
        final_report.to_user_text()
        if hasattr(final_report, "to_user_text")
        else None
    )
    vlm_report = _run_vlm_advisory_review(imported, engine_gate)
    vlm_review_text = (
        vlm_report.to_user_text()
        if hasattr(vlm_report, "to_user_text")
        else None
    )
    return {
        "items": resolved,
        "imported": imported,
        "failed": failed,
        "extracted_count": len(all_items),
        "model_count": len(resolved),
        "scene_path": None,  # 渐进式不用 scene.json
        "error": None,
        "progressive": True,
        "final_report": final_report,
        "final_report_text": final_report_text,
        "phases_run": prog_result.get("phases_run", []),
        "progress_events": progress_events,
        "progress_timeline": prog_result.get("progress_timeline", []),
        "operation_log": _serialize_operation_log(getattr(session, "operation_log", [])),
        "operation_count": len(getattr(session, "operation_log", [])),
        "pending_tasks": list(getattr(session, "pending_tasks", []) or []),
        "round": prog_result.get("round"),
        "paused": bool(prog_result.get("paused")),
        "paused_mode": prog_result.get("paused_mode"),
        "paused_before_phase": prog_result.get("paused_before_phase"),
        "vlm_review": vlm_report,
        "vlm_review_text": vlm_review_text,
        "vlm_review_skipped": list(getattr(vlm_report, "skipped", []) or []),
        "vlm_review_timed_out": list(getattr(vlm_report, "timed_out", []) or []),
    }


def _build_micro_batch_phase_plan(
    phase_assets: Dict[str, List[Dict[str, Any]]],
) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """Split content phases into real micro-batches.

    Framework phases remain as-is. INTERIOR/OBJECTS/DECORATION are user-visible
    placement phases, so they become 2-3 item batches to create intervention
    windows between imports.
    """
    from .scene_session import PHASE_ORDER

    batch_size = max(1, int(os.getenv("CORONA_PROGRESSIVE_BATCH_SIZE", "3") or "3"))
    split_phases = {"INTERIOR", "OBJECTS", "DECORATION"}
    sequence: List[str] = []
    metadata: Dict[str, Dict[str, Any]] = {}
    out: Dict[str, List[Dict[str, Any]]] = {}
    total_assets = sum(len(items or []) for items in phase_assets.values())

    for phase in PHASE_ORDER:
        assets = list(phase_assets.get(phase) or [])
        if not assets:
            continue
        if phase not in split_phases or len(assets) <= batch_size:
            sequence.append(phase)
            out[phase] = assets
            metadata[phase] = {
                "batch_index": 1,
                "batch_total": 1,
                "asset_count": len(assets),
                "total_assets": total_assets,
            }
            continue

        ordered = sorted(assets, key=_micro_batch_sort_key)
        batches = [ordered[i:i + batch_size] for i in range(0, len(ordered), batch_size)]
        for idx, batch in enumerate(batches, 1):
            key = f"{phase}#{idx}"
            sequence.append(key)
            out[key] = batch
            metadata[key] = {
                "batch_index": idx,
                "batch_total": len(batches),
                "asset_count": len(batch),
                "total_assets": total_assets,
            }
    return sequence, metadata, out


def _asset_names(assets: List[Dict[str, Any]]) -> List[str]:
    return [str(item.get("name") or "").strip()
            for item in assets if isinstance(item, dict) and str(item.get("name") or "").strip()]


def _refresh_micro_batch_metadata(
    phase_sequence: List[str],
    metadata: Dict[str, Dict[str, Any]],
    micro_phase_assets: Dict[str, List[Dict[str, Any]]],
) -> None:
    total_assets = sum(len(micro_phase_assets.get(phase) or []) for phase in phase_sequence)
    for idx, phase in enumerate(phase_sequence):
        assets = list(micro_phase_assets.get(phase) or [])
        meta = metadata.setdefault(phase, {})
        meta["asset_count"] = len(assets)
        meta["total_assets"] = total_assets
        meta["batch_asset_names"] = _asset_names(assets)
        next_names: List[str] = []
        for next_phase in phase_sequence[idx + 1:]:
            next_assets = micro_phase_assets.get(next_phase) or []
            if next_assets:
                next_names = _asset_names(next_assets)
                break
        meta["next_batch_asset_names"] = next_names


def _micro_batch_sort_key(asset: Dict[str, Any]) -> Tuple[int, str]:
    role = str(asset.get("layout_role") or "").lower()
    name = str(asset.get("name") or "")
    priority = {
        "main": 0,
        "landmark": 0,
        "foreground_object": 1,
        "furniture": 1,
        "support": 1,
        "surface": 2,
        "decoration": 3,
        "ground_cover": 3,
    }.get(role, 2)
    return priority, name


def _consume_runtime_scene_notes() -> List[Any]:
    try:
        from plugins.AITool.services.lanchat_scene_runtime import get_lanchat_scene_runtime
    except Exception:  # noqa: BLE001
        try:
            from services.lanchat_scene_runtime import get_lanchat_scene_runtime  # type: ignore
        except Exception:  # noqa: BLE001
            return []
    try:
        return list(get_lanchat_scene_runtime().consume_notes())
    except Exception:  # noqa: BLE001
        return []


def _apply_pending_notes_to_batch(
    assets: List[Dict[str, Any]],
    notes: List[Any],
    session: SceneSession,
    *,
    current_phase: str = "",
    micro_phase_assets: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    phase_sequence: Optional[List[str]] = None,
    max_batch_size: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Apply safe pending notes to the next batch.

    This path does not spawn new model-generation jobs mid-compose. It can
    remove forbidden future assets, nudge next-batch placement constraints, and
    pull already-resolved future assets into the next import window.
    """
    remaining = list(assets)
    future_batches = micro_phase_assets or {}
    ordered_phases = phase_sequence or []
    max_count = max_batch_size or 0
    for note in notes:
        text = str(getattr(note, "text", "") or "")
        kind = str(getattr(note, "kind", "") or "")
        source = str(getattr(note, "source_agent", "") or "")
        task = {
            "kind": kind,
            "text": text,
            "source": source,
            "status": "recorded",
        }
        if kind == "layout_constraint":
            affected: List[str] = []
            for asset in remaining:
                constraints = asset.setdefault("runtime_layout_constraints", [])
                if text and text not in constraints:
                    constraints.append(text)
                if _apply_runtime_layout_constraint(asset, text):
                    affected.append(str(asset.get("name") or ""))
            task["status"] = "applied_to_next_batch_layout" if affected else "recorded_layout_constraint"
            if affected:
                task["affected_assets"] = [name for name in affected if name][:6]
        negative = any(word in text.lower() for word in ("不要", "别再", "移除后续", "do not", "don't", "remove", "no more"))
        if kind == "layout_constraint":
            pass
        elif kind == "generation_delta" and not negative:
            matched_existing = False
            for asset in remaining:
                context = asset.setdefault("runtime_generation_context", [])
                if text and text not in context:
                    context.append(text)
                name = str(asset.get("name") or "")
                if name and name in text:
                    matched_existing = True
            inserted = []
            if not matched_existing:
                inserted = _pull_matching_future_assets(
                    text,
                    remaining,
                    future_batches=future_batches,
                    phase_sequence=ordered_phases,
                    current_phase=current_phase,
                    max_batch_size=max_count,
                )
            if matched_existing:
                task["status"] = "already_in_remaining_plan"
            elif inserted:
                task["status"] = "inserted_into_remaining_batch"
                task["affected_assets"] = inserted[:6]
            else:
                task["status"] = "deferred_missing_asset"
        elif kind == "generation_delta" and negative:
            filtered: List[Dict[str, Any]] = []
            removed: List[str] = []
            for asset in remaining:
                name = str(asset.get("name") or "")
                if name and name in text:
                    logger.info("[ProgressiveWorkflow] pending note removed future asset: %s", name)
                    removed.append(name)
                    continue
                filtered.append(asset)
            remaining = filtered
            if future_batches:
                future_removed = _remove_matching_future_assets(
                    text,
                    future_batches=future_batches,
                    phase_sequence=ordered_phases,
                    current_phase=current_phase,
                )
                removed.extend(future_removed)
            task["status"] = "applied_removed_from_remaining" if removed else "recorded_no_matching_asset"
            if removed:
                task["affected_assets"] = removed[:6]
        elif kind == "edit_existing":
            task["status"] = "queued_edit_or_waiting_for_actor"
        session.pending_tasks.append(task)
    return remaining


def _normalize_asset_text(text: str) -> str:
    return str(text or "").lower().replace(" ", "").replace("_", "").replace("-", "")


def _asset_matches_note(asset: Dict[str, Any], note_text: str) -> bool:
    note = _normalize_asset_text(note_text)
    if not note:
        return False
    candidates = [
        str(asset.get("name") or ""),
        str(asset.get("semantic_type") or ""),
        str(asset.get("asset_id") or ""),
    ]
    for value in candidates:
        normalized = _normalize_asset_text(value)
        if len(normalized) >= 2 and (normalized in note or note in normalized):
            return True
    return False


def _pull_matching_future_assets(
    note_text: str,
    current_assets: List[Dict[str, Any]],
    *,
    future_batches: Dict[str, List[Dict[str, Any]]],
    phase_sequence: List[str],
    current_phase: str,
    max_batch_size: int,
) -> List[str]:
    inserted: List[str] = []
    if not future_batches or not phase_sequence or not current_phase:
        return inserted
    current_index = phase_sequence.index(current_phase) if current_phase in phase_sequence else -1
    if current_index < 0:
        return inserted
    for phase in phase_sequence[current_index + 1:]:
        future = list(future_batches.get(phase) or [])
        if not future:
            continue
        kept: List[Dict[str, Any]] = []
        for asset in future:
            if _asset_matches_note(asset, note_text) and (not max_batch_size or len(current_assets) < max_batch_size):
                moved = dict(asset)
                moved["source"] = "USER_PENDING_DELTA"
                context = moved.setdefault("runtime_generation_context", [])
                if note_text and note_text not in context:
                    context.append(note_text)
                current_assets.append(moved)
                inserted.append(str(moved.get("name") or ""))
                continue
            kept.append(asset)
        future_batches[phase] = kept
    return [name for name in inserted if name]


def _remove_matching_future_assets(
    note_text: str,
    *,
    future_batches: Dict[str, List[Dict[str, Any]]],
    phase_sequence: List[str],
    current_phase: str,
) -> List[str]:
    removed: List[str] = []
    current_index = phase_sequence.index(current_phase) if current_phase in phase_sequence else -1
    if current_index < 0:
        return removed
    for phase in phase_sequence[current_index + 1:]:
        future = list(future_batches.get(phase) or [])
        if not future:
            continue
        kept: List[Dict[str, Any]] = []
        for asset in future:
            if _asset_matches_note(asset, note_text):
                removed.append(str(asset.get("name") or ""))
                continue
            kept.append(asset)
        future_batches[phase] = kept
    return [name for name in removed if name]


def _apply_runtime_layout_constraint(asset: Dict[str, Any], text: str) -> bool:
    """Apply cheap user-visible layout constraints to a not-yet-imported asset."""
    if not text:
        return False
    pos = asset.get("pos")
    if not isinstance(pos, list) or len(pos) < 3:
        return False
    try:
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
    except Exception:
        return False

    before = (round(x, 4), round(y, 4), round(z, 4))
    name = str(asset.get("name") or "")

    lower = text.lower()

    if any(k in lower for k in ("中央活动区", "中间活动区", "中央留空", "中间留空", "不要挡住中间", "别挡中间", "central", "center clear", "middle clear")):
        radius = max((x * x + z * z) ** 0.5, 2.4)
        if abs(x) + abs(z) < 0.6:
            seed = sum(ord(ch) for ch in name) or 1
            # Four deterministic quadrants, no scene-specific branching.
            quadrant = seed % 4
            signs = ((1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0))[quadrant]
            x = signs[0] * radius
            z = signs[1] * radius
        else:
            scale = radius / max(0.001, (x * x + z * z) ** 0.5)
            x *= scale
            z *= scale

    if any(k in lower for k in ("靠墙", "贴墙", "沿墙", "侧墙", "against wall", "near wall", "by wall")):
        wall_offset = 2.2
        if abs(x) >= abs(z):
            x = (1.0 if x >= 0.0 else -1.0) * max(abs(x), wall_offset)
        else:
            z = (1.0 if z >= 0.0 else -1.0) * max(abs(z), wall_offset)
        if abs(x) + abs(z) < 0.6:
            x = wall_offset

    if any(k in lower for k in ("不要挡入口", "别挡入口", "不要挡门", "别挡门", "门口留空", "入口留空", "entrance clear", "do not block entrance", "do not block door")):
        if abs(x) < 1.2 and z > -0.5:
            x = 1.8 if (sum(ord(ch) for ch in name) % 2 == 0) else -1.8
            z = min(z, -0.8)

    if ("喷泉" in name or "fountain" in name.lower()) and any(k in lower for k in ("轴线", "外广场", "教堂外", "广场前", "前场", "axis", "outside", "forecourt")):
        x = 0.0
        direction = 1.0 if z >= 0.0 else -1.0
        z = direction * max(abs(z), 4.0)

    after = (round(x, 4), round(y, 4), round(z, 4))
    if after == before:
        return False
    asset["pos"] = [round(x, 4), round(y, 4), round(z, 4)]
    return True


def _generate_post_shell_framework(composer: Any) -> None:
    """Generate framework pieces that depend on measured shell placement.

    The original workflow runs these after _place_shells(). Progressive compose
    must keep the same anchor chain, otherwise shell interiors and opt-in
    boundary aspects disappear from the default F5 path.
    """
    zone_tree = getattr(composer, "zone_tree", None)
    if zone_tree is None or getattr(zone_tree, "root", None) is None:
        return
    try:
        from .scene_composer import _aspect_params, _has_aspect, resolve_zone_anchor

        for zone in zone_tree.list_all_zones():
            if (getattr(zone, "enclosure", "") or "") == "shell":
                composer._generate_interior_floor(zone)
                composer._generate_foundation_surface(zone)

        boundary_zone = next(
            (zone for zone in zone_tree.list_all_zones() if _has_aspect(zone, "boundary")),
            None,
        )
        if boundary_zone is None:
            return
        boundary_params = _aspect_params(boundary_zone, "boundary")
        boundary_anchor = resolve_zone_anchor(
            composer,
            boundary_zone,
            "boundary",
            params=boundary_params,
        )
        composer._generate_fence(boundary_params, anchor=boundary_anchor)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProgressiveWorkflow] post-shell framework skipped: %s", exc)


def _run_vlm_advisory_review(imported: List[str], engine_gate: Any) -> Any:
    """Run the optional VLM outer loop; failures are advisory-only."""
    try:
        from .model_reviewer import _capture_single_model, _vlm_review_model
        from .vlm_review_loop import review_models_async
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ProgressiveWorkflow] VLM 外回路不可用，跳过: %s", exc)
        return None

    max_targets = _vlm_max_targets()
    targets = [
        {"actor_id": actor_id, "model_name": actor_id, "model_type": actor_id}
        for actor_id in imported[:max(0, max_targets)]
    ]
    if not targets:
        return None
    try:
        return review_models_async(
            targets,
            capture_fn=_capture_single_model,
            review_fn=_vlm_review_model,
            engine_gate=engine_gate,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProgressiveWorkflow] VLM 外回路异常，已跳过: %s", exc)
        return None


def _vlm_max_targets() -> int:
    """Return configured VLM advisory target count.

    F5 demo mode defaults to 0 so the main interaction demo is not slowed by
    screenshot/VLM work. Explicit PROGRESSIVE_VLM_MAX_TARGETS always wins.
    """
    default_targets = "0" if os.getenv("CORONA_F5_DEMO_MODE") and "PROGRESSIVE_VLM_MAX_TARGETS" not in os.environ else "4"
    try:
        return max(0, int(os.getenv("PROGRESSIVE_VLM_MAX_TARGETS", default_targets) or default_targets))
    except Exception:
        return int(default_targets)


def _serialize_operation_log(entries: List[Any]) -> List[Dict[str, Any]]:
    """把 OperationLogEntry 转成 compose() 可直接返回的普通 dict。"""
    out: List[Dict[str, Any]] = []
    for entry in entries:
        out.append({
            "op_id": getattr(entry, "op_id", None),
            "round_id": getattr(entry, "round_id", None),
            "timestamp": getattr(entry, "timestamp", None),
            "source": getattr(entry, "source", None),
            "op_type": getattr(entry, "op_type", None),
            "actor_id": getattr(entry, "actor_id", None),
            "user_id": getattr(entry, "user_id", None),
            "before": getattr(entry, "before", None),
            "after": getattr(entry, "after", None),
            "intent_text": getattr(entry, "intent_text", None),
        })
    return out


def _capture_viewport_snapshot(composer: Any) -> Dict[str, Any]:
    """采集当前视口的 transform 快照（喂给 SceneDiffTracker）。"""
    try:
        from .scene_diff import make_transform
        scene = _get_current_scene()
        if scene is None:
            return {}
        snapshot = {}
        for actor in scene.get_actors():
            aid = _actor_name(actor)
            if not aid:
                continue
            pos = actor.get_position()
            rot = actor.get_rotation()
            scale = actor.get_scale()
            snapshot[aid] = make_transform(pos, rot, scale)
        return snapshot
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProgressiveWorkflow] 采集快照失败: %s", exc)
        return {}


def _get_current_scene() -> Any:
    """Return the active/default Corona scene using the public scene_manager API."""
    from CoronaCore.core.managers import scene_manager

    scene = scene_manager.get("")
    if scene is not None:
        return scene
    routes = scene_manager.list_all()
    return scene_manager.get(routes[0]) if routes else None


def _actor_name(actor: Any) -> str:
    getter = getattr(actor, "get_name", None)
    if callable(getter):
        try:
            return str(getter() or "")
        except Exception:
            pass
    return str(getattr(actor, "name", "") or "")


def _actor_aabb(actor: Any) -> Optional[List[float]]:
    getter = getattr(actor, "get_bounding_box", None)
    if callable(getter):
        bb = getter()
        return list(bb) if bb and len(bb) >= 6 else None
    try:
        from ..mcp.tools.transform_grounding import actor_world_aabb
        bb = actor_world_aabb(actor)
        return list(bb) if bb and len(bb) >= 6 else None
    except Exception:
        pass
    return None


def _scene_actor(scene: Any, actor_id: str) -> Any:
    getter = getattr(scene, "get_actor", None)
    if callable(getter):
        try:
            actor = getter(actor_id)
            if actor is not None:
                return actor
        except Exception:
            pass
    finder = getattr(scene, "find_actor", None)
    if callable(finder):
        try:
            return finder(actor_id)
        except Exception:
            return None
    return None


def _repair_recent_imports(
    imported_ids: List[str],
    scene_layout: Any,
    engine_gate: Any,
    *,
    zone_aabbs: Dict[str, List[float]],
    door_aabbs: Dict[str, List[float]],
    issue_sink: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """AABB hard loop after each imported batch: snap bottom and resolve overlaps."""

    if not imported_ids:
        return 0
    try:
        from ..mcp.tools.transform_grounding import resolve_actor_overlaps, snap_actor_to_ground
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ProgressiveWorkflow] AABB repair unavailable: %s", exc)
        return 0
    scene = _get_current_scene()
    if scene is None:
        return 0

    try:
        active_ids = {str(getattr(inst, "instance_id", "") or "") for inst in scene_layout.list_active()}
    except Exception:
        active_ids = set()

    repaired = 0
    for actor_id in imported_ids:
        actor = _scene_actor(scene, actor_id)
        if actor is None:
            continue
        try:
            inst = scene_layout.get(actor_id)
        except Exception:
            inst = None
        zone_id = str(getattr(inst, "zone_id", "") or "")
        zone_aabb = zone_aabbs.get(zone_id)

        def _apply() -> Dict[str, Any]:
            before = list(actor.get_position())
            snapped = snap_actor_to_ground(actor, ground_y=0.0, clearance=0.02)
            obstacles = []
            for other_id in active_ids:
                if other_id == actor_id:
                    continue
                other = _scene_actor(scene, other_id)
                if other is not None:
                    obstacles.append(other)
            overlap = resolve_actor_overlaps(
                actor,
                obstacles,
                extra_obstacle_aabbs=door_aabbs.values(),
                zone_aabb=zone_aabb,
                max_iterations=32,
            )
            after = list(actor.get_position())
            return {
                "changed": before != after,
                "snapped": snapped is not None,
                "overlap": overlap,
                "position": after,
            }

        try:
            result = engine_gate.run(_apply) if engine_gate is not None else _apply()
            if result.get("changed"):
                repaired += 1
                if inst is not None:
                    transform = getattr(inst, "transform", None)
                    if not isinstance(transform, dict):
                        transform = {}
                        inst.transform = transform
                    transform["pos"] = list(result.get("position") or actor.get_position())
                logger.info("[ProgressiveWorkflow] AABB repair %s -> %s", actor_id, result.get("position"))
            overlap = result.get("overlap") or {}
            if overlap and not overlap.get("resolved", True):
                logger.warning(
                    "[ProgressiveWorkflow] AABB unresolved %s reason=%s remaining=%s",
                    actor_id,
                    overlap.get("reason") or "overlap",
                    overlap.get("remaining_overlap") or [],
                )
                if issue_sink is not None:
                    issue_sink.append({
                        "kind": "aabb_repair",
                        "text": f"{actor_id} 仍有重叠或摆放冲突",
                        "source": "AABB",
                        "status": "needs_confirm",
                        "actor_id": actor_id,
                        "reason": overlap.get("reason") or "overlap",
                        "remaining_overlap": list(overlap.get("remaining_overlap") or []),
                    })
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ProgressiveWorkflow] AABB repair skipped for %s: %s", actor_id, exc)
    return repaired


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
        role = _infer_layout_role(asset)
        asset.setdefault("layout_role", role)
        # 简单分类（可扩展为查 placement_type）
        if any(kw in name for kw in ["地毯", "rug", "floor", "桌", "table", "椅", "chair", "床", "bed"]):
            if _is_surface_asset(asset):
                asset["layout_role"] = "surface"
            else:
                asset.setdefault("layout_role", "furniture")
            if indoor_zone_id:
                asset.setdefault("zone_id", indoor_zone_id)
            if shell_zone_id:
                asset.setdefault("anchor_ref", shell_zone_id)
            phase_map["INTERIOR"].append(asset)
        elif any(kw in name for kw in ["栅栏", "fence", "boundary", "围栏"]):
            asset.setdefault("layout_role", "boundary")
            if outdoor_zone_id:
                asset.setdefault("zone_id", outdoor_zone_id)
            phase_map["BOUNDARY"].append(asset)
        elif any(kw in name for kw in [
            "篝火", "火堆", "campfire", "bonfire", "木柴", "log", "horse", "马",
            "喷泉", "fountain", "雕像", "statue", "天使", "angel", "长椅", "bench",
            "广场", "plaza", "路灯", "streetlight", "树", "tree", "摊", "stall",
        ]):
            if outdoor_zone_id:
                asset.setdefault("zone_id", outdoor_zone_id)
            phase_map["OBJECTS"].append(asset)
        elif any(kw in name for kw in ["灯", "lamp", "light", "装饰", "deco"]):
            asset.setdefault("layout_role", "decoration")
            if indoor_zone_id:
                asset.setdefault("zone_id", indoor_zone_id)
            if shell_zone_id:
                asset.setdefault("anchor_ref", shell_zone_id)
            phase_map["DECORATION"].append(asset)
        else:
            # Mixed outdoor + shell scenes should not silently push unknown
            # plaza/camp props into the building. Known furniture above still
            # goes indoors; otherwise prefer the outdoor parent when present.
            if outdoor_zone_id and shell_zone_id:
                asset.setdefault("zone_id", outdoor_zone_id)
            elif indoor_zone_id:
                asset.setdefault("zone_id", indoor_zone_id)
            phase_map["OBJECTS"].append(asset)

    _assign_default_progressive_positions(phase_map, composer)
    return phase_map


def _assign_default_progressive_positions(phase_map: Dict[str, List[Dict[str, Any]]],
                                          composer: Any) -> None:
    """Assign conservative non-overlapping positions when no layout pos exists.

    Progressive import intentionally bypasses the old clear-scene compose/import
    path, so assets can arrive without LLM layout geometry. A small deterministic
    first-pass layout is better than importing everything at the origin; AABB/VLM
    can then review from a sane initial state.
    """
    zones = _zone_lookup(composer)
    counters: Dict[str, int] = {}
    indoor_states: Dict[str, Dict[str, Any]] = {}
    for phase, assets in phase_map.items():
        for asset in assets:
            if asset.get("pos") is not None:
                continue
            zone_id = str(asset.get("zone_id") or "")
            idx = counters.get(zone_id or phase, 0)
            counters[zone_id or phase] = idx + 1
            zone = zones.get(zone_id)
            if _is_outdoor_zone(zone):
                asset["pos"] = _outdoor_default_pos(asset, idx, zone, composer)
                asset.setdefault("scale", _outdoor_default_scale(asset, zone, composer))
            else:
                state_key = zone_id or "__default_indoor__"
                state = indoor_states.setdefault(state_key, {})
                asset["pos"] = _indoor_default_pos(asset, idx, zone, state)


def _zone_lookup(composer: Any) -> Dict[str, Any]:
    tree = getattr(composer, "zone_tree", None)
    if tree is None or getattr(tree, "root", None) is None:
        return {}
    return {str(getattr(zone, "zone_id", "")): zone for zone in tree.list_all_zones()}


def _is_outdoor_zone(zone: Any) -> bool:
    if zone is None:
        return False
    return (
        (str(getattr(zone, "role", "") or "").lower() == "outdoor")
        or (str(getattr(zone, "enclosure", "") or "").lower() == "terrain")
    )


def _indoor_default_pos(
    asset: Dict[str, Any],
    index: int,
    zone: Any,
    state: Optional[Dict[str, Any]] = None,
) -> List[float]:
    """Return a first-pass indoor slot for progressive import.

    The old fallback used a fixed seven-point pattern, which made beds,
    wardrobes, desks and rugs compete for the same central points. This planner
    stays scene-agnostic but uses asset semantics and room dimensions so AABB
    repair starts from a layout that is already plausible.
    """

    size = list(getattr(getattr(zone, "volume", None), "size", []) or [5.0, 5.0, 3.0])
    width = float(size[0] if len(size) > 0 else 5.0)
    depth = float(size[1] if len(size) > 1 else 5.0)
    half_x = max(1.0, width / 2.0)
    half_z = max(1.0, depth / 2.0)
    wall_x = max(0.35, half_x - 0.65)
    wall_z = max(0.35, half_z - 0.65)
    side_x = max(0.35, half_x - 0.8)
    side_z = max(0.0, min(wall_z * 0.45, half_z - 0.9))

    name = str(asset.get("name") or "").lower()
    role = str(asset.get("layout_role") or _infer_layout_role(asset)).lower()
    state = state if isinstance(state, dict) else {}
    anchors = state.setdefault("anchors", {})
    counts = state.setdefault("counts", {})

    def _reserve(slot: str, pos: List[float]) -> List[float]:
        count = int(counts.get(slot, 0) or 0)
        counts[slot] = count + 1
        if count:
            step = 0.42 * count
            pos = [
                max(-half_x + 0.35, min(half_x - 0.35, pos[0] + ((-1) ** count) * step)),
                pos[1],
                max(-half_z + 0.35, min(half_z - 0.35, pos[2] - step * 0.35)),
            ]
        return [round(float(pos[0]), 3), 0.0, round(float(pos[2]), 3)]

    if role == "surface" or _is_surface_asset(asset):
        anchors["surface"] = [0.0, 0.0, 0.0]
        return _reserve("surface", [0.0, 0.0, 0.0])

    if any(kw in name for kw in ("床", "bed", "crib")):
        pos = [0.0, 0.0, -wall_z]
        anchors["bed"] = pos
        return _reserve("bed", pos)

    if any(kw in name for kw in ("书桌", "desk", "writing table", "study table")):
        pos = [-side_x, 0.0, side_z]
        anchors["desk"] = pos
        return _reserve("desk", pos)

    if any(kw in name for kw in ("椅", "chair", "stool")):
        desk = anchors.get("desk")
        if desk:
            return _reserve("chair", [desk[0] + 0.75, 0.0, desk[2] - 0.35])
        return _reserve("chair", [-side_x + 0.65, 0.0, side_z])

    if any(kw in name for kw in ("台灯", "lamp", "desk light", "light")):
        desk = anchors.get("desk")
        if desk:
            return _reserve("lamp", [desk[0] + 0.25, 0.0, desk[2] + 0.2])
        bed = anchors.get("bed")
        if bed:
            return _reserve("lamp", [bed[0] + min(1.0, half_x - 0.7), 0.0, bed[2] + 0.35])
        return _reserve("lamp", [0.0, 0.0, side_z])

    if any(kw in name for kw in ("衣柜", "wardrobe", "closet")):
        return _reserve("wardrobe", [wall_x, 0.0, -wall_z * 0.25])

    if any(kw in name for kw in ("书架", "bookshelf", "bookcase", "shelf")):
        return _reserve("bookshelf", [-wall_x, 0.0, -wall_z * 0.25])

    if any(kw in name for kw in ("玩具柜", "toy cabinet", "toy storage", "柜", "cabinet")):
        return _reserve("cabinet", [wall_x, 0.0, side_z])

    if any(kw in name for kw in ("桌", "table")):
        pos = [-side_x, 0.0, side_z]
        anchors.setdefault("desk", pos)
        return _reserve("table", pos)

    margin_x = max(0.4, min(width / 2.0 - 0.4, 1.0))
    margin_z = max(0.4, min(depth / 2.0 - 0.4, 1.0))
    pattern = [
        [0.0, 0.0, 0.0],
        [-margin_x, 0.0, margin_z],
        [margin_x, 0.0, margin_z],
        [-margin_x, 0.0, -margin_z],
        [margin_x, 0.0, -margin_z],
        [0.0, 0.0, margin_z * 1.4],
        [0.0, 0.0, -margin_z * 1.4],
    ]
    if index < len(pattern):
        return pattern[index]
    row = index - len(pattern)
    x = ((row % 3) - 1) * margin_x
    z = (1.8 + row // 3) * margin_z
    return [x, 0.0, min(depth / 2.0 - 0.5, z)]


def _is_surface_asset(asset: Dict[str, Any]) -> bool:
    name = str(asset.get("name") or "").lower()
    role = str(asset.get("layout_role") or "").lower()
    return role == "surface" or any(
        kw in name for kw in ("地毯", "rug", "carpet", "floor mat", "mat")
    )


def _infer_layout_role(asset: Dict[str, Any]) -> str:
    explicit = str(asset.get("layout_role") or "").strip().lower()
    if explicit:
        return explicit
    name = str(asset.get("name") or "").lower()
    if any(kw in name for kw in ("fountain", "喷泉", "statue", "雕像", "angel", "天使")):
        return "landmark"
    if any(kw in name for kw in ("地毯", "rug", "carpet", "floor mat", "mat")):
        return "surface"
    if any(kw in name for kw in ("bench", "长椅", "streetlight", "路灯", "stall", "摊")):
        return "foreground_object"
    if any(kw in name for kw in ("fence", "boundary", "围栏", "栅栏")):
        return "boundary"
    if any(kw in name for kw in ("grass", "flower", "rocks", "shrub", "草", "花", "岩石", "灌木")):
        return "ground_cover"
    if any(kw in name for kw in ("table", "chair", "bed", "desk", "桌", "椅", "床")):
        return "furniture"
    return "decoration"


def _scene_scale_context(composer: Any, zone: Any) -> Dict[str, float]:
    shell_r = _measured_shell_radius(composer)
    aabbs = getattr(composer, "_shell_aabb", {}) or {}
    building_width = shell_r * 2.0 if shell_r > 0.0 else 0.0
    building_depth = building_width
    building_height = 0.0
    for item in aabbs.values():
        if isinstance(item, dict):
            building_width = max(building_width, float(item.get("half_x", 0.0) or 0.0) * 2.0)
            building_depth = max(building_depth, float(item.get("half_z", 0.0) or 0.0) * 2.0)
            building_height = max(building_height, float(item.get("height", 0.0) or 0.0))
    if building_height <= 0.0 and building_width > 0.0:
        building_height = building_width * 0.75

    size = list(getattr(getattr(zone, "volume", None), "size", []) or [20.0, 20.0, 0.0])
    terrain_extent = max(
        float(size[0] if len(size) > 0 else 20.0),
        float(size[1] if len(size) > 1 else 20.0),
        float((getattr(composer, "_terrain_extent", {}) or {}).get("extent", 0.0) or 0.0),
    )
    foundation = getattr(composer, "_foundation_extent", {}) or {}
    foundation_extent = max(
        float(foundation.get("width", 0.0) or 0.0),
        float(foundation.get("depth", 0.0) or 0.0),
        building_width,
        building_depth,
    )
    return {
        "building_width": building_width,
        "building_depth": building_depth,
        "building_height": building_height,
        "building_radius": max(building_width, building_depth) / 2.0,
        "terrain_extent": terrain_extent,
        "foundation_extent": foundation_extent,
    }


def _scale_triplet(value: float) -> List[float]:
    v = round(max(0.2, float(value or 1.0)), 3)
    return [v, v, v]


def _outdoor_default_scale(asset: Dict[str, Any], zone: Any, composer: Any) -> List[float]:
    if asset.get("scale") is not None:
        scale = asset.get("scale")
        return list(scale) if isinstance(scale, (list, tuple)) else _scale_triplet(float(scale))
    ctx = _scene_scale_context(composer, zone)
    name = str(asset.get("name") or "").lower()
    role = str(asset.get("layout_role") or "").lower()
    width = max(1.0, ctx.get("building_width", 0.0) or ctx.get("terrain_extent", 20.0) * 0.25)
    height = max(width * 0.75, ctx.get("building_height", 0.0) or 0.0)
    if "fountain" in name or "喷泉" in name:
        return _scale_triplet(max(1.15, min(1.9, width / 5.0)))
    if "statue" in name or "雕像" in name or "angel" in name or "天使" in name:
        return _scale_triplet(max(1.25, min(2.0, height / 3.8)))
    if role == "foreground_object":
        return _scale_triplet(max(0.85, min(1.25, height / 8.0)))
    if role == "decoration":
        return _scale_triplet(max(0.65, min(1.05, height / 10.0)))
    return _scale_triplet(1.0)


def _outdoor_default_pos(asset: Dict[str, Any], index: int, zone: Any, composer: Any) -> List[float]:
    size = list(getattr(getattr(zone, "volume", None), "size", []) or [20.0, 20.0, 0.0])
    width = float(size[0] if len(size) > 0 else 20.0)
    depth = float(size[1] if len(size) > 1 else 20.0)
    half_limit = max(2.0, min(width, depth) / 2.0 - 1.5)
    ctx = _scene_scale_context(composer, zone)
    shell_r = float(ctx.get("building_radius", 0.0) or _measured_shell_radius(composer))
    foundation_r = float(ctx.get("foundation_extent", 0.0) or 0.0) / 2.0
    activity_r = max(shell_r + 2.0, foundation_r + 1.2, min(width, depth) * 0.22, 3.5)
    radius = min(half_limit, activity_r)
    name = str(asset.get("name") or "").lower()
    if "fountain" in name or "喷泉" in name:
        return [0.0, 0.0, radius]
    if "statue" in name or "雕像" in name or "angel" in name or "天使" in name:
        return [-radius * 0.65, 0.0, radius * 0.45]
    angles = [0.0, 0.75, -0.75, 1.6, -1.6, 2.35, -2.35, 3.14]
    angle = angles[index % len(angles)]
    import math
    return [
        round(math.sin(angle) * radius, 3),
        0.0,
        round(math.cos(angle) * radius, 3),
    ]


def _measured_shell_radius(composer: Any) -> float:
    aabbs = getattr(composer, "_shell_aabb", {}) or {}
    radii = []
    for item in aabbs.values():
        if isinstance(item, dict):
            radii.append(max(float(item.get("half_x", 0.0) or 0.0),
                            float(item.get("half_z", 0.0) or 0.0)))
    return max(radii) if radii else 0.0


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
        scene = _get_current_scene()
        if scene is None:
            return {}
        aabbs = {}
        for inst in scene_layout.list_active():
            actor = scene.get_actor(inst.instance_id)
            if actor is None:
                continue
            bb = _actor_aabb(actor)
            if bb and len(bb) >= 6:
                aabbs[inst.instance_id] = list(bb)
        return aabbs
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProgressiveWorkflow] 采集 AABB 失败: %s", exc)
        return {}


__all__ = ["run_progressive_workflow"]
