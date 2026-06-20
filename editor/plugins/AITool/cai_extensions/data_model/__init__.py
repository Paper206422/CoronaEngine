"""
数据模型：AssetPool / SceneLayout / UserLayer / ZoneTree

M1：AssetPool/SceneLayout/UserLayer + provenance 7 字段
M2：ZoneTree（室内外混合 + 多 Zone 嵌套）
"""
from .asset_pool import AssetPoolEntry, AssetPool
from .layout import LayoutInstance, SceneLayout
from .user_layer import UserLayer
from .zone_tree import (
    CAPABILITY_MANIFEST,
    GENERATOR_MANIFEST,
    Zone,
    ZoneAspect,
    ZoneTree,
    Volume,
    InteriorSkin,
    Connector,
    TerrainProfile,
)

__all__ = [
    "AssetPoolEntry",
    "AssetPool",
    "LayoutInstance",
    "SceneLayout",
    "UserLayer",
    "CAPABILITY_MANIFEST",
    "GENERATOR_MANIFEST",
    "Zone",
    "ZoneAspect",
    "ZoneTree",
    "Volume",
    "InteriorSkin",
    "Connector",
    "TerrainProfile",
]
