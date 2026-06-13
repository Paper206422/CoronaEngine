"""
ZoneTree：空间树数据结构

M2 步骤 2：单 Zone 退化形态（enclosure=box），把现有 room_box 逻辑重新表达成 Zone。
M2 步骤 14：两层 Zone 嵌套（草原 + 蒙古包内部 + 门洞）。
M2 步骤 15：dressing_assets + interior_skin 参数化。

按文档 [后续计划:328-339]，Zone 字段：
  zone_id, name, role, volume, enclosure, primary_shell_asset_id,
  dressing_assets, interior_skin, objects, sub_zones, connectors
"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Volume:
    """参数化空间体积（唯一事实源，我们自己造、可控、能留门洞）"""
    center: List[float]              # [x, y, z] 中心点
    size: List[float]                # [width, depth, height] 尺寸
    rotation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])  # [rx, ry, rz] 旋转


@dataclass
class InteriorSkin:
    """参数化内皮：进去后的墙地顶（不是模型，是程序生成）

    M2 步骤 2 暂不实现，步骤 15 再补。
    """
    floor_material: str = "default"
    wall_material: str = "default"
    ceiling_material: str = "default"
    openings: List[Dict] = field(default_factory=list)  # 门洞/窗户位置


@dataclass
class Connector:
    """门洞/通道：连接父子 Zone，camera 由此穿越

    M2 步骤 2 暂不实现，步骤 14 再补。
    """
    connector_id: str
    type: str                        # "door" | "window" | "passage"
    position: List[float]            # [x, y, z] 在父 Zone 的位置
    size: List[float]                # [width, height] 门洞尺寸
    target_zone_id: Optional[str] = None  # 连到哪个子 Zone


@dataclass
class Zone:
    """Zone：递归空间结构节点

    M2 步骤 2：单 Zone + enclosure=box（退化形态，重表达现有 room_box）。
    M2 步骤 14：支持两层嵌套（外 Zone + 内 Zone + 门洞）。
    """
    zone_id: str                     # 唯一 ID
    name: str                        # 人类可读名（"草原"/"蒙古包内部"）
    role: str                        # "outdoor" | "indoor" | "connector"

    # 空间体积（唯一事实源）
    volume: Volume

    # 包裹方式（M2 步骤 2 只实现 box，步骤 14 加 terrain/shell）
    enclosure: str = "box"           # "none" | "terrain" | "box" | "shell"

    # 外壳（M2 步骤 15 实现）
    primary_shell_asset_id: Optional[str] = None  # 主外壳 asset_id（教堂/蒙古包）
    dressing_assets: List[str] = field(default_factory=list)  # 附加外部装饰 asset_id

    # 内皮（M2 步骤 15 实现）
    interior_skin: Optional[InteriorSkin] = None

    # 递归结构（M2 步骤 14 实现）
    sub_zones: List["Zone"] = field(default_factory=list)
    connectors: List[Connector] = field(default_factory=list)

    # 物体（引用 LayoutInstance，M2 步骤 2 暂不填充）
    objects: List[str] = field(default_factory=list)  # [instance_id]

    # 元数据（M2 预留）
    metadata: Dict = field(default_factory=dict)


class ZoneTree:
    """ZoneTree：管理 Zone 树

    M2 步骤 2：只有根 Zone，退化成现在的单盒子场景。
    M2 步骤 14：支持两层嵌套。
    """
    def __init__(self, root: Zone):
        self.root = root

    def get_zone(self, zone_id: str) -> Optional[Zone]:
        """递归查找 Zone（DFS）"""
        return self._dfs_find(self.root, zone_id)

    def _dfs_find(self, node: Zone, target_id: str) -> Optional[Zone]:
        if node.zone_id == target_id:
            return node
        for child in node.sub_zones:
            found = self._dfs_find(child, target_id)
            if found:
                return found
        return None

    def list_all_zones(self) -> List[Zone]:
        """列出所有 Zone（先序遍历）"""
        result = []
        self._dfs_collect(self.root, result)
        return result

    def _dfs_collect(self, node: Zone, result: List[Zone]):
        result.append(node)
        for child in node.sub_zones:
            self._dfs_collect(child, result)
