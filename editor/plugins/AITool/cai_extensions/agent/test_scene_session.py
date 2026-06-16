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


if __name__ == "__main__":
    test_phase_loop_runs_provided_only()
    test_intervention_drain_marks_user()
    test_delete_marks_stale_not_physical()
    test_settle_skips_recent_user()
    test_final_review_three_buckets()
    print("\n=== COMMIT 4 SceneSession ALL PASS ===")
