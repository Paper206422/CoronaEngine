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
    _infer_primary_zone_ids,
)
from cai_extensions.data_model.zone_tree import Connector, Volume, Zone, ZoneTree  # noqa: E402


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
        )
        indoor = Zone(
            zone_id="main_building",
            name="main shell",
            role="indoor",
            enclosure="shell",
            volume=Volume(center=[0.0, 1.5, 0.0], size=[6.0, 6.0, 3.0]),
            primary_shell_asset_id="main shell",
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


if __name__ == "__main__":
    test_zone_and_asset_routing()
    test_zone_and_door_aabb_helpers()
    test_filter_aabbs_by_zone()
    print("\n=== progressive mixed geometry ALL PASS ===")
