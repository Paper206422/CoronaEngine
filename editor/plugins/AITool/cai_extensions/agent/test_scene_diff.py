"""离线自验：轮询式视口 scene-diff（突击方案 §2.1 路 A 命门解法）。

纯逻辑、无引擎依赖。验收：
- diff_snapshots 三类事件（moved/added/deleted）正确
- 阈值过滤浮点噪声（微小抖动不报）
- SceneDiffTracker 把 agent 自己导入的 actor 排除出"用户新增"

直接 `python test_scene_diff.py` 运行。
"""
from scene_diff import (
    make_transform,
    diff_snapshots,
    SceneDiffTracker,
    DIFF_MOVED,
    DIFF_ADDED,
    DIFF_DELETED,
)


def _snap(**kw):
    """kw: actor_id=((pos),(rot),(scale)) 简写。"""
    return {k: make_transform(*v) for k, v in kw.items()}


def test_diff_three_kinds():
    prev = _snap(
        sofa=((0, 0, 0), (0, 0, 0), (1, 1, 1)),
        table=((2, 0, 0), (0, 0, 0), (1, 1, 1)),
    )
    cur = _snap(
        sofa=((1.5, 0, 0), (0, 0, 0), (1, 1, 1)),   # moved (pos)
        # table 删除
        lamp=((3, 0, 0), (0, 0, 0), (1, 1, 1)),     # added
    )
    events = {(e.kind, e.actor_id) for e in diff_snapshots(prev, cur)}
    assert (DIFF_MOVED, "sofa") in events, "sofa 移动应报 moved"
    assert (DIFF_DELETED, "table") in events, "table 删除应报 deleted"
    assert (DIFF_ADDED, "lamp") in events, "lamp 新增应报 added"
    print("[OK] diff_snapshots 三类事件正确")


def test_threshold_filters_noise():
    prev = _snap(rug=((0, 0, 0), (0, 0, 0), (1, 1, 1)))
    # 微小抖动（低于阈值）→ 不报
    cur = _snap(rug=((0.0005, 0, 0), (0, 0, 0.005), (1, 1, 1.0005)))
    events = diff_snapshots(prev, cur)
    assert not events, "亚阈值抖动不应报介入"
    print("[OK] 阈值过滤浮点噪声")


def test_changed_items_labeled():
    prev = _snap(box=((0, 0, 0), (0, 0, 0), (1, 1, 1)))
    cur = _snap(box=((0, 0, 0), (0, 90, 0), (2, 2, 2)))  # rot + scale 变
    events = diff_snapshots(prev, cur)
    assert len(events) == 1 and events[0].kind == DIFF_MOVED
    assert set(events[0].changed) == {"rot", "scale"}, "应标出 rot/scale 变了"
    print("[OK] MOVED 事件标出具体变了哪几项")


def test_tracker_excludes_agent_imports():
    tracker = SceneDiffTracker()
    base = _snap(yurt=((0, 0, 0), (0, 0, 0), (1, 1, 1)))
    tracker.set_baseline(base)

    # agent 导入了一个新 actor（rug）→ 纳入基线
    after_import = _snap(
        yurt=((0, 0, 0), (0, 0, 0), (1, 1, 1)),
        rug=((0, 0, 0), (0, 0, 0), (1, 1, 1)),
    )
    tracker.baseline_add(["rug"], after_import)

    # 下一次 poll：rug 不应被当成用户新增；用户自己拖了 yurt + 新增 cushion
    cur = _snap(
        yurt=((0.5, 0, 0), (0, 0, 0), (1, 1, 1)),       # 用户拖动
        rug=((0, 0, 0), (0, 0, 0), (1, 1, 1)),
        cushion=((1, 0, 0), (0, 0, 0), (1, 1, 1)),       # 用户新增
    )
    events = tracker.poll(cur)
    kinds = {(e.kind, e.actor_id) for e in events}
    assert (DIFF_MOVED, "yurt") in kinds, "用户拖动 yurt 应报"
    assert (DIFF_ADDED, "cushion") in kinds, "用户新增 cushion 应报"
    assert (DIFF_ADDED, "rug") not in kinds, "agent 导入的 rug 不应被当用户新增"
    print("[OK] SceneDiffTracker 排除 agent 自导入，只报真用户介入")


if __name__ == "__main__":
    test_diff_three_kinds()
    test_threshold_filters_noise()
    test_changed_items_labeled()
    test_tracker_excludes_agent_imports()
    print("\n=== COMMIT 3 scene-diff ALL PASS ===")
