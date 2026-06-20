"""
AssetPool：资产池

所有生成/导入过的模型，不随 regenerate 删除（只增）。
磁盘持久（.glb + metadata.json），可选本地向量索引。

按文档 [后续计划:96-104]，AssetPoolEntry 字段：
  asset_id, local_path, prompt, type, created_at, status
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AssetPoolEntry:
    """资产池条目：一个生成/导入的模型"""
    asset_id: str                    # 唯一 ID（UUID 或 hash）
    local_path: str                  # 磁盘路径（.glb）
    prompt: str                      # 当初用什么 prompt 生成的（支持"再来个类似的"）
    type: str                        # "generated" | "imported" | "builtin"
    created_at: str                  # ISO 8601 时间戳
    status: str = "available"        # "available" | "hidden" | "rejected"

    # 可选：嵌入向量（本地向量检索），M1 不实现
    embedding: Optional[List[float]] = None

    # 可选：元数据（尺寸/标签/来源 workflow_id），M1 预留
    metadata: Dict = field(default_factory=dict)


class AssetPool:
    """资产池：管理所有资产条目

    M1 只实现内存存储 + 基本 CRUD，不实现磁盘持久化/向量检索。
    """
    def __init__(self):
        self._assets: Dict[str, AssetPoolEntry] = {}

    def add(self, entry: AssetPoolEntry) -> None:
        """添加资产（幂等：asset_id 已存在则更新）"""
        self._assets[entry.asset_id] = entry

    def get(self, asset_id: str) -> Optional[AssetPoolEntry]:
        """查询单个资产"""
        return self._assets.get(asset_id)

    def list_available(self) -> List[AssetPoolEntry]:
        """列出所有 status=available 的资产"""
        return [e for e in self._assets.values() if e.status == "available"]

    def mark_rejected(self, asset_id: str) -> None:
        """标记资产为 rejected（用户拒绝）"""
        if asset_id in self._assets:
            self._assets[asset_id].status = "rejected"

    def clear(self) -> None:
        """清空池（M1 测试用，生产环境几乎不调）"""
        self._assets.clear()
