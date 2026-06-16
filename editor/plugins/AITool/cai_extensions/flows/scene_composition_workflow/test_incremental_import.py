"""离线自验：渐进式增量导入（突击方案 §2.1 / §C3 — 只 add 不 clear）。

注入假 import_tool / 假 SceneLayout / 假 EngineWriteGate / 假 LayoutInstance，
不依赖引擎。验收：
- 只 add，绝不清场（已有 actor 全保留）
- 导入后写 provenance=AGENT + batch_id
- 单个失败不中断整批
- 所有引擎写入经 engine_gate.invoke_tool（串行收口）

直接 `python test_incremental_import.py` 运行。
"""
import sys
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# 让 `from ...data_model.layout` 在独立运行时不被触发——我们注入 layout_instance_cls。
sys.path.insert(0, os.path.dirname(__file__))
from incremental_import import incremental_import  # noqa: E402


# ── 假实现 ───────────────────────────────────────────────

@dataclass
class FakeLayoutInstance:
    instance_id: str
    asset_id: str
    zone_id: str
    transform: Dict[str, List[float]] = field(default_factory=dict)
    provenance: str = "AGENT"
    batch_id: Optional[str] = None
    anchor_ref: Optional[str] = None
    intervention_round: int = -1


class FakeLayout:
    def __init__(self):
        self._inst = {}

    def add(self, inst):
        self._inst[inst.instance_id] = inst

    def get(self, iid):
        return self._inst.get(iid)

    def all_ids(self):
        return set(self._inst)


class FakeGate:
    """记录调用次数，验证所有写入都经 gate。"""
    def __init__(self, fail_names=None):
        self.invoke_count = 0
        self.fail_names = set(fail_names or [])

    def invoke_tool(self, tool, payload):
        self.invoke_count += 1
        name = payload.get("actor_name", "")
        if name in self.fail_names:
            raise RuntimeError(f"模拟 {name} 导入失败")
        return {"actor_name": name, "status": "success"}


class FakeTool:
    pass


def test_only_add_no_clear():
    layout = FakeLayout()
    # 预置一个用户物体 + 一个上一批 agent 物体
    layout.add(FakeLayoutInstance("user_sofa", "sofa", "default", provenance="USER"))
    layout.add(FakeLayoutInstance("agent_table_b1", "table", "default",
                                  provenance="AGENT", batch_id="batch_1"))
    gate = FakeGate()

    incremental_import(
        [{"name": "lamp", "path": "/m/lamp.glb"},
         {"name": "rug", "path": "/m/rug.glb"}],
        batch_id="batch_2", import_tool=FakeTool(),
        scene_layout=layout, engine_gate=gate,
        layout_instance_cls=FakeLayoutInstance,
    )
    ids = layout.all_ids()
    assert "user_sofa" in ids, "用户物体绝不能被清场"
    assert "agent_table_b1" in ids, "上一批 agent 物体绝不能被清场"
    assert "lamp" in ids and "rug" in ids, "本批新物体应导入"
    print("[OK] 只 add 不 clear（用户物体 + 历史批次全保留）")


def test_writes_provenance():
    layout = FakeLayout()
    gate = FakeGate()
    incremental_import(
        [{"name": "yurt", "path": "/m/yurt.glb", "zone_id": "indoor",
          "anchor_ref": "terrain"}],
        batch_id="batch_5", import_tool=FakeTool(),
        scene_layout=layout, engine_gate=gate,
        layout_instance_cls=FakeLayoutInstance,
    )
    inst = layout.get("yurt")
    assert inst is not None
    assert inst.provenance == "AGENT", "渐进导入应写 AGENT"
    assert inst.batch_id == "batch_5"
    assert inst.zone_id == "indoor"
    assert inst.anchor_ref == "terrain"
    assert inst.intervention_round == -1, "从未被用户介入"
    print("[OK] 导入后写 provenance=AGENT + batch_id + zone + anchor")


def test_failure_does_not_abort_batch():
    layout = FakeLayout()
    gate = FakeGate(fail_names={"broken"})
    result = incremental_import(
        [{"name": "good1", "path": "/m/g1.glb"},
         {"name": "broken", "path": "/m/b.glb"},
         {"name": "good2", "path": "/m/g2.glb"}],
        batch_id="b", import_tool=FakeTool(),
        scene_layout=layout, engine_gate=gate,
        layout_instance_cls=FakeLayoutInstance,
    )
    assert set(result["imported"]) == {"good1", "good2"}, "好的应全导入"
    assert len(result["failed"]) == 1 and result["failed"][0]["name"] == "broken"
    print("[OK] 单个失败不中断整批")


def test_all_writes_through_gate():
    layout = FakeLayout()
    gate = FakeGate()
    incremental_import(
        [{"name": "a", "path": "/m/a.glb"}, {"name": "b", "path": "/m/b.glb"}],
        batch_id="b", import_tool=FakeTool(),
        scene_layout=layout, engine_gate=gate,
        layout_instance_cls=FakeLayoutInstance,
    )
    assert gate.invoke_count == 2, "每个导入都必须经 EngineWriteGate"
    print("[OK] 所有引擎写入经 EngineWriteGate 串行收口")


def test_missing_path_skipped():
    layout = FakeLayout()
    gate = FakeGate()
    result = incremental_import(
        [{"name": "nopath"}],
        batch_id="b", import_tool=FakeTool(),
        scene_layout=layout, engine_gate=gate,
        layout_instance_cls=FakeLayoutInstance,
    )
    assert result["failed"] and result["failed"][0]["name"] == "nopath"
    assert gate.invoke_count == 0, "无路径不应触碰引擎"
    print("[OK] 无模型路径跳过、不触引擎")


if __name__ == "__main__":
    test_only_add_no_clear()
    test_writes_provenance()
    test_failure_does_not_abort_batch()
    test_all_writes_through_gate()
    test_missing_path_skipped()
    print("\n=== COMMIT 3 incremental_import ALL PASS ===")
