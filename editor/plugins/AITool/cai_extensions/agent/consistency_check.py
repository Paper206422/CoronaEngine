"""场景一致性检查（突击方案 §2.3aabb / 后续计划 E5-a/E5-b）。

确定性几何检查，无 API、可复现、快、可单测——防穿模主力。VLM 是外回路、产语义建议；
本模块是内回路、每次摆放都跑、放置前检查→不过就 nudge/夹回→再 commit。

分两层（来源不同，绝不混报，否则误判）：
- E5-a 基础设施层（锚定链 / phase 产物）：shell 落平台 / interior 在 footprint 内 /
  boundary 围对 anchor / connector 通畅。
- E5-b 家具层（compose_scene 布局产物）：AABB 穿模 / 挡门 / 超 Zone / 放错 Zone /
  用户锁定物被移。

纯几何：输入是 {actor_id: AABB}，AABB = [min_x,min_y,min_z, max_x,max_y,max_z]（世界系）。
不 import engine、不读 C++ 对象——调用方负责把引擎 AABB 喂进来。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

AABB = Sequence[float]  # [min_x, min_y, min_z, max_x, max_y, max_z]

# 容差：小于此重叠/间隙视为贴合，不报问题（避免浮点噪声误报）。
EPS = 1e-3
# 穿模判定：两 AABB 的重叠体积占较小体积的比例超过此值才算穿模（轻微接触不算）。
OVERLAP_RATIO = 0.05
# 悬空判定：物体底面离地面高于此值算悬空（米）。
FLOAT_GAP = 0.05


# ── 问题类型 ─────────────────────────────────────────────

ISSUE_FLOATING = "floating"        # 悬空（E5-b）
ISSUE_OVERLAP = "overlap"          # AABB 穿模（E5-b）
ISSUE_BLOCK_DOOR = "block_door"    # 挡门（E5-b）
ISSUE_OUT_OF_ZONE = "out_of_zone"  # 超出 Zone（E5-b）
ISSUE_WRONG_ZONE = "wrong_zone"    # 放错 Zone（E5-b）
ISSUE_USER_MOVED = "user_moved"    # 用户锁定物被移动（E5-b）
ISSUE_SHELL_OFF_PLATFORM = "shell_off_platform"      # shell 没落平台（E5-a）
ISSUE_INTERIOR_OVERFLOW = "interior_overflow"        # 内皮超出 footprint（E5-a）
ISSUE_BOUNDARY_MISMATCH = "boundary_mismatch"        # 边界没围对 anchor（E5-a）


@dataclass
class Issue:
    """一条一致性问题。"""
    kind: str                              # ISSUE_* 之一
    actor_id: str                          # 主体物体
    layer: str                             # "infra"(E5-a) | "furniture"(E5-b)
    detail: str = ""                       # 人读描述
    related_id: Optional[str] = None       # 关联物体（穿模对方 / 门洞 / anchor）
    severity: str = "warn"                 # "warn" | "error"
    suggestion: Optional[Dict] = None      # 可选修正建议（nudge 向量等）


@dataclass
class CheckResult:
    """一次检查的汇总。issues 按 layer 分桶，便于分层排查。"""
    issues: List[Issue] = field(default_factory=list)

    def infra(self) -> List[Issue]:
        return [i for i in self.issues if i.layer == "infra"]

    def furniture(self) -> List[Issue]:
        return [i for i in self.issues if i.layer == "furniture"]

    def is_clean(self) -> bool:
        return not self.issues

    def by_actor(self, actor_id: str) -> List[Issue]:
        return [i for i in self.issues if i.actor_id == actor_id]


# ── 几何原语 ─────────────────────────────────────────────

def _valid(aabb: Optional[AABB]) -> bool:
    return aabb is not None and len(aabb) >= 6


def _volume(a: AABB) -> float:
    dx = max(0.0, a[3] - a[0])
    dy = max(0.0, a[4] - a[1])
    dz = max(0.0, a[5] - a[2])
    return dx * dy * dz


def _overlap_volume(a: AABB, b: AABB) -> float:
    ox = max(0.0, min(a[3], b[3]) - max(a[0], b[0]))
    oy = max(0.0, min(a[4], b[4]) - max(a[1], b[1]))
    oz = max(0.0, min(a[5], b[5]) - max(a[2], b[2]))
    return ox * oy * oz


def _overlap_xz(a: AABB, b: AABB) -> float:
    """XZ 平面重叠面积（门洞遮挡 / footprint 用 — 忽略 y）。"""
    ox = max(0.0, min(a[3], b[3]) - max(a[0], b[0]))
    oz = max(0.0, min(a[5], b[5]) - max(a[2], b[2]))
    return ox * oz


def _contains_xz(outer: AABB, inner: AABB, margin: float = 0.0) -> bool:
    """inner 的 XZ 投影是否落在 outer 的 XZ 投影内（带 margin 收缩）。"""
    return (inner[0] >= outer[0] - margin and inner[2] >= outer[2] - margin
            and inner[3] <= outer[3] + margin and inner[5] <= outer[5] + margin)


# ── E5-b 家具层检查 ──────────────────────────────────────

def check_floating(actor_id: str, aabb: AABB, ground_y: float = 0.0) -> Optional[Issue]:
    """悬空：物体底面离地面高于 FLOAT_GAP。"""
    if not _valid(aabb):
        return None
    gap = aabb[1] - ground_y
    if gap > FLOAT_GAP:
        return Issue(
            kind=ISSUE_FLOATING, actor_id=actor_id, layer="furniture",
            detail=f"底面离地 {gap:.2f}m（悬空）",
            suggestion={"nudge": [0.0, -gap, 0.0]},
        )
    return None


def check_overlaps(aabbs: Dict[str, AABB]) -> List[Issue]:
    """两两 AABB 穿模（重叠体积占较小体积比例 > OVERLAP_RATIO）。"""
    issues: List[Issue] = []
    ids = [i for i in aabbs if _valid(aabbs[i])]
    for idx, a_id in enumerate(ids):
        for b_id in ids[idx + 1:]:
            a, b = aabbs[a_id], aabbs[b_id]
            ov = _overlap_volume(a, b)
            if ov <= EPS:
                continue
            smaller = min(_volume(a), _volume(b))
            if smaller <= EPS:
                continue
            ratio = ov / smaller
            if ratio > OVERLAP_RATIO:
                issues.append(Issue(
                    kind=ISSUE_OVERLAP, actor_id=a_id, related_id=b_id,
                    layer="furniture",
                    detail=f"与 {b_id} 穿模（重叠占比 {ratio:.0%}）",
                    severity="error" if ratio > 0.3 else "warn",
                ))
    return issues


def check_block_door(
    aabbs: Dict[str, AABB],
    door_aabbs: Dict[str, AABB],
) -> List[Issue]:
    """挡门：物体 XZ 投影与门洞 XZ 投影重叠。"""
    issues: List[Issue] = []
    for actor_id, aabb in aabbs.items():
        if not _valid(aabb):
            continue
        for door_id, door in door_aabbs.items():
            if not _valid(door):
                continue
            if _overlap_xz(aabb, door) > EPS:
                issues.append(Issue(
                    kind=ISSUE_BLOCK_DOOR, actor_id=actor_id, related_id=door_id,
                    layer="furniture", severity="error",
                    detail=f"挡住门洞 {door_id}",
                ))
    return issues


def check_out_of_zone(
    aabbs: Dict[str, AABB],
    zone_aabb: AABB,
    zone_id: str = "zone",
    margin: float = 0.0,
) -> List[Issue]:
    """超出 Zone：物体 XZ 投影越过 zone 体积边界。"""
    issues: List[Issue] = []
    if not _valid(zone_aabb):
        return issues
    for actor_id, aabb in aabbs.items():
        if not _valid(aabb):
            continue
        if not _contains_xz(zone_aabb, aabb, margin):
            issues.append(Issue(
                kind=ISSUE_OUT_OF_ZONE, actor_id=actor_id, related_id=zone_id,
                layer="furniture",
                detail=f"越出 Zone {zone_id} 边界",
            ))
    return issues


def check_user_moved(
    current: Dict[str, AABB],
    locked_snapshot: Dict[str, AABB],
) -> List[Issue]:
    """用户锁定物被移动：锁定快照与当前 AABB 中心偏移超容差。"""
    issues: List[Issue] = []
    for actor_id, snap in locked_snapshot.items():
        cur = current.get(actor_id)
        if not _valid(cur) or not _valid(snap):
            continue
        cdx = abs((cur[0] + cur[3]) - (snap[0] + snap[3])) / 2.0
        cdz = abs((cur[2] + cur[5]) - (snap[2] + snap[5])) / 2.0
        if cdx > EPS or cdz > EPS:
            issues.append(Issue(
                kind=ISSUE_USER_MOVED, actor_id=actor_id, layer="furniture",
                severity="error",
                detail=f"用户锁定物被移动（Δx={cdx:.2f} Δz={cdz:.2f}）",
            ))
    return issues


# ── E5-a 基础设施层检查 ──────────────────────────────────

def check_shell_on_platform(
    shell_id: str, shell_aabb: AABB, platform_y: float = 0.0,
    tol: float = 0.1,
) -> Optional[Issue]:
    """shell 底面是否落在平台 y 上（不悬空、不埋地）。"""
    if not _valid(shell_aabb):
        return None
    gap = abs(shell_aabb[1] - platform_y)
    if gap > tol:
        return Issue(
            kind=ISSUE_SHELL_OFF_PLATFORM, actor_id=shell_id, layer="infra",
            severity="error",
            detail=f"外壳底面偏离平台 {gap:.2f}m",
            suggestion={"nudge": [0.0, platform_y - shell_aabb[1], 0.0]},
        )
    return None


def check_interior_within_footprint(
    interior_id: str, interior_aabb: AABB, shell_footprint: AABB,
    margin: float = 0.05,
) -> Optional[Issue]:
    """内皮地面是否在 shell footprint 内（不溢出露缝）。"""
    if not _valid(interior_aabb) or not _valid(shell_footprint):
        return None
    if not _contains_xz(shell_footprint, interior_aabb, margin):
        return Issue(
            kind=ISSUE_INTERIOR_OVERFLOW, actor_id=interior_id, layer="infra",
            detail="内皮地面溢出外壳足迹",
        )
    return None


def check_boundary_around_anchor(
    boundary_id: str, boundary_aabb: AABB, anchor_aabb: AABB,
) -> Optional[Issue]:
    """边界（栅栏）是否围住 anchor（anchor footprint 应落在 boundary 内）。"""
    if not _valid(boundary_aabb) or not _valid(anchor_aabb):
        return None
    if not _contains_xz(boundary_aabb, anchor_aabb, margin=0.0):
        return Issue(
            kind=ISSUE_BOUNDARY_MISMATCH, actor_id=boundary_id, layer="infra",
            related_id=None,
            detail="边界未围住锚点物体",
        )
    return None


# ── 汇总入口 ─────────────────────────────────────────────

def run_furniture_checks(
    aabbs: Dict[str, AABB],
    *,
    ground_y: float = 0.0,
    zone_aabb: Optional[AABB] = None,
    zone_id: str = "zone",
    door_aabbs: Optional[Dict[str, AABB]] = None,
    locked_snapshot: Optional[Dict[str, AABB]] = None,
    zone_margin: float = 0.0,
) -> CheckResult:
    """E5-b 家具层全套检查。"""
    result = CheckResult()
    for actor_id, aabb in aabbs.items():
        fi = check_floating(actor_id, aabb, ground_y)
        if fi:
            result.issues.append(fi)
    result.issues.extend(check_overlaps(aabbs))
    if door_aabbs:
        result.issues.extend(check_block_door(aabbs, door_aabbs))
    if zone_aabb is not None:
        result.issues.extend(check_out_of_zone(aabbs, zone_aabb, zone_id, zone_margin))
    if locked_snapshot:
        result.issues.extend(check_user_moved(aabbs, locked_snapshot))
    return result


def reasonable_map_from_result(
    result: CheckResult, actor_ids: Sequence[str],
) -> Dict[str, bool]:
    """把检查结果转成 {actor_id: 是否合理}，喂给 §2.2 近因加权保护。

    某 actor 触发任意 error 级问题 → 不合理（False，允许被整体重排覆盖）；
    无 error → 合理（True，至少 SOFT 保护）。

    注意：穿模/挡门这类 error 同时牵连双方（actor_id + related_id），两边都要标
    不合理——否则\"被穿模的另一方\"会逃过保护降级。
    """
    bad: set = set()
    for i in result.issues:
        if i.severity != "error":
            continue
        bad.add(i.actor_id)
        if i.related_id:
            bad.add(i.related_id)
    return {aid: (aid not in bad) for aid in actor_ids}


__all__ = [
    "AABB", "Issue", "CheckResult",
    "ISSUE_FLOATING", "ISSUE_OVERLAP", "ISSUE_BLOCK_DOOR", "ISSUE_OUT_OF_ZONE",
    "ISSUE_WRONG_ZONE", "ISSUE_USER_MOVED", "ISSUE_SHELL_OFF_PLATFORM",
    "ISSUE_INTERIOR_OVERFLOW", "ISSUE_BOUNDARY_MISMATCH",
    "check_floating", "check_overlaps", "check_block_door", "check_out_of_zone",
    "check_user_moved", "check_shell_on_platform",
    "check_interior_within_footprint", "check_boundary_around_anchor",
    "run_furniture_checks", "reasonable_map_from_result",
]
