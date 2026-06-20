"""
ZoneTree 单元测试

M2 步骤 2：验证 Zone 数据结构 + 单 Zone 退化形态。

运行: python -c "import sys; sys.path.insert(0, '.'); exec(open('editor/plugins/AITool/cai_extensions/data_model/test_zone_tree.py').read())"
      从 editor/plugins/AITool 目录
"""
import sys


def test_single_zone_box():
    """测试单 Zone + enclosure=box（退化形态，对应现有 room_box）"""
    from cai_extensions.data_model.zone_tree import Zone, ZoneTree, Volume

    # 单 Zone：5×3×3 的室内盒子（对应现有 room_size）
    root = Zone(
        zone_id="zone_root",
        name="living_room",
        role="indoor",
        volume=Volume(center=[0.0, 1.5, 0.0], size=[5.0, 3.0, 3.0]),
        enclosure="box",
    )

    tree = ZoneTree(root=root)

    # 查询根 Zone
    assert tree.get_zone("zone_root") == root
    assert tree.get_zone("not_exist") is None

    # 列出所有 Zone（单 Zone 时只有根）
    all_zones = tree.list_all_zones()
    assert len(all_zones) == 1
    assert all_zones[0].zone_id == "zone_root"

    # 验证字段
    assert root.enclosure == "box"
    assert root.role == "indoor"
    assert root.volume.size == [5.0, 3.0, 3.0]
    assert len(root.sub_zones) == 0  # 单 Zone 无子节点

    print("[PASS] test_single_zone_box")


def test_two_layer_zone_nesting():
    """测试两层 Zone 嵌套（M2 步骤 14 目标：草原 + 蒙古包内部）"""
    from cai_extensions.data_model.zone_tree import Zone, ZoneTree, Volume, Connector

    # 外层：草原（enclosure=terrain）
    outer = Zone(
        zone_id="zone_outdoor",
        name="grassland",
        role="outdoor",
        volume=Volume(center=[0.0, 0.0, 0.0], size=[20.0, 0.0, 20.0]),  # terrain 高度=0
        enclosure="terrain",
    )

    # 内层：蒙古包内部（enclosure=shell）
    inner = Zone(
        zone_id="zone_indoor",
        name="yurt_interior",
        role="indoor",
        volume=Volume(center=[5.0, 0.0, 5.0], size=[4.0, 2.5, 4.0]),
        enclosure="shell",
        primary_shell_asset_id="asset_yurt",  # 主外壳：蒙古包模型
    )

    # 门洞：连接外层和内层
    door = Connector(
        connector_id="door_01",
        type="door",
        position=[5.0, 0.0, 3.0],  # 在外层 Zone 的位置
        size=[1.0, 2.0],
        target_zone_id="zone_indoor",
    )

    # 挂载子 Zone + 门洞
    outer.sub_zones.append(inner)
    outer.connectors.append(door)

    tree = ZoneTree(root=outer)

    # 递归查询
    assert tree.get_zone("zone_outdoor") == outer
    assert tree.get_zone("zone_indoor") == inner

    # 列出所有 Zone（先序遍历：外层 → 内层）
    all_zones = tree.list_all_zones()
    assert len(all_zones) == 2
    assert all_zones[0].zone_id == "zone_outdoor"
    assert all_zones[1].zone_id == "zone_indoor"

    # 验证嵌套结构
    assert len(outer.sub_zones) == 1
    assert outer.sub_zones[0].zone_id == "zone_indoor"
    assert len(outer.connectors) == 1
    assert outer.connectors[0].target_zone_id == "zone_indoor"

    print("[PASS] test_two_layer_zone_nesting")


if __name__ == "__main__":
    test_single_zone_box()
    test_two_layer_zone_nesting()
    print("")
    print("=== All ZoneTree tests passed ===")
