"""轮询式视口 scene-diff（突击方案 §2.1 路 A — 命门解法）。

命门背景：引擎→Python **没有** actor 变换事件（actor.py 只有创建时 _broadcast_actor_created，
没有\"用户视口拖动→通知 Python\"的反向事件）。所以用户自己在视口拖拽/缩放/删除，
G老师 spec 的 record_user_op 没有调用者。

路 A 解法（零 C++、零前端）：在每个 phase 边界对全场 actor 的 transform 拍快照，
与上一张 diff。变了→touched_by_user；消失→user_deleted；新增→provenance=USER。
代价：不是实时，是 phase 间粒度——但渐进生成本就在 phase 间 yield，体感够。

纯逻辑：输入是 {actor_id: transform_tuple}，由调用方从引擎 scene.get_actors() +
actor.get_position/scale/rotation 采集喂进来。本模块不 import engine。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# 变换快照：每个 actor 记 (pos, rot, scale)，各为 3 元组。
Transform = Tuple[Tuple[float, float, float],
                  Tuple[float, float, float],
                  Tuple[float, float, float]]
Snapshot = Dict[str, Transform]

# 判定阈值：中心/缩放/旋转变化小于此视为未动（避免浮点噪声误报为用户介入）。
POS_EPS = 1e-3
SCALE_EPS = 1e-3
ROT_EPS = 1e-2   # 度

# diff 事件类型
DIFF_MOVED = "moved"        # transform 变了（用户拖拽/缩放/旋转）
DIFF_ADDED = "added"        # 新出现的 actor（用户新增）
DIFF_DELETED = "deleted"    # 消失的 actor（用户删除）


@dataclass
class DiffEvent:
    """一次视口介入事件。"""
    kind: str               # DIFF_*
    actor_id: str
    detail: str = ""
    changed: List[str] = field(default_factory=list)  # ["pos","scale","rot"] 中变了的项


def _t3(v: Optional[Sequence[float]]) -> Tuple[float, float, float]:
    """规整成 3 元组（容错：缺省 0/1）。"""
    if v is None:
        return (0.0, 0.0, 0.0)
    try:
        return (float(v[0]), float(v[1]), float(v[2]))
    except Exception:  # noqa: BLE001
        return (0.0, 0.0, 0.0)


def make_transform(pos: Sequence[float], rot: Sequence[float],
                   scale: Sequence[float]) -> Transform:
    """从引擎采集的 pos/rot/scale 构造规范化快照条目。"""
    return (_t3(pos), _t3(rot), _t3(scale))


def _max_delta(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def diff_snapshots(prev: Snapshot, cur: Snapshot) -> List[DiffEvent]:
    """对比两张快照，产出视口介入事件列表。

    - cur 有 prev 没有 → ADDED（用户新增）
    - prev 有 cur 没有 → DELETED（用户删除）
    - 都有但 transform 变了 → MOVED（用户拖拽/缩放/旋转）

    阈值过滤浮点噪声；MOVED 事件标出具体变了哪几项（pos/scale/rot）。
    """
    events: List[DiffEvent] = []
    prev_ids = set(prev)
    cur_ids = set(cur)

    for aid in cur_ids - prev_ids:
        events.append(DiffEvent(kind=DIFF_ADDED, actor_id=aid, detail="新增 actor"))
    for aid in prev_ids - cur_ids:
        events.append(DiffEvent(kind=DIFF_DELETED, actor_id=aid, detail="删除 actor"))
    for aid in prev_ids & cur_ids:
        (ppos, prot, pscale) = prev[aid]
        (cpos, crot, cscale) = cur[aid]
        changed: List[str] = []
        if _max_delta(ppos, cpos) > POS_EPS:
            changed.append("pos")
        if _max_delta(pscale, cscale) > SCALE_EPS:
            changed.append("scale")
        if _max_delta(prot, crot) > ROT_EPS:
            changed.append("rot")
        if changed:
            events.append(DiffEvent(
                kind=DIFF_MOVED, actor_id=aid, changed=changed,
                detail="用户改了 " + "/".join(changed),
            ))
    return events


class SceneDiffTracker:
    """跨 phase 边界维护快照，每次 poll 产出自上次以来的视口介入事件。

    持有上一张快照；调用方在 phase 边界采集当前全场 transform → poll(cur) →
    得到 DiffEvent 列表 → 据此调 SceneLayout.mark_user_intervention / 标 deleted。
    """

    def __init__(self) -> None:
        self._last: Snapshot = {}
        # 基线：渐进生成自己导入的 actor 不应被误判为\"用户新增\"。
        # 调用方在 import 后调 baseline_add 把 agent 导入的 actor 纳入基线。
        self._agent_known: set = set()

    def set_baseline(self, snapshot: Snapshot) -> None:
        """重置基线（compose 开始时调；之后的 diff 都相对此基线增量算）。"""
        self._last = dict(snapshot)
        self._agent_known = set(snapshot)

    def baseline_add(self, actor_ids: Sequence[str], snapshot: Snapshot) -> None:
        """把 agent 刚导入的 actor 纳入基线，避免下次 poll 误判为用户新增。"""
        for aid in actor_ids:
            self._agent_known.add(aid)
            if aid in snapshot:
                self._last[aid] = snapshot[aid]

    def poll(self, cur: Snapshot) -> List[DiffEvent]:
        """对比当前快照与上一张，产出事件并更新基线。

        ADDED 事件中，若 actor 是 agent 刚导入的（在 _agent_known 里）→ 过滤掉
        （那是 agent 自己加的，不是用户介入）。
        """
        events = diff_snapshots(self._last, cur)
        filtered: List[DiffEvent] = []
        for ev in events:
            if ev.kind == DIFF_ADDED and ev.actor_id in self._agent_known:
                continue  # agent 自己导入的，非用户新增
            filtered.append(ev)
        self._last = dict(cur)
        return filtered


__all__ = [
    "Transform", "Snapshot", "DiffEvent",
    "DIFF_MOVED", "DIFF_ADDED", "DIFF_DELETED",
    "make_transform", "diff_snapshots", "SceneDiffTracker",
]
