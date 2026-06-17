"""离线自验：progressive 混合环境几何约束接线。

覆盖目标：
- indoor/outdoor/shell zone 推断不依赖具体"蒙古包"关键词。
- 资产分流会写入 zone_id，避免后续 AABB zone 检查误伤室外物体。
- connector 能派生 door clearance AABB，用于防挡门/防穿模内回路。
"""
import os
import sys
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from cai_extensions.agent.scene_composer_progressive import (  # noqa: E402
    _collect_door_clearance_aabbs,
    _collect_zone_aabbs,
    _distribute_assets_to_phases,
    _filter_aabbs_by_zone,
    _generate_post_shell_framework,
    _infer_primary_zone_ids,
)
from cai_extensions.data_model.zone_tree import Connector, Volume, Zone, ZoneAspect, ZoneTree  # noqa: E402


@dataclass
class FakeInstance:
    instance_id: str
    zone_id: str
    layout_status: str = "active"


class FakeLayout:
    def __init__(self, instances: List[FakeInstance]):
        self._instances = instances

    def list_active(self):
        return [i for i in self._instances if i.layout_status == "active"]


class FakeComposer:
    def __init__(self):
        outdoor = Zone(
            zone_id="grassland",
            name="open field",
            role="outdoor",
            enclosure="terrain",
            volume=Volume(center=[0.0, 0.0, 0.0], size=[20.0, 20.0, 0.0]),
            aspects=[ZoneAspect(capability="boundary", params={"kind": "fence", "radius": 7.0})],
        )
        indoor = Zone(
            zone_id="main_building",
            name="main shell",
            role="indoor",
            enclosure="shell",
            volume=Volume(center=[0.0, 1.5, 0.0], size=[6.0, 6.0, 3.0]),
            primary_shell_asset_id="main shell",
            aspects=[ZoneAspect(capability="foundation_surface", params={"material": "stone", "shape": "quad", "padding": 0.8})],
        )
        indoor.connectors.append(Connector(
            connector_id="door_main",
            type="door",
            position=[0.0, 0.0, 3.0],
            size=[1.2, 2.0],
            target_zone_id="main_building",
        ))
        outdoor.sub_zones.append(indoor)
        self.zone_tree = ZoneTree(root=outdoor)
        self.floors = []
        self.foundations = []
        self.fences = []
        self.anchors = []
        self._terrain_extent = {"extent": 20.0, "width": 20.0, "depth": 20.0}
        self._shell_aabb = {
            "main shell": {"half_x": 3.0, "half_z": 3.0, "height": 4.0},
        }

    def _generate_interior_floor(self, zone):
        self.floors.append(zone.zone_id)

    def _generate_foundation_surface(self, zone):
        self.foundations.append(zone.zone_id)
        self._foundation_extent = {"width": 7.6, "depth": 7.6}

    def _generate_fence(self, params, anchor=None):
        self.fences.append(dict(params or {}))
        self.anchors.append(dict(anchor or {}))


def test_zone_and_asset_routing():
    composer = FakeComposer()
    indoor, outdoor, shell = _infer_primary_zone_ids(composer)
    assert indoor == "main_building"
    assert outdoor == "grassland"
    assert shell == "main_building"

    phase_map = _distribute_assets_to_phases(
        [
            {"name": "wooden table", "model_path": "/m/table.glb"},
            {"name": "campfire", "model_path": "/m/fire.glb"},
            {"name": "fence", "model_path": "/m/fence.glb"},
            {"name": "lamp", "model_path": "/m/lamp.glb"},
            {"name": "angel statue", "model_path": "/m/statue.glb"},
            {"name": "fountain", "model_path": "/m/fountain.glb"},
        ],
        [],
        composer,
    )
    interior = phase_map["INTERIOR"][0]
    outdoor_object = phase_map["OBJECTS"][0]
    boundary = phase_map["BOUNDARY"][0]
    decoration = phase_map["DECORATION"][0]

    assert interior["zone_id"] == "main_building"
    assert interior["anchor_ref"] == "main_building"
    assert outdoor_object["zone_id"] == "grassland"
    assert boundary["zone_id"] == "grassland"
    assert decoration["zone_id"] == "main_building"
    outdoor_names = {a["name"]: a["zone_id"] for a in phase_map["OBJECTS"]}
    assert outdoor_names["angel statue"] == "grassland"
    assert outdoor_names["fountain"] == "grassland"
    positions = {a["name"]: tuple(a.get("pos", [])) for phase in phase_map.values() for a in phase}
    scales = {a["name"]: tuple(a.get("scale", [])) for phase in phase_map.values() for a in phase}
    roles = {a["name"]: a.get("layout_role") for phase in phase_map.values() for a in phase}
    assert positions["wooden table"] != positions["fountain"]
    assert positions["angel statue"] != (0.0, 0.0, 0.0)
    assert positions["fountain"] != (0.0, 0.0, 0.0)
    assert roles["fountain"] == "landmark"
    assert roles["angel statue"] == "landmark"
    assert scales["fountain"][0] >= 1.15
    assert scales["angel statue"][0] >= 1.25
    print("[OK] mixed environment asset routing writes zone_id / anchor_ref")


def test_zone_and_door_aabb_helpers():
    composer = FakeComposer()
    zone_aabbs = _collect_zone_aabbs(composer.zone_tree)
    door_aabbs = _collect_door_clearance_aabbs(composer.zone_tree)

    assert zone_aabbs["grassland"] == [-10.0, -0.1, -10.0, 10.0, 0.1, 10.0]
    assert zone_aabbs["main_building"] == [-3.0, 0.0, -3.0, 3.0, 3.0, 3.0]
    assert "door_main" in door_aabbs
    assert door_aabbs["door_main"][2] < 3.0 < door_aabbs["door_main"][5]
    print("[OK] ZoneTree derives zone AABB and door clearance AABB")


def test_indoor_room_slot_planner_uses_asset_semantics():
    composer = FakeComposer()
    phase_map = _distribute_assets_to_phases(
        [
            {"name": "儿童床", "model_path": "/m/bed.glb"},
            {"name": "书桌", "model_path": "/m/desk.glb"},
            {"name": "椅子", "model_path": "/m/chair.glb"},
            {"name": "衣柜", "model_path": "/m/wardrobe.glb"},
            {"name": "书架", "model_path": "/m/bookshelf.glb"},
            {"name": "地毯", "model_path": "/m/rug.glb"},
            {"name": "台灯", "model_path": "/m/lamp.glb"},
            {"name": "玩具柜", "model_path": "/m/toy.glb"},
        ],
        [],
        composer,
    )
    rows = {a["name"]: a for phase in phase_map.values() for a in phase}
    assert rows["地毯"]["layout_role"] == "surface"
    assert rows["儿童床"]["pos"][2] < 0.0
    assert rows["书桌"]["pos"][0] < 0.0
    assert rows["椅子"]["pos"] != rows["书桌"]["pos"]
    assert rows["台灯"]["pos"] != [0.0, 0.0, 0.0]
    unique_positions = {tuple(row["pos"]) for row in rows.values()}
    assert len(unique_positions) >= 6
    print("[OK] indoor room slot planner separates large furniture, surface, and dependents")


def test_filter_aabbs_by_zone():
    layout = FakeLayout([
        FakeInstance("table", "main_building"),
        FakeInstance("campfire", "grassland"),
    ])
    aabbs = {
        "table": [-0.5, 0.0, -0.5, 0.5, 1.0, 0.5],
        "campfire": [4.0, 0.0, 4.0, 5.0, 1.0, 5.0],
    }
    indoor = _filter_aabbs_by_zone(layout, aabbs, "main_building")
    outdoor = _filter_aabbs_by_zone(layout, aabbs, "grassland")
    assert list(indoor) == ["table"]
    assert list(outdoor) == ["campfire"]
    print("[OK] AABB zone checks are scoped by LayoutInstance.zone_id")


def test_progressive_post_shell_framework_generates_floor_and_boundary():
    composer = FakeComposer()
    _generate_post_shell_framework(composer)
    assert composer.floors == ["main_building"]
    assert composer.foundations == ["main_building"]
    assert composer.fences and composer.fences[0]["kind"] == "fence"
    assert composer.anchors and composer.anchors[0]["anchor_type"] == "shell"
    print("[OK] progressive post-shell framework keeps interior floor and boundary chain")


if __name__ == "__main__":
    test_zone_and_asset_routing()
    test_zone_and_door_aabb_helpers()
    test_indoor_room_slot_planner_uses_asset_semantics()
    test_filter_aabbs_by_zone()
    test_progressive_post_shell_framework_generates_floor_and_boundary()
    print("\n=== progressive mixed geometry ALL PASS ===")
