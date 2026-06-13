"""
数据模型：AssetPool / SceneLayout / UserLayer

M1 里程碑：纯数据骨架，不碰引擎，对照探针结论写。
为 M3/M4 的渐进式生成 + 用户介入提供数据基础。
"""
from .asset_pool import AssetPoolEntry, AssetPool
from .layout import LayoutInstance, SceneLayout
from .user_layer import UserLayer

__all__ = [
    "AssetPoolEntry",
    "AssetPool",
    "LayoutInstance",
    "SceneLayout",
    "UserLayer",
]
