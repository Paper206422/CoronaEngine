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

# 近因加权保护档位（突击方案 §2.2）。不是布尔"碰过即永久锁死"，
# 而是按"用户介入的近因 + 介入结果是否合理"分三档。
PROTECTION_HARD = "HARD"   # 最近 1-2 轮介入：强保护，settlement/重排绝不自动碰
PROTECTION_SOFT = "SOFT"   # 早期但合理：尽量保留，与新目标冲突时可让位
PROTECTION_NONE = "NONE"   # 早期且不合理：允许被新的整体场景目标覆盖

# "最近"窗口：current_round - RECENT_WINDOW 之后的介入算强保护。
RECENT_WINDOW = 1


def protection_level(
    instance: "LayoutInstance",
    current_round: int,
    reasonable: bool = True,
) -> str:
    """计算实例的保护强度（突击方案 §2.2 的机读实现）。

    - 用户从未介入（intervention_round < 0）→ NONE（纯 AGENT，可自由调整）。
    - 最近 1-2 轮介入 → HARD（强保护，无论合理与否——尊重最新明确意图）。
    - 早期介入 + 合理（E5 几何检查通过）→ SOFT（尽量保留，冲突可让位）。
    - 早期介入 + 不合理（穿模/挡门/超 Zone/悬空）→ NONE（允许被整体重排覆盖）。

    reasonable 由功能② 的 E5-a/E5-b 几何检查产出（突击方案 §2.3）；
    取不到检查结果时默认 True（保守：早期介入默认 SOFT 而非可覆盖）。
    """
    r = getattr(instance, "intervention_round", -1)
    if r is None or r < 0:
        return PROTECTION_NONE
    if r >= current_round - RECENT_WINDOW:
        return PROTECTION_HARD
    return PROTECTION_SOFT if reasonable else PROTECTION_NONE


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

    # 近因加权保护（突击方案 §2.2）：用户在第几轮介入了这个实例。
    # -1 = 从未被用户介入（纯 AGENT）；>=0 = 用户最后一次介入时的 session 轮次。
    # 配合 SceneSession.current_round 计算保护强度——不是"碰过就永久锁死"，
    # 而是"最近 1-2 轮强保护、早期+不合理介入允许被整体重排覆盖"。
    intervention_round: int = -1

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

    def list_settleable(
        self,
        current_batch_id: Optional[str],
        current_round: int,
        reasonable_map: Optional[Dict[str, bool]] = None,
    ) -> List[LayoutInstance]:
        """settlement 缩范围（突击方案 §B4 + §2.2）：只返回可被自动沉降/重排的实例。

        条件全满足才可 settle：
          - provenance == AGENT（用户物体不无差别沉降）
          - protection_level != HARD（最近 1-2 轮的用户介入绝不碰）
          - batch_id == current_batch（不对历史批次无差别沉降）

        reasonable_map: {instance_id: 该实例介入是否合理}（由 E5 几何检查产出）；
        缺省时所有实例视为合理（早期介入默认 SOFT，不会被覆盖）。
        """
        reasonable_map = reasonable_map or {}
        result: List[LayoutInstance] = []
        for inst in self._instances.values():
            if inst.layout_status != "active":
                continue
            reasonable = reasonable_map.get(inst.instance_id, True)
            level = protection_level(inst, current_round, reasonable)
            if level == PROTECTION_HARD:
                continue  # 最近用户介入：强保护，绝不自动碰
            if inst.provenance == "AGENT" and inst.batch_id == current_batch_id:
                result.append(inst)  # 本批 AGENT 物体：可沉降
            elif level == PROTECTION_NONE and inst.provenance == "USER":
                result.append(inst)  # 早期+不合理用户介入：允许被整体重排覆盖
        return result

    def mark_user_intervention(
        self,
        instance_id: str,
        current_round: int,
        lock_level: str = "HARD",
    ) -> None:
        """记录一次用户介入（视口拖拽 / AI 工具代用户操作）。

        打 provenance=USER + touched_by_user + 记录介入轮次（近因加权用）。
        近因强保护靠 intervention_round + current_round 计算，lock_level 作冗余标记。
        """
        inst = self._instances.get(instance_id)
        if inst is None:
            return
        inst.provenance = "USER"
        inst.touched_by_user = True
        inst.intervention_round = int(current_round)
        inst.lock_level = lock_level

    def clear(self) -> None:
        """清空布局（M1 测试用）"""
        self._instances.clear()
