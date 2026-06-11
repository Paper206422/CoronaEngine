"""Constraint Solver — 将 LLM 语义关系转为精确坐标。

6 个核心关系:
  against_wall    — 贴墙 (大件锚定)
  in_front        — 在前方
  near_anchor     — 锚点侧边
  on_surface      — 放在表面上
  center_under_group — 居中到组合下方
  between         — 两点之间

输入: LLM 输出的关系列表 + 已放置物体的 position/bbox
输出: 计算后的精确坐标 [x, y, z]
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 房间边界: wall → (axis, sign)  — axis=0 means X, axis=2 means Z
_WALL_DEFS = {
    "back":  (2, +1),   # +Z
    "front": (2, -1),   # -Z
    "left":  (0, -1),   # -X
    "right": (0, +1),   # +X
}

_SIDE_OFFSETS = {"left": -1, "right": +1}


def _get_half_size(
    name: str,
    scale: List[float],
    asset_meta: Dict[str, Any],
) -> Tuple[float, float, float]:
    """获取物体半尺寸 (half_x, half_y, half_z)。优先 metadata, 回退 scale 估算。"""
    meta = asset_meta.get(name, {})
    if meta and meta.get("size"):
        s = meta["size"]
        return s[0] / 2, s[1] / 2, s[2] / 2
    # fallback: scale * 0.45m default
    sc = scale or [1, 1, 1]
    return 0.45 * sc[0], 0.50 * sc[1], 0.45 * sc[2]


def _get_placed(name: str, placed: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从已放置字典中查找物体 (case-insensitive)。"""
    if name in placed:
        return placed[name]
    name_lower = name.lower()
    for k, v in placed.items():
        if k.lower() == name_lower:
            return v
    return None


# ═══════════════════════════════════════════════════════════════════════════
# 6 个核心求解函数
# ═══════════════════════════════════════════════════════════════════════════

def solve_against_wall(
    obj_name: str,
    wall: str,
    offset: float = 0.5,
    *,
    placed: Dict[str, Any],
    room_size: List[float],
    asset_meta: Dict[str, Any],
    obj_scale: List[float] = None,
    offset_along: float = 0.0,
    **kwargs,
) -> List[float]:
    """贴墙放置。wall: back/front/left/right。offset: 距墙距离(m)。
    offset_along: 沿墙偏移 (正=右/后, 负=左/前), 避免全部居中堆叠。
    """
    x_half = room_size[0] / 2
    z_half = (room_size[1] / 2) if len(room_size) > 1 else 1.5
    sc = obj_scale or [1, 1, 1]
    hx, hy, hz = _get_half_size(obj_name, sc, asset_meta)

    if wall not in _WALL_DEFS:
        return [0, 0, 0]

    axis, sign = _WALL_DEFS[wall]
    half_range = x_half if axis == 0 else z_half

    pos = [0.0, 0.0, 0.0]
    pos[axis] = sign * (half_range - hx - offset)
    pos[1] = 0  # floor

    # 沿墙偏移: axis=0(Z墙)时沿X偏移, axis=2(X墙)时沿Z偏移
    along_axis = 2 if axis == 0 else 0
    pos[along_axis] = offset_along
    return [round(pos[0], 3), round(pos[1], 3), round(pos[2], 3)]


def solve_in_front(
    obj_name: str,
    target_name: str,
    distance: float = 0.7,
    *,
    placed: Dict[str, Any],
    asset_meta: Dict[str, Any],
    obj_scale: List[float] = None,
    **kwargs,
) -> Optional[List[float]]:
    """放在 target 正前方 (target 的 facing 方向)。"""
    tgt = _get_placed(target_name, placed)
    if not tgt:
        return None
    tgt_pos = tgt["pos"]
    tgt_scale = tgt.get("scale", [1, 1, 1])
    sc = obj_scale or [1, 1, 1]
    _, _, thz = _get_half_size(target_name, tgt_scale, asset_meta)
    _, _, ohz = _get_half_size(obj_name, sc, asset_meta)

    # 默认 facing = -Z (rot 0) → front = -Z
    z = tgt_pos[2] - thz - distance - ohz
    return [round(tgt_pos[0], 3), 0.0, round(z, 3)]


def solve_near_anchor(
    obj_name: str,
    anchor_name: str,
    side: str = "right",
    distance: float = 0.3,
    *,
    placed: Dict[str, Any],
    asset_meta: Dict[str, Any],
    obj_scale: List[float] = None,
    **kwargs,
) -> Optional[List[float]]:
    """放在 anchor 侧边。side: left/right。"""
    anchor = _get_placed(anchor_name, placed)
    if not anchor:
        return None
    ap = anchor["pos"]
    asc = anchor.get("scale", [1, 1, 1])
    sc = obj_scale or [1, 1, 1]
    ahx, _, _ = _get_half_size(anchor_name, asc, asset_meta)
    ohx, _, _ = _get_half_size(obj_name, sc, asset_meta)

    sign = _SIDE_OFFSETS.get(side, 1)
    x = ap[0] + sign * (ahx + distance + ohx)
    return [round(x, 3), 0.0, round(ap[2], 3)]


def solve_on_surface(
    obj_name: str,
    surface_name: str,
    *,
    placed: Dict[str, Any],
    asset_meta: Dict[str, Any],
    obj_scale: List[float] = None,
    **kwargs,
) -> Optional[List[float]]:
    """放在 surface 顶面上。"""
    surf = _get_placed(surface_name, placed)
    if not surf:
        return None
    sp = surf["pos"]
    ssc = surf.get("scale", [1, 1, 1])
    _, shy, _ = _get_half_size(surface_name, ssc, asset_meta)
    # surface top Y = pos_y + half_height
    surface_top_y = sp[1] + shy * 2

    return [round(sp[0], 3), round(surface_top_y, 3), round(sp[2], 3)]


def solve_center_under_group(
    obj_name: str,
    group_names: List[str],
    *,
    placed: Dict[str, Any],
    obj_scale: List[float] = None,
    **kwargs,
) -> Optional[List[float]]:
    """放在一组物体的中心下方 (如地毯)。"""
    if not group_names:
        return None
    cx, cz = 0.0, 0.0
    count = 0
    for name in group_names:
        tgt = _get_placed(name, placed)
        if tgt:
            cx += tgt["pos"][0]
            cz += tgt["pos"][2]
            count += 1
    if count == 0:
        return None
    return [round(cx / count, 3), 0.01, round(cz / count, 3)]


def solve_between(
    obj_name: str,
    a_name: str,
    b_name: str,
    *,
    placed: Dict[str, Any],
    obj_scale: List[float] = None,
    **kwargs,
) -> Optional[List[float]]:
    """放在 a 和 b 的中点。"""
    a = _get_placed(a_name, placed)
    b = _get_placed(b_name, placed)
    if not a or not b:
        return None
    return [
        round((a["pos"][0] + b["pos"][0]) / 2, 3),
        0.0,
        round((a["pos"][2] + b["pos"][2]) / 2, 3),
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Relative Scale Normalizer
# ═══════════════════════════════════════════════════════════════════════════

# 相对比例规则: target_height = reference_height × ratio
_RELATIVE_SCALE_RULES = {
    "on_surface": 0.6,     # 台灯/摆件 = 承载物高度 × 0.6
    "near_anchor": 1.5,    # 落地灯 = 锚点高度 × 1.5
    "floor_surface": None, # 地毯: 用宽度规则单独处理
    "large_anchor": 1.0,   # 大件保持模型原始比例
}

# 地毯: target_width = group_width × ratio
_RUG_WIDTH_RATIO = 1.3
_RUG_DEPTH_RATIO = 1.3


def normalize_relative_scale(
    obj_name: str,
    obj_meta: Dict[str, Any],
    context: Dict[str, Any],
) -> Optional[List[float]]:
    """根据相对比例规则计算目标 scale。

    obj_meta: asset_metadata 中的 bbox 数据
    context: {"placement_type": str, "reference_height": float, "group_width": float, ...}
    返回 [sx, sy, sz] 或 None (保持原 scale)
    """
    ptype = obj_meta.get("placement_type", "large_anchor")
    raw_size = obj_meta.get("size", [1, 1, 1])
    raw_height = raw_size[1] if raw_size[1] > 0.001 else 1.0
    raw_width = raw_size[0]
    raw_depth = raw_size[2]

    if ptype == "floor_surface":
        # 地毯: 相对 group 宽深
        gw = context.get("group_width", 2.0)
        gd = context.get("group_depth", 2.0)
        sx = (gw * _RUG_WIDTH_RATIO) / raw_width if raw_width > 0.001 else 2.0
        sz = (gd * _RUG_DEPTH_RATIO) / raw_depth if raw_depth > 0.001 else 1.5
        sy = 0.02 / raw_height if raw_height > 0.001 else 1.0
        return [round(max(0.5, min(4.0, sx)), 2),
                round(max(0.01, min(2.0, sy)), 2),
                round(max(0.5, min(4.0, sz)), 2)]

    # 高度类规则
    ratio = _RELATIVE_SCALE_RULES.get(ptype, 1.0)
    if ratio is None:
        return None

    ref_height = context.get("reference_height", raw_height)
    target_height = ref_height * ratio

    uniform_scale = target_height / raw_height if raw_height > 0.001 else ratio
    uniform_scale = max(0.15, min(3.0, uniform_scale))
    us = round(uniform_scale, 2)
    return [us, us, us]


# ═══════════════════════════════════════════════════════════════════════════
# 调度器
# ═══════════════════════════════════════════════════════════════════════════

_SOLVERS = {
    "against_wall":       solve_against_wall,
    "in_front":           solve_in_front,
    "near_anchor":        solve_near_anchor,
    "on_surface":         solve_on_surface,
    "center_under_group": solve_center_under_group,
    "between":            solve_between,
}


def solve_relations(
    relations: List[Dict[str, Any]],
    room_size: List[float],
    asset_meta: Dict[str, Any],
    placed: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Dict[str, Any]]:
    """批量求解语义关系。返回 {object_id: {pos, rot, scale}}。

    relations: [{"object_id":"sofa","relation":"against_wall","target":"back",...}, ...]
    执行顺序: wall→anchor→in_front→near→on_surface→group→between (拓扑保证)
    """
    if placed is None:
        placed = {}

    # 拓扑排序: 先求解不依赖其他物体的 (against_wall)
    order = sorted(relations, key=lambda r: _relation_priority(r.get("relation", "")))

    for rel in order:
        oid = rel.get("object_id", "")
        relation = rel.get("relation", "")
        solver = _SOLVERS.get(relation)
        if not solver:
            logger.warning("[solver] 未知关系: %s for %s", relation, oid)
            continue

        obj_scale = rel.get("scale", [1, 1, 1])
        kwargs = {
            "placed": placed,
            "asset_meta": asset_meta,
            "obj_scale": obj_scale,
            "room_size": room_size,
        }

        try:
            if relation == "against_wall":
                wall_offset = max(0.2, min(1.0, rel.get("offset", 0.5)))
                along = max(-2.5, min(2.5, rel.get("offset_along", 0.0)))
                pos = solver(oid, rel.get("target", "back"),
                             offset=wall_offset, offset_along=along, **kwargs)
            elif relation == "in_front":
                dist = max(0.3, min(2.0, rel.get("distance", 0.7)))
                pos = solver(oid, rel.get("target", ""), distance=dist, **kwargs)
            elif relation == "near_anchor":
                pos = solver(oid, rel.get("target", ""),
                             side=rel.get("side", "right"),
                             distance=rel.get("distance", 0.3), **kwargs)
            elif relation == "on_surface":
                pos = solver(oid, rel.get("target", ""), **kwargs)
            elif relation == "center_under_group":
                pos = solver(oid, rel.get("targets", []), **kwargs)
            elif relation == "between":
                pos = solver(oid, rel.get("target_a", ""),
                             rel.get("target_b", ""), **kwargs)
            else:
                pos = None

            if pos is None:
                logger.warning("[solver] %s %s 求解失败 (target 未找到?)", oid, relation)
                continue

            placed[oid] = {
                "pos": pos,
                "rot": rel.get("rotation", [0, 0, 0]),
                "scale": obj_scale,
            }
        except Exception as e:
            logger.warning("[solver] %s 求解异常: %s", oid, e)

    return placed


def _relation_priority(relation: str) -> int:
    """拓扑优先级: 先求解不依赖其他的。"""
    return {
        "against_wall": 0,
        "center_under_group": 5,
        "between": 5,
        "in_front": 2,
        "near_anchor": 3,
        "on_surface": 4,
    }.get(relation, 10)
