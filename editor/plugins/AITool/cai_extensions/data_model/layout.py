"""
SceneLayout：当前布局

哪些资产被放进场景、各自的 pos/rot/scale（资产实例引用）。
regenerate 时 Agent 摆放可清，用户操作保留。

按文档 [后续计划:106-118]，LayoutInstance 字段：
  instance_id, asset_id, zone_id, transform,
  provenance, owner_id, lock_level, touched_by_user, anchor_ref, batch_id, layout_status

provenance 七字段（G老师扩展）散在 LayoutInstance 内，不单独抽类。
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class LayoutInstance:
    """布局实例：一个资产在场景里的一次摆放

    provenance 相关字段（7 个）：
      provenance, owner_id, lock_level, touched_by_user, layout_status + (anchor_ref, batch_id)
    """
    instance_id: str                 # 唯一 ID（引擎 actor GUID 或自生成 UUID）
    asset_id: str                    # 引用 AssetPool，不复制
    zone_id: str                     # 挂在哪个 Zone 上（M1 暂用 "default"，M2 接 ZoneTree）

    # Transform: [x, y, z], [rx, ry, rz], [sx, sy, sz]
    transform: Dict[str, List[float]] = field(default_factory=lambda: {
        "pos": [0.0, 0.0, 0.0],
        "rot": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
    })

    # Provenance 七字段
    provenance: str = "AGENT"        # "USER" | "AGENT"
    owner_id: str = "local"          # peer_id | "local"（多人：谁拥有/锁定）
    lock_level: str = "NONE"         # "NONE" | "SOFT" | "HARD"
    touched_by_user: bool = False    # 用户是否碰过（锁定/移动/旋转）
    layout_status: str = "active"    # "active" | "hidden" | "rejected" | "stale"

    # 可选
    anchor_ref: Optional[str] = None      # 依赖的锚点实例 ID（spatial constraint）
    batch_id: Optional[str] = None        # 哪一轮生成的（settlement 缩范围用）

    # 可选：元数据（M1 预留）
    metadata: Dict = field(default_factory=dict)


class SceneLayout:
    """当前布局：管理场景中所有实例

    M1 只实现内存存储 + 基本 CRUD，不实现持久化/engine 同步。
    """
    def __init__(self):
        self._instances: Dict[str, LayoutInstance] = {}

    def add(self, instance: LayoutInstance) -> None:
        """添加实例（幂等：instance_id 已存在则更新）"""
        self._instances[instance.instance_id] = instance

    def get(self, instance_id: str) -> Optional[LayoutInstance]:
        """查询单个实例"""
        return self._instances.get(instance_id)

    def remove(self, instance_id: str) -> None:
        """移除实例（regenerate / 用户删除）"""
        self._instances.pop(instance_id, None)

    def list_active(self) -> List[LayoutInstance]:
        """列出 layout_status=active 的实例"""
        return [i for i in self._instances.values() if i.layout_status == "active"]

    def list_by_provenance(self, provenance: str) -> List[LayoutInstance]:
        """按 provenance 筛选（"USER" / "AGENT"）"""
        return [i for i in self._instances.values() if i.provenance == provenance]

    def list_locked(self) -> List[LayoutInstance]:
        """列出 lock_level != NONE 的实例"""
        return [i for i in self._instances.values() if i.lock_level != "NONE"]

    def clear_agent_instances(self) -> None:
        """清除 provenance=AGENT 的实例（regenerate 时调用，保留用户操作）"""
        self._instances = {
            iid: inst for iid, inst in self._instances.items()
            if inst.provenance == "USER"
        }

    def clear(self) -> None:
        """清空布局（M1 测试用）"""
        self._instances.clear()
