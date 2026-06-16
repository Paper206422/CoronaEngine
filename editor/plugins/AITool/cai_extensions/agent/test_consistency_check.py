"""离线自验：AABB 一致性检查 E5-a/E5-b（突击方案 §2.3aabb）。

纯几何、无引擎依赖。验收：
- 穿模/挡门/超Zone/悬空 各报对应 issue
- E5-a/E5-b 分层不混
- reasonable_map_from_result 把 error 级问题转成 不合理（喂 §2.2 保护）

直接 `python test_consistency_check.py` 运行。
"""
from consistency_check import (
    run_furniture_checks,
    check_overlaps,
    check_block_door,
    check_out_of_zone,
    check_floating,
    check_shell_on_platform,
    check_interior_within_footprint,
    reasonable_map_from_result,
    ISSUE_OVERLAP,
    ISSUE_BLOCK_DOOR,
    ISSUE_OUT_OF_ZONE,
    ISSUE_FLOATING,
    ISSUE_SHELL_OFF_PLATFORM,
)


def test_overlap():
    # 两个明显重叠的盒子
    aabbs = {
        "a": [0, 0, 0, 2, 2, 2],
        "b": [1, 0, 1, 3, 2, 3],   # 与 a 在 [1,2]x[0,2]x[1,2] 重叠
        "c": [10, 0, 10, 11, 1, 11],  # 远处，不重叠
    }
    issues = check_overlaps(aabbs)
    kinds = {(i.actor_id, i.related_id) for i in issues}
    assert any({"a", "b"} == {aid, rid} for aid, rid in kinds), "a/b 应报穿模"
    assert all("c" not in {aid, rid} for aid, rid in kinds), "c 不应卷入穿模"
    assert all(i.kind == ISSUE_OVERLAP for i in issues)
    print("[OK] check_overlaps 穿模检测正确")


def test_block_door():
    aabbs = {"sofa": [-1, 0, -1, 1, 1, 1]}
    doors = {"door_main": [0, 0, 0.5, 0.5, 2, 1.5]}  # XZ 与 sofa 重叠
    issues = check_block_door(aabbs, doors)
    assert len(issues) == 1 and issues[0].kind == ISSUE_BLOCK_DOOR
    assert issues[0].actor_id == "sofa" and issues[0].related_id == "door_main"
    print("[OK] check_block_door 挡门检测正确")


def test_out_of_zone():
    zone = [0, 0, 0, 5, 3, 5]
    aabbs = {
        "inside": [1, 0, 1, 2, 1, 2],
        "outside": [4, 0, 4, 7, 1, 7],   # 越过 max_x/max_z
    }
    issues = check_out_of_zone(aabbs, zone, "yurt")
    bad = {i.actor_id for i in issues}
    assert "outside" in bad and "inside" not in bad
    assert all(i.kind == ISSUE_OUT_OF_ZONE for i in issues)
    print("[OK] check_out_of_zone 超Zone检测正确")


def test_floating():
    fi = check_floating("lamp", [0, 1.5, 0, 1, 2.5, 1], ground_y=0.0)
    assert fi is not None and fi.kind == ISSUE_FLOATING
    assert fi.suggestion["nudge"][1] < 0  # 应建议向下沉
    grounded = check_floating("rug", [0, 0.0, 0, 1, 0.02, 1], ground_y=0.0)
    assert grounded is None  # 贴地不报
    print("[OK] check_floating 悬空检测 + 下沉建议正确")


def test_layer_separation():
    # E5-a 基础设施层问题不混入家具层
    shell_issue = check_shell_on_platform("yurt_shell", [-2, 0.5, -2, 2, 3, 2], platform_y=0.0)
    assert shell_issue is not None and shell_issue.layer == "infra"
    interior_ok = check_interior_within_footprint(
        "rug", [-1.5, 0, -1.5, 1.5, 0.02, 1.5], [-2, 0, -2, 2, 3, 2])
    assert interior_ok is None  # 地毯在足迹内
    interior_overflow = check_interior_within_footprint(
        "rug", [-3, 0, -3, 3, 0.02, 3], [-2, 0, -2, 2, 3, 2])
    assert interior_overflow is not None and interior_overflow.layer == "infra"
    print("[OK] E5-a 基础设施层检查 + 分层不混")


def test_reasonable_map():
    aabbs = {
        "good": [0, 0, 0, 1, 1, 1],
        "bad": [0.2, 0, 0.2, 1.2, 1, 1.2],  # 与 good 深度穿模（重叠占比 64% > 30% → error）
    }
    result = run_furniture_checks(aabbs)
    rmap = reasonable_map_from_result(result, ["good", "bad"])
    # 穿模 ratio 大 → error → 两者都不合理
    assert rmap["bad"] is False, "穿模物体应判不合理"
    print("[OK] reasonable_map 把 error 转成 不合理（喂 §2.2 保护）")


if __name__ == "__main__":
    test_overlap()
    test_block_door()
    test_out_of_zone()
    test_floating()
    test_layer_separation()
    test_reasonable_map()
    print("\n=== COMMIT 2 一致性检查 ALL PASS ===")
