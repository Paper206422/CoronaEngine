"""离线自验：SceneSession 渐进主循环 + FinalReview 三分桶（突击方案 §2.1 / §2.5）。

注入假 SceneLayout + 假 protection_fn，不依赖引擎。验收：
- progressive_compose 按 PHASE_ORDER 跑、跳过未提供的 phase
- 介入随时入队、phase 边界 drain 落账（打 USER + 当前轮次）
- settle 只碰本批 AGENT
- FinalReview 三分桶：HARD/近因→preserved，AGENT不合理→adjusted，早期不合理用户→needs_confirm
- 生成中拖动的物体不被后续 settle 覆盖（功能①核心保证）

直接 `python test_scene_session.py` 运行。
"""
import sys
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(__file__))
from scene_session import (  # noqa: E402
    SceneSession,
    FinalReviewReport,
    InterventionOp,
    PHASE_ORDER,
    OP_MOVE,
    OP_DELETE,
)


# ── 假实现 ───────────────────────────────────────────────

@dataclass
class FakeInst:
    instance_id: str
    provenance: str = "AGENT"
    batch_id: Optional[str] = None
    intervention_round: int = -1
    touched_by_user: bool = False
    lock_level: str = "NONE"
    layout_status: str = "active"
    metadata: Dict[str, Any] = field(default_factory=dict)


class FakeLayout:
    def __init__(self):
        self._inst: Dict[str, FakeInst] = {}

    def add(self, inst):
        self._inst[inst.instance_id] = inst

    def get(self, iid):
        return self._inst.get(iid)

    def list_active(self):
        return [i for i in self._inst.values() if i.layout_status == "active"]

    def mark_user_intervention(self, iid, current_round, lock_level="HARD"):
        inst = self._inst.get(iid)
        if inst is None:
            # 用户新增：创建一个 USER 实例
            inst = FakeInst(iid, provenance="USER")
            self._inst[iid] = inst
        inst.provenance = "USER"
        inst.touched_by_user = True
        inst.intervention_round = current_round
        inst.lock_level = lock_level

    def list_settleable(self, batch_id, current_round, reasonable_map=None):
        reasonable_map = reasonable_map or {}
        out = []
        for inst in self._inst.values():
            if inst.layout_status != "active":
                continue
            # 复刻 protection 逻辑：最近 1 轮介入 → HARD，绝不 settle
            r = inst.intervention_round
            is_hard = (r is not None and r >= 0 and r >= current_round - 1)
            if is_hard:
                continue
            if inst.provenance == "AGENT" and inst.batch_id == batch_id:
                out.append(inst)
        return out


def _fake_protection(inst, current_round, reasonable):
    r = getattr(inst, "intervention_round", -1)
    if r is None or r < 0:
        return "NONE"
    if r >= current_round - 1:
        return "HARD"
    return "SOFT" if reasonable else "NONE"


# ── 测试 ─────────────────────────────────────────────────

def test_phase_loop_runs_provided_only():
    layout = FakeLayout()
    session = SceneSession(layout)
    ran = []

    def gen_ground(s, phase):
        ran.append(phase)
        return [{"name": "terrain", "path": "/m/t.glb"}]

    def gen_objects(s, phase):
        ran.append(phase)
        return [{"name": "table", "path": "/m/tb.glb"}]

    imported_ids = []

    def importer(assets, batch_id):
        # 模拟导入：往 layout 加 AGENT 实例
        for a in assets:
            layout.add(FakeInst(a["name"], provenance="AGENT", batch_id=batch_id))
            imported_ids.append(a["name"])
        return {"imported": [a["name"] for a in assets]}

    result = session.progressive_compose(
        {"GROUND": gen_ground, "OBJECTS": gen_objects},
        importer=importer,
        skip_final_review=True,  # 有专门的独立测试覆盖 final_review
    )
    # 只跑提供的 phase，且按 PHASE_ORDER 顺序（GROUND 在 OBJECTS 前）
    assert ran == ["GROUND", "OBJECTS"], f"应按序只跑提供的 phase，实际 {ran}"
    assert result["phases_run"] == ["GROUND", "OBJECTS"]
    assert set(result["imported"]) == {"terrain", "table"}
    print("[OK] progressive_compose 按 PHASE_ORDER 跑、跳过未提供的 phase")


def test_progress_sink_and_report_text_are_observable():
    layout = FakeLayout()
    session = SceneSession(layout)
    progress_events: List[str] = []
    progress_structured: List[Dict[str, Any]] = []
    session.set_progress_sink(progress_events.append)
    session.set_progress_event_sink(progress_structured.append)

    def gen_objects(s, phase):
        return [{"name": "table", "path": "/m/tb.glb"}]

    def importer(assets, batch_id):
        for a in assets:
            layout.add(FakeInst(a["name"], provenance="AGENT", batch_id=batch_id))
        return {"imported": [a["name"] for a in assets]}

    result = session.progressive_compose(
        {"OBJECTS": gen_objects},
        importer=importer,
        phase_metadata={
            "OBJECTS": {
                "batch_index": 1,
                "batch_total": 1,
                "prompt": "PRIVATE_PROGRESS_PROMPT_SHOULD_NOT_LEAK",
                "provider": "progress-provider-secret",
                "job_id": "progress-job-secret",
                "session_id": "progress-session-secret",
                "runtime_context": {"token": "progress-token-secret"},
                "scheduler_updates": [{"prompt": "nested-progress-secret"}],
                "hidden_debug_ref": "progress-debug-secret",
            }
        },
        reasonable_provider=lambda: {"table": True},
        skip_final_review=True,
    )
    report = session.final_review({"table": True}, protection_fn=_fake_protection)
    assert progress_events, "渐进进度必须能被上层收集，而不是只写日志"
    assert any("生成进度" in msg and "[" in msg and "]" in msg for msg in progress_events), progress_events
    assert any("1/1 个物件" in msg for msg in progress_events), progress_events
    assert not any("OBJECTS" in msg or "batch" in msg or "prompt" in msg for msg in progress_events), progress_events
    assert result["phases_run"] == ["OBJECTS"]
    timeline = result["progress_timeline"]
    assert timeline[0]["status"] == "start"
    assert timeline[0]["percent"] == 0
    assert timeline[-1]["status"] == "done"
    assert timeline[-1]["percent"] == 100
    assert timeline[-1]["asset_count"] == 1
    assert "user_message" in timeline[-1]
    assert progress_structured, "结构化进度事件必须能被 Coordinator 收集"
    assert progress_structured[-1]["status"] == "done"
    assert progress_structured[-1]["phase"] == "OBJECTS"
    assert progress_structured[-1]["percent"] == 100
    assert progress_structured[-1]["user_message"] == timeline[-1]["user_message"]
    exposed_structured = repr(progress_structured) + repr(timeline)
    assert "PRIVATE_PROGRESS_PROMPT_SHOULD_NOT_LEAK" not in exposed_structured
    assert "progress-provider-secret" not in exposed_structured
    assert "progress-job-secret" not in exposed_structured
    assert "progress-session-secret" not in exposed_structured
    assert "progress-token-secret" not in exposed_structured
    assert "nested-progress-secret" not in exposed_structured
    assert "progress-debug-secret" not in exposed_structured
    assert "场景已就绪" in report.to_user_text()
    print("[OK] 字符串进度 + 结构化进度 + progress_timeline + FinalReview 文案可被上层观测")


def test_progressive_compose_exposes_batch_resource_status():
    layout = FakeLayout()
    session = SceneSession(layout)
    progress_events: List[str] = []
    progress_structured: List[Dict[str, Any]] = []
    session.set_progress_sink(progress_events.append)
    session.set_progress_event_sink(progress_structured.append)

    def gen_objects(s, phase):
        s.pending_tasks.append({
            "kind": "batch_resource_plan",
            "status": "completed",
            "resolved_assets": ["天使雕像"],
            "batch_resource_plan": {
                "requested_items": [{"item_name": "天使雕像"}],
            },
        })
        return [{"name": "天使雕像", "path": "/m/angel.glb"}]

    def importer(assets, batch_id):
        for a in assets:
            layout.add(FakeInst(a["name"], provenance="AGENT", batch_id=batch_id))
        return {"imported": [a["name"] for a in assets]}

    result = session.progressive_compose(
        {"OBJECTS": gen_objects},
        importer=importer,
        phase_metadata={"OBJECTS": {"batch_index": 1, "batch_total": 1}},
        reasonable_provider=lambda: {"天使雕像": True},
        skip_final_review=True,
    )

    assert result["progress_timeline"][-1]["resource_plans"]
    assert "资源准备：新增请求 1 个" in progress_events[-1]
    assert "模型 1/1" in progress_events[-1]
    assert "导入 1/1" in progress_events[-1]
    assert progress_structured[-1]["resource_plans"][0]["status"] == "completed"
    print("[OK] progressive_compose exposes batch resource status in user-facing progress")


def test_progressive_compose_pauses_at_micro_batch_boundary():
    layout = FakeLayout()
    session = SceneSession(layout)
    progress_events: List[str] = []
    session.set_progress_sink(progress_events.append)
    calls = {"mode": 0}

    def gen_objects(s, phase):
        return [{"name": phase, "path": f"/m/{phase}.glb"}]

    def importer(assets, batch_id):
        for a in assets:
            layout.add(FakeInst(a["name"], provenance="AGENT", batch_id=batch_id))
        return {"imported": [a["name"] for a in assets]}

    def runtime_mode():
        calls["mode"] += 1
        return "EXECUTING" if calls["mode"] == 1 else "PAUSED"

    result = session.progressive_compose(
        {"OBJECTS#1": gen_objects, "OBJECTS#2": gen_objects},
        importer=importer,
        phase_sequence=["OBJECTS#1", "OBJECTS#2"],
        phase_metadata={
            "OBJECTS#1": {"batch_index": 1, "batch_total": 2, "asset_count": 1, "total_assets": 2},
            "OBJECTS#2": {"batch_index": 2, "batch_total": 2, "asset_count": 1, "total_assets": 2},
        },
        runtime_mode_provider=runtime_mode,
        skip_final_review=False,
    )
    assert result["phases_run"] == ["OBJECTS#1"]
    assert result["imported"] == ["OBJECTS#1"]
    assert result["paused"] is True
    assert result["paused_mode"] == "PAUSED"
    assert result["paused_before_phase"] == "OBJECTS#2"
    assert result["final_report"] is None, "暂停时不应跑最终审查假装完成"
    assert any("等待 @GM 继续" in msg for msg in progress_events), progress_events
    print("[OK] progressive_compose 在 micro-batch 边界响应 PAUSED 并返回可恢复状态")


def test_intervention_drain_marks_user():
    layout = FakeLayout()
    layout.add(FakeInst("sofa", provenance="AGENT", batch_id="r1_GROUND"))
    session = SceneSession(layout)
    session.current_round = 3

    session.enqueue_intervention(InterventionOp("sofa", OP_MOVE, source="viewport"))
    n = session.drain_interventions()
    assert n == 1
    inst = layout.get("sofa")
    assert inst.provenance == "USER", "拖动后应转 USER"
    assert inst.touched_by_user is True
    assert inst.intervention_round == 3, "应记当前轮次（近因加权）"
    print("[OK] 介入入队 + phase 边界 drain 落账（打 USER + 轮次）")


def test_post_import_hook_runs_before_final_review():
    layout = FakeLayout()
    session = SceneSession(layout)
    repaired: List[tuple] = []

    def gen_objects(s, phase):
        return [{"name": "chair", "path": "/m/chair.glb"}]

    def importer(assets, batch_id):
        for a in assets:
            layout.add(FakeInst(a["name"], provenance="AGENT", batch_id=batch_id))
        return {"imported": [a["name"] for a in assets]}

    def post_import_hook(imported_ids, batch_id):
        repaired.append((tuple(imported_ids), batch_id))

    session.progressive_compose(
        {"OBJECTS": gen_objects},
        importer=importer,
        post_import_hook=post_import_hook,
        skip_final_review=True,
    )
    assert repaired == [(("chair",), "r1_OBJECTS")]
    print("[OK] phase 导入后会触发 post_import_hook（AABB repair 接线点）")


def test_delete_marks_stale_not_physical():
    layout = FakeLayout()
    layout.add(FakeInst("lamp", provenance="AGENT"))
    session = SceneSession(layout)
    session.current_round = 2
    session.enqueue_intervention(InterventionOp("lamp", OP_DELETE, source="viewport"))
    session.drain_interventions()
    inst = layout.get("lamp")
    assert inst is not None, "删除应标 stale 不物理删（可恢复）"
    assert inst.layout_status == "stale"
    print("[OK] 删除标 stale 不物理删")


def test_settle_skips_recent_user():
    layout = FakeLayout()
    # 本批 AGENT → 可 settle
    layout.add(FakeInst("agent_cur", provenance="AGENT", batch_id="r5_OBJECTS"))
    # 用户最近介入 → 绝不 settle
    layout.add(FakeInst("user_recent", provenance="USER",
                        batch_id="r5_OBJECTS", intervention_round=5))
    session = SceneSession(layout)
    session.current_round = 5
    settled = session.settle_current_batch("r5_OBJECTS")
    assert "agent_cur" in settled
    assert "user_recent" not in settled, "最近用户介入绝不被 settle 覆盖（功能①核心）"
    print("[OK] settle 只碰本批 AGENT，跳过最近用户介入")


def test_final_review_three_buckets():
    layout = FakeLayout()
    session = SceneSession(layout)
    session.current_round = 5
    # HARD 近因用户物体 → preserved
    layout.add(FakeInst("u_recent", provenance="USER", intervention_round=5))
    # 早期合理用户物体 → preserved（SOFT）
    layout.add(FakeInst("u_early_ok", provenance="USER", intervention_round=1))
    # 早期不合理用户物体 → needs_confirm
    layout.add(FakeInst("u_early_bad", provenance="USER", intervention_round=1))
    # AGENT 不合理 → adjusted
    layout.add(FakeInst("agent_bad", provenance="AGENT"))
    # AGENT 合理 → 不动
    layout.add(FakeInst("agent_ok", provenance="AGENT"))

    rmap = {"u_early_ok": True, "u_early_bad": False,
            "agent_bad": False, "agent_ok": True}
    report = session.final_review(rmap, protection_fn=_fake_protection)

    assert "u_recent" in report.preserved, "近因用户物体应 preserved"
    assert "u_early_ok" in report.preserved, "早期合理用户物体应 preserved"
    assert any(nc["actor_id"] == "u_early_bad" for nc in report.needs_confirm), \
        "早期不合理用户物体应 needs_confirm"
    assert "agent_bad" in report.adjusted, "不合理 AGENT 应 adjusted"
    assert "agent_ok" not in report.adjusted, "合理 AGENT 不动"
    # 报告文案可生成
    text = report.to_user_text()
    assert "保留" in text and "确认" in text
    print("[OK] FinalReview 三分桶 + 报告文案")


def test_final_adjustment_plan_is_consumed_by_final_review():
    layout = FakeLayout()
    session = SceneSession(layout)
    layout.add(FakeInst("agent_ok", provenance="AGENT"))
    statue = FakeInst("actor-statue", provenance="AGENT")
    statue.transform = {
        "pos": [1.0, -0.25, 2.0],
        "rot": [0.0, 0.0, 0.0],
        "scale": [2.0, 2.0, 2.0],
    }
    layout.add(statue)
    lamp = FakeInst("actor-lamp", provenance="AGENT")
    lamp.transform = {
        "pos": [2.0, 0.0, 3.0],
        "rot": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }
    layout.add(lamp)
    conflicted = FakeInst("actor-conflict", provenance="AGENT")
    conflicted.transform = {
        "pos": [0.0, 0.0, 0.0],
        "rot": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }
    layout.add(conflicted)

    adjustment = {
        "selected": [
            {
                "intervention_id": "iv-late",
                "content": "最后收尾时把中心雕塑缩小并贴地",
                "actor_id": "actor-statue",
                "apply_policy": "final_adjustment",
                "score": 120,
            },
            {
                "intervention_id": "iv-conflict",
                "content": "删除这个冲突物体",
                "actor_id": "actor-conflict",
                "apply_policy": "final_adjustment",
                "score": 115,
            },
            {
                "intervention_id": "iv-vlm",
                "content": "朝向不符合用户意图，请缩小一点",
                "actor_id": "actor-lamp",
                "apply_policy": "final_adjustment",
                "score": 110,
                "finding_details": [{
                    "action": "apply_vlm_advice",
                    "position_correction": [2.5, 0.0, 3.5],
                    "rotation_correction": [0.0, 90.0, 0.0],
                    "scale_correction": [0.8, 0.8, 0.8],
                    "fix_suggestion": "移到不穿模位置，旋转 90 度并缩小",
                }],
            }
        ],
        "deferred": [
            {
                "intervention_id": "iv-early",
                "content": "第一批旁边加一个很小的摊位",
                "defer_reason": "early_low_priority_request_superseded_by_later_batches",
            }
        ],
        "conflicts": [
            {
                "actor_id": "actor-conflict",
                "reason": "same_actor_has_remove_and_keep_modify_requests",
            },
            {
                "actor_id": "",
                "target_hint": "入口摊位",
                "reason": "same_target_has_remove_and_keep_modify_requests",
            }
        ],
    }

    result = session.progressive_compose(
        {},
        reasonable_provider=lambda: {"agent_ok": True},
        final_adjustment_provider=lambda: adjustment,
        final_review_protection_fn=_fake_protection,
    )
    report = result["final_report"]

    assert result["final_adjustment_plan"] == adjustment
    assert report.final_adjustments[0]["intervention_id"] == "iv-late"
    assert report.deferred_interventions[0]["intervention_id"] == "iv-early"
    assert report.conflicts[0]["actor_id"] == "actor-conflict"
    assert statue.transform["pos"][1] == 0.0
    assert statue.transform["scale"] == [1.7, 1.7, 1.7]
    assert lamp.transform["pos"] == [2.5, 0.0, 3.5]
    assert lamp.transform["rot"] == [0.0, 90.0, 0.0]
    assert lamp.transform["scale"] == [0.8, 0.8, 0.8]
    assert conflicted.layout_status == "active", "冲突 actor 不应被静默删除"
    assert report.applied_final_adjustments[0]["actor_id"] == "actor-statue"
    assert report.applied_final_adjustments[0]["actions"] == ["scale_down", "ground_fit"]
    assert any(
        item["actor_id"] == "actor-lamp"
        and item["actions"] == [
            "apply_position_correction",
            "apply_rotation_correction",
            "apply_scale_correction",
        ]
        for item in report.applied_final_adjustments
    )
    assert any(entry.op_type == "FINAL_ADJUST" and entry.actor_id == "actor-statue"
               for entry in session.operation_log)
    text = report.to_user_text()
    assert "最终收尾会优先处理" in text
    assert "中心雕塑缩小" in text
    assert "仍待后续处理" in text
    assert "第一批旁边加一个很小的摊位" in text
    assert "已完成收尾调整" in text
    assert "GM/房主确认" in text
    assert "入口摊位" in text
    assert "同一目标同时存在删除与保留/修改要求" in text
    print("[OK] FinalReview consumes Coordinator final adjustment plan")


def test_final_review_reports_failed_resource_requests_to_user():
    layout = FakeLayout()
    session = SceneSession(layout)
    session.pending_tasks.append({
        "kind": "batch_resource_plan",
        "status": "model_provider_unavailable",
        "batch_resource_plan": {
            "requested_items": [
                {"item_name": "天使雕像", "original_text": "新增：再加一个天使雕像"}
            ],
        },
        "provider": "PRIVATE_PROVIDER_SHOULD_NOT_LEAK",
        "prompt": "PRIVATE_PROMPT_SHOULD_NOT_LEAK",
    })

    report = session.final_review({}, protection_fn=_fake_protection)
    text = report.to_user_text()

    assert report.deferred_interventions[-1]["status"] == "model_provider_unavailable"
    assert "仍待后续处理" in text
    assert "天使雕像" in text
    assert "模型生成服务暂不可用" in text
    assert "PRIVATE_PROVIDER_SHOULD_NOT_LEAK" not in text
    assert "PRIVATE_PROMPT_SHOULD_NOT_LEAK" not in text
    print("[OK] FinalReview reports failed resource requests without leaking internals")


def test_final_review_reports_scene_design_contract_without_leaking_prompt():
    layout = FakeLayout()
    session = SceneSession(layout)
    contract = {
        "version": 7,
        "scene_type": "fantasy_night_market",
        "environment_type": "outdoor",
        "mood": ["warm", "mysterious but friendly"],
        "style_keywords": ["fantasy", "market", "style consistency"],
        "avoid_keywords": ["too horror", "dark horror"],
        "palette": ["warm amber"],
        "lighting": ["coherent warm lights"],
        "terrain_spec": {
            "type": "outdoor_market_ground",
            "surface": "stone_path_with_soft_grass_edges",
            "debug": "TERRAIN_DEBUG_SHOULD_NOT_LEAK",
        },
        "boundary_spec": {
            "type": "low_decorative_boundary",
            "style": "vine_wood_lantern",
            "height": "low",
            "avoid": ["grassland yurt fence"],
            "prompt": "BOUNDARY_PROMPT_SHOULD_NOT_LEAK",
        },
        "scale_rules": ["天使雕像要足够大"],
        "placement_rules": ["keep clear visitor paths between entrance, stalls, lighting, and rest area"],
        "asset_style_prompt": "PRIVATE_STYLE_PROMPT_SHOULD_NOT_LEAK",
    }

    report = session.final_review({}, protection_fn=_fake_protection, scene_design_contract=contract)
    text = report.to_user_text()

    assert report.style_contract_summary["version"] == 7
    assert "风格收口" in text
    assert "warm" in text
    assert "fantasy" in text
    assert "已持续避开" in text
    assert "too horror" in text
    assert "组装约束" in text
    assert "low_decorative_boundary" in text
    assert "grassland yurt fence" in text
    assert "PRIVATE_STYLE_PROMPT_SHOULD_NOT_LEAK" not in text
    assert "BOUNDARY_PROMPT_SHOULD_NOT_LEAK" not in text
    assert "TERRAIN_DEBUG_SHOULD_NOT_LEAK" not in text
    print("[OK] FinalReview reports scene design contract without leaking prompts")


def test_resolved_final_adjustment_conflicts_are_consumed_by_final_review():
    layout = FakeLayout()
    session = SceneSession(layout)
    layout.add(FakeInst("actor-confirmed", provenance="AGENT"))
    layout.add(FakeInst("actor-rejected", provenance="AGENT"))

    adjustment = {
        "selected": [
            {
                "intervention_id": "iv-confirmed",
                "content": "房主确认后删除这个冲突物体",
                "actor_id": "actor-confirmed",
                "apply_policy": "final_adjustment",
                "score": 120,
            }
        ],
        "deferred": [
            {
                "intervention_id": "iv-rejected",
                "content": "房主拒绝删除这个冲突物体",
                "actor_id": "actor-rejected",
                "apply_policy": "final_adjustment",
                "defer_reason": "final_adjustment_conflict_rejected_by_host",
            }
        ],
        "conflicts": [],
        "resolved_conflicts": [
            {
                "actor_id": "actor-confirmed",
                "reason": "same_actor_has_remove_and_keep_modify_requests",
                "status": "confirmed",
            },
            {
                "actor_id": "actor-rejected",
                "reason": "same_actor_has_remove_and_keep_modify_requests",
                "status": "rejected",
            },
        ],
    }

    result = session.progressive_compose(
        {},
        reasonable_provider=lambda: {"actor-confirmed": True, "actor-rejected": True},
        final_adjustment_provider=lambda: adjustment,
        final_review_protection_fn=_fake_protection,
    )
    report = result["final_report"]

    assert layout.get("actor-confirmed").layout_status == "stale"
    assert layout.get("actor-rejected").layout_status == "active"
    assert report.conflicts == []
    assert report.resolved_conflicts[0]["status"] == "confirmed"
    assert report.resolved_conflicts[1]["status"] == "rejected"
    text = report.to_user_text()
    assert "GM/房主确认" not in text
    assert "已按房主决定跳过收尾冲突项" in text
    print("[OK] FinalReview consumes resolved final adjustment conflicts without re-blocking confirmed items")


def test_unresolved_target_hint_conflict_blocks_matching_final_adjustment():
    layout = FakeLayout()
    session = SceneSession(layout)
    stall = FakeInst("actor-stall-generated", provenance="AGENT")
    stall.transform = {
        "pos": [0.0, 0.0, 0.0],
        "rot": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }
    layout.add(stall)

    adjustment = {
        "selected": [
            {
                "intervention_id": "iv-target-hint",
                "content": "删除入口摊位",
                "actor_id": "actor-stall-generated",
                "target_hint": "入口摊位",
                "apply_policy": "final_adjustment",
                "score": 120,
            }
        ],
        "deferred": [],
        "conflicts": [
            {
                "actor_id": "",
                "target_hint": "入口摊位",
                "reason": "same_target_has_remove_and_keep_modify_requests",
            }
        ],
        "resolved_conflicts": [],
    }

    result = session.progressive_compose(
        {},
        reasonable_provider=lambda: {"actor-stall-generated": True},
        final_adjustment_provider=lambda: adjustment,
        final_review_protection_fn=_fake_protection,
    )
    report = result["final_report"]

    assert stall.layout_status == "active", "target_hint 未决冲突不应被 actor_id 绕过"
    assert report.applied_final_adjustments == []
    text = report.to_user_text()
    assert "GM/房主确认" in text
    assert "入口摊位" in text
    print("[OK] target_hint conflicts block matching final adjustments")


def test_final_adjustment_skips_stale_actor_version():
    layout = FakeLayout()
    session = SceneSession(layout)
    stall = FakeInst("actor-stall", provenance="AGENT", metadata={"actor_version": 5})
    stall.transform = {
        "pos": [0.0, 0.0, 0.0],
        "rot": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    }
    layout.add(stall)

    adjustment = {
        "selected": [
            {
                "intervention_id": "iv-stale-version",
                "content": "把入口摊位缩小一点",
                "actor_id": "actor-stall",
                "actor_version": 3,
                "target_hint": "入口摊位",
                "apply_policy": "final_adjustment",
                "score": 120,
            }
        ],
        "deferred": [],
        "conflicts": [],
        "resolved_conflicts": [],
    }

    result = session.progressive_compose(
        {},
        reasonable_provider=lambda: {"actor-stall": True},
        final_adjustment_provider=lambda: adjustment,
        final_review_protection_fn=_fake_protection,
    )
    report = result["final_report"]

    assert stall.transform["scale"] == [1.0, 1.0, 1.0]
    assert report.applied_final_adjustments[0]["actions"] == ["skipped_actor_version_mismatch"]
    assert report.applied_final_adjustments[0]["expected_actor_version"] == 3
    assert report.applied_final_adjustments[0]["actual_actor_version"] == 5
    assert not any(entry.op_type == "FINAL_ADJUST" for entry in session.operation_log)
    text = report.to_user_text()
    assert "已跳过过期介入" in text
    assert "已完成收尾调整" not in text
    assert "后续批次或用户更新" in text
    print("[OK] FinalReview skips stale actor-version final adjustments")


def test_final_review_user_text_sanitizes_internal_fields():
    report = FinalReviewReport(
        preserved=["入口摊位 prompt=PRIVATE_FINAL_PROMPT_SHOULD_NOT_LEAK"],
        adjusted=["天使雕塑 provider=final-provider-secret"],
        needs_confirm=[
            {
                "detail": "重新安排灯光 session_id=final-session-secret token=final-token-secret",
                "actor_id": "light-1",
            }
        ],
        final_adjustments=[
            {
                "content": "把入口摊位缩小一点 raw_prompt=PRIVATE_RAW_PROMPT_SHOULD_NOT_LEAK",
            }
        ],
        conflicts=[
            {
                "target_hint": "中央喷泉 vlm_raw=PRIVATE_VLM_RAW_SHOULD_NOT_LEAK",
                "reason": "debug=final-debug-secret",
            }
        ],
        resolved_conflicts=[
            {
                "target_hint": "入口摊位 api_key=final-api-key-secret",
                "reason": "same_target_has_remove_and_keep_modify_requests",
                "status": "rejected",
            }
        ],
        applied_final_adjustments=[
            {
                "action": "贴地修正 scheduler_updates=PRIVATE_SCHEDULER_UPDATE_SHOULD_NOT_LEAK",
            },
            {
                "content": "过期入口摊位 job_id=final-job-secret",
                "actions": ["skipped_actor_version_mismatch"],
            },
        ],
    )

    text = report.to_user_text()
    assert "入口摊位" in text
    assert "缩小一点" in text
    assert "贴地修正" in text
    assert "重新安排灯光" in text
    assert "中央喷泉" in text
    assert "PRIVATE_FINAL_PROMPT_SHOULD_NOT_LEAK" not in text
    assert "final-provider-secret" not in text
    assert "final-session-secret" not in text
    assert "final-token-secret" not in text
    assert "PRIVATE_RAW_PROMPT_SHOULD_NOT_LEAK" not in text
    assert "PRIVATE_VLM_RAW_SHOULD_NOT_LEAK" not in text
    assert "final-debug-secret" not in text
    assert "final-api-key-secret" not in text
    assert "PRIVATE_SCHEDULER_UPDATE_SHOULD_NOT_LEAK" not in text
    assert "final-job-secret" not in text
    print("[OK] FinalReview user text sanitizes internal fields")


if __name__ == "__main__":
    test_phase_loop_runs_provided_only()
    test_progress_sink_and_report_text_are_observable()
    test_progressive_compose_exposes_batch_resource_status()
    test_progressive_compose_pauses_at_micro_batch_boundary()
    test_intervention_drain_marks_user()
    test_post_import_hook_runs_before_final_review()
    test_delete_marks_stale_not_physical()
    test_settle_skips_recent_user()
    test_final_review_three_buckets()
    test_final_adjustment_plan_is_consumed_by_final_review()
    test_final_review_reports_failed_resource_requests_to_user()
    test_final_review_reports_scene_design_contract_without_leaking_prompt()
    test_resolved_final_adjustment_conflicts_are_consumed_by_final_review()
    test_unresolved_target_hint_conflict_blocks_matching_final_adjustment()
    test_final_adjustment_skips_stale_actor_version()
    test_final_review_user_text_sanitizes_internal_fields()
    print("\n=== COMMIT 4 SceneSession ALL PASS ===")
