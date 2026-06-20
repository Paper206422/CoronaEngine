"""离线自验：近因加权保护三档 + settlement 缩范围（突击方案 §2.2 / §B4）。

不依赖引擎，纯数据逻辑。验收：
- protection_level 三档分界正确（HARD 最近 / SOFT 早期合理 / NONE 早期不合理 / 纯AGENT=NONE）
- list_settleable 只放本批 AGENT + 早期不合理用户物体，绝不放最近用户介入
- mark_user_intervention 正确打 USER + 轮次

直接 `python test_protection_tiers.py` 运行。
"""
from layout import (
    LayoutInstance,
    SceneLayout,
    protection_level,
    PROTECTION_HARD,
    PROTECTION_SOFT,
    PROTECTION_NONE,
)


def _inst(iid, provenance="AGENT", intervention_round=-1, batch_id=None,
          layout_status="active"):
    return LayoutInstance(
        instance_id=iid, asset_id=iid, zone_id="default",
        provenance=provenance, intervention_round=intervention_round,
        batch_id=batch_id, layout_status=layout_status,
    )


def test_protection_tiers():
    cur = 5
    # 纯 AGENT，从未介入 → NONE
    assert protection_level(_inst("a"), cur) == PROTECTION_NONE
    # 最近一轮介入（cur-1=4）→ HARD（无论合理与否）
    assert protection_level(_inst("b", "USER", 4), cur, reasonable=True) == PROTECTION_HARD
    assert protection_level(_inst("b", "USER", 4), cur, reasonable=False) == PROTECTION_HARD
    # 当前轮介入 → HARD
    assert protection_level(_inst("c", "USER", 5), cur) == PROTECTION_HARD
    # 早期介入（round=1）+ 合理 → SOFT
    assert protection_level(_inst("d", "USER", 1), cur, reasonable=True) == PROTECTION_SOFT
    # 早期介入 + 不合理 → NONE（允许整体重排覆盖）
    assert protection_level(_inst("e", "USER", 1), cur, reasonable=False) == PROTECTION_NONE
    print("[OK] protection_level 三档分界正确")


def test_list_settleable():
    cur_round = 5
    cur_batch = "batch_5"
    layout = SceneLayout()
    # 本批 AGENT 物体 → 可 settle
    layout.add(_inst("agent_cur", "AGENT", batch_id=cur_batch))
    # 历史批次 AGENT → 不 settle（不对历史无差别沉降）
    layout.add(_inst("agent_old", "AGENT", batch_id="batch_3"))
    # 最近用户介入 → 绝不 settle
    layout.add(_inst("user_recent", "USER", intervention_round=5, batch_id=cur_batch))
    # 早期用户介入 + 合理 → SOFT，不 settle
    layout.add(_inst("user_early_ok", "USER", intervention_round=1, batch_id="batch_1"))
    # 早期用户介入 + 不合理 → NONE，可被覆盖
    layout.add(_inst("user_early_bad", "USER", intervention_round=1, batch_id="batch_1"))
    # hidden 实例 → 跳过
    layout.add(_inst("hidden_one", "AGENT", batch_id=cur_batch, layout_status="hidden"))

    reasonable_map = {"user_early_ok": True, "user_early_bad": False}
    settleable = {i.instance_id for i in
                  layout.list_settleable(cur_batch, cur_round, reasonable_map)}

    assert "agent_cur" in settleable, "本批 AGENT 应可 settle"
    assert "agent_old" not in settleable, "历史批次 AGENT 不应 settle"
    assert "user_recent" not in settleable, "最近用户介入绝不可 settle"
    assert "user_early_ok" not in settleable, "早期合理用户物体不应被覆盖"
    assert "user_early_bad" in settleable, "早期不合理用户介入应允许被整体重排覆盖"
    assert "hidden_one" not in settleable, "非 active 实例应跳过"
    print("[OK] list_settleable 缩范围正确（本批AGENT + 早期不合理用户物体）")


def test_mark_user_intervention():
    layout = SceneLayout()
    layout.add(_inst("x", "AGENT", batch_id="batch_2"))
    layout.mark_user_intervention("x", current_round=7)
    inst = layout.get("x")
    assert inst.provenance == "USER"
    assert inst.touched_by_user is True
    assert inst.intervention_round == 7
    assert inst.lock_level == "HARD"
    # 标记后立即视为最近介入 → HARD 保护
    assert protection_level(inst, current_round=7) == PROTECTION_HARD
    print("[OK] mark_user_intervention 打 USER + 轮次 + 即时强保护")


if __name__ == "__main__":
    test_protection_tiers()
    test_list_settleable()
    test_mark_user_intervention()
    print("\n=== COMMIT 1 元数据层 ALL PASS ===")
