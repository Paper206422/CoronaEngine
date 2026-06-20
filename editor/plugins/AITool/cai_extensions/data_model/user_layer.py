"""
UserLayer：用户操作账本

全局用户操作账本（不是 per-actor）：
  锁定集合 + 拒绝集合 + 操作日志 + 偏好

按文档 [后续计划:120-126]，UserLayer 字段：
  locked_instance_ids, rejected_asset_ids, operation_log, preferences

不等于 provenance（provenance 在 LayoutInstance 内，这里是全局账本）。
"""
from typing import Dict, List, Set
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class OperationLogEntry:
    """操作日志条目：记录用户一次操作"""
    timestamp: str                   # ISO 8601
    operation: str                   # "lock" | "unlock" | "reject_asset" | "move" | "rotate" | "delete"
    target_id: str                   # instance_id or asset_id
    details: Dict = field(default_factory=dict)  # 可选：操作细节（旧/新 transform 等）


class UserLayer:
    """用户操作账本：跟随用户操作，regenerate 时保留

    M1 只实现内存存储 + 基本操作，不实现持久化。
    """
    def __init__(self):
        # 锁定集合：哪些实例被用户锁定（instance_id）
        self.locked_instance_ids: Set[str] = set()

        # 拒绝集合：哪些资产被用户拒绝（asset_id）
        self.rejected_asset_ids: Set[str] = set()

        # 操作日志：用户操作历史（按时间顺序）
        self.operation_log: List[OperationLogEntry] = []

        # 用户偏好：风格/尺寸/摆放偏好（M1 预留，格式待定）
        self.preferences: Dict = {}

    def lock_instance(self, instance_id: str) -> None:
        """锁定实例"""
        self.locked_instance_ids.add(instance_id)
        self._log("lock", instance_id)

    def unlock_instance(self, instance_id: str) -> None:
        """解锁实例"""
        self.locked_instance_ids.discard(instance_id)
        self._log("unlock", instance_id)

    def reject_asset(self, asset_id: str) -> None:
        """拒绝资产（用户不想要这个模型）"""
        self.rejected_asset_ids.add(asset_id)
        self._log("reject_asset", asset_id)

    def is_locked(self, instance_id: str) -> bool:
        """查询实例是否被锁定"""
        return instance_id in self.locked_instance_ids

    def is_rejected(self, asset_id: str) -> bool:
        """查询资产是否被拒绝"""
        return asset_id in self.rejected_asset_ids

    def _log(self, operation: str, target_id: str, details: Dict = None) -> None:
        """内部：记录操作日志"""
        entry = OperationLogEntry(
            timestamp=datetime.utcnow().isoformat() + "Z",
            operation=operation,
            target_id=target_id,
            details=details or {},
        )
        self.operation_log.append(entry)

    def get_recent_operations(self, count: int = 10) -> List[OperationLogEntry]:
        """获取最近 N 条操作（按时间倒序）"""
        return self.operation_log[-count:][::-1]

    def clear(self) -> None:
        """清空账本（M1 测试用）"""
        self.locked_instance_ids.clear()
        self.rejected_asset_ids.clear()
        self.operation_log.clear()
        self.preferences.clear()
