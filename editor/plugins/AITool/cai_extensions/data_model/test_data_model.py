"""
M1 数据模型单元测试

验证 AssetPool / SceneLayout / UserLayer 基本 CRUD + provenance 逻辑。
M1 只测数据结构，不涉及引擎/磁盘 I/O。

运行: python -m pytest editor/plugins/AITool/cai_extensions/data_model/test_data_model.py -v
或:   python editor/plugins/AITool/cai_extensions/data_model/test_data_model.py
"""
import sys
from datetime import datetime


def test_asset_pool():
    """测试 AssetPool：添加/查询/标记拒绝"""
    from cai_extensions.data_model.asset_pool import AssetPool, AssetPoolEntry

    pool = AssetPool()
    entry = AssetPoolEntry(
        asset_id="asset_001",
        local_path="/tmp/sofa.glb",
        prompt="modern sofa",
        type="generated",
        created_at=datetime.utcnow().isoformat() + "Z",
    )
    pool.add(entry)

    # 查询
    assert pool.get("asset_001") == entry
    assert pool.get("not_exist") is None

    # 列出 available
    assert len(pool.list_available()) == 1

    # 标记拒绝
    pool.mark_rejected("asset_001")
    assert pool.get("asset_001").status == "rejected"
    assert len(pool.list_available()) == 0

    print("✓ test_asset_pool passed")


def test_scene_layout():
    """测试 SceneLayout：添加/查询/按 provenance 筛选/清除 Agent 实例"""
    from cai_extensions.data_model.layout import SceneLayout, LayoutInstance

    layout = SceneLayout()

    # 添加 Agent 实例
    agent_inst = LayoutInstance(
        instance_id="inst_001",
        asset_id="asset_001",
        zone_id="default",
        provenance="AGENT",
    )
    layout.add(agent_inst)

    # 添加 User 实例
    user_inst = LayoutInstance(
        instance_id="inst_002",
        asset_id="asset_002",
        zone_id="default",
        provenance="USER",
        lock_level="HARD",
        touched_by_user=True,
    )
    layout.add(user_inst)

    # 查询
    assert layout.get("inst_001") == agent_inst
    assert layout.get("inst_002") == user_inst

    # 按 provenance 筛选
    assert len(layout.list_by_provenance("AGENT")) == 1
    assert len(layout.list_by_provenance("USER")) == 1

    # 锁定筛选
    assert len(layout.list_locked()) == 1
    assert layout.list_locked()[0].instance_id == "inst_002"

    # 清除 Agent 实例（regenerate）
    layout.clear_agent_instances()
    assert layout.get("inst_001") is None
    assert layout.get("inst_002") is not None  # User 实例保留

    print("✓ test_scene_layout passed")


def test_user_layer():
    """测试 UserLayer：锁定/拒绝/操作日志"""
    from cai_extensions.data_model.user_layer import UserLayer

    user = UserLayer()

    # 锁定实例
    user.lock_instance("inst_001")
    assert user.is_locked("inst_001")
    assert not user.is_locked("inst_002")

    # 拒绝资产
    user.reject_asset("asset_bad")
    assert user.is_rejected("asset_bad")

    # 解锁
    user.unlock_instance("inst_001")
    assert not user.is_locked("inst_001")

    # 操作日志
    assert len(user.operation_log) == 3  # lock + reject + unlock
    recent = user.get_recent_operations(count=2)
    assert len(recent) == 2
    assert recent[0].operation == "unlock"  # 最新的在前

    print("✓ test_user_layer passed")


def test_provenance_seven_fields():
    """测试 provenance 七字段（G老师扩展）在 LayoutInstance 内"""
    from cai_extensions.data_model.layout import LayoutInstance

    inst = LayoutInstance(
        instance_id="inst_provenance",
        asset_id="asset_x",
        zone_id="zone_a",
        provenance="USER",
        owner_id="peer_123",
        lock_level="SOFT",
        touched_by_user=True,
        anchor_ref="inst_anchor",
        batch_id="batch_001",
        layout_status="active",
    )

    # 七字段都在
    assert inst.provenance == "USER"
    assert inst.owner_id == "peer_123"
    assert inst.lock_level == "SOFT"
    assert inst.touched_by_user is True
    assert inst.layout_status == "active"
    assert inst.anchor_ref == "inst_anchor"
    assert inst.batch_id == "batch_001"

    print("✓ test_provenance_seven_fields passed")


if __name__ == "__main__":
    # 简单运行（不依赖 pytest）
    test_asset_pool()
    test_scene_layout()
    test_user_layer()
    test_provenance_seven_fields()
    print("\n✅ All M1 data model tests passed")
