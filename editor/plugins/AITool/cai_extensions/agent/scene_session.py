"""SceneSession 运行时（突击方案 §2.1 / §2.5 — 渐进生成 + 随时介入 + FinalReview）。

定位：一次场景生成会话的协同核心。把已建的几块串起来：
  SceneLayout（唯一事实源）+ SceneDiffTracker（视口介入捕获）+
  consistency_check（防穿模/合理性）+ EngineWriteGate（写入收口）+
  incremental_import（只 add 不 clear）。

核心机制（突击方案 §2.1 路 B 决策）：**phase 边界交错**，不做真抢占。
  PHASE_ORDER 每个 phase 末是天然的 yield 点 / 介入 drain 点 / 快照点。
  生成在 phase 间 yield → drain 介入队列（AI 工具 + 视口 diff）→ 防抖懒重建 →
  settle 只碰本批 AGENT → 下一 phase。最后 FinalReview 只修 AGENT。

近因加权保护（突击方案 §2.2）：current_round 每轮自增；用户介入记 intervention_round。
  最近 1-2 轮强保护（HARD），早期+合理 SOFT，早期+不合理 NONE（可被整体重排覆盖）。

设计：纯编排逻辑，引擎相关全部依赖注入（import_tool/engine_gate/采集回调），
便于离线测——不在本模块 import engine。
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# 阶段固定顺序（= 锚定链时序 = 渐进 yield 点 = 回滚/快照粒度，三者共用同一组切分）。
PHASE_ORDER = ["GROUND", "SHELL", "INTERIOR", "BOUNDARY", "OBJECTS", "DECORATION"]

# phase → 用户可读进度文案（中性模板，不写场景身份；具体对象名由调用方填充）。
PHASE_PROGRESS = {
    "GROUND": "正在生成地形…",
    "SHELL": "正在放置主体建筑…",
    "INTERIOR": "正在生成内部…",
    "BOUNDARY": "正在铺设边界…",
    "DECORATION": "正在点缀装饰…",
    "OBJECTS": "正在摆放物体…",
}

# 介入操作类型（突击方案 §B3）
OP_ADD = "USER_ADD"
OP_DELETE = "USER_DELETE"
OP_MOVE = "USER_MOVE"
OP_SCALE = "USER_SCALE"
OP_ROTATE = "USER_ROTATE"
OP_COLOR = "USER_COLOR"


@dataclass
class InterventionOp:
    """一条介入操作（视口 diff 或 AI 工具代用户操作，统一进队列）。"""
    actor_id: str
    op_type: str
    source: str = "viewport"          # "viewport"(用户拖拽) | "ai_tool"(AI助手代操作)
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationLogEntry:
    """用户/Agent/系统操作账本条目。

    这是 SceneState 的解释层，不代替 SceneLayout。后续 GM/多人同步从这里取
    provenance、最近操作与确认依据。
    """
    op_id: str
    round_id: int
    timestamp: float
    source: str
    op_type: str
    actor_id: Optional[str] = None
    user_id: Optional[str] = None
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    intent_text: Optional[str] = None


@dataclass
class FinalReviewReport:
    """FinalReview 三分桶结果（突击方案 §2.5）。"""
    preserved: List[str] = field(default_factory=list)        # HARD/近因强保护用户物体：只检查不动
    adjusted: List[str] = field(default_factory=list)         # AGENT 物体：自动 nudge/让位
    needs_confirm: List[Dict[str, str]] = field(default_factory=list)  # 早期+不合理用户物体：报告问用户

    def to_user_text(self) -> str:
        """生成给用户的自然语言报告（不是日志）。"""
        lines: List[str] = []
        if self.preserved:
            lines.append("已保留你最近的调整：" + "、".join(self.preserved[:5]) + "。")
        if self.adjusted:
            lines.append("系统自动调整了：" + "、".join(self.adjusted[:5]) + "。")
        for nc in self.needs_confirm:
            lines.append(f"需要你确认：{nc.get('detail', nc.get('actor_id', ''))}，是否允许我重新安排？")
        return "\n".join(lines) if lines else "场景已就绪，未发现需要调整的冲突。"


class SceneSession:
    """渐进式场景生成会话运行时。

    持有 SceneLayout（唯一事实源）+ current_round + 介入队列 + diff tracker。
    progressive_compose() 是主循环；介入随时 enqueue，phase 边界统一 drain。
    """

    def __init__(
        self,
        scene_layout: Any,
        *,
        diff_tracker: Any = None,
        engine_gate: Any = None,
        scene_name: str = "lanchat_scene",
    ) -> None:
        self.scene_layout = scene_layout
        self.diff_tracker = diff_tracker
        self.engine_gate = engine_gate
        self.scene_name = scene_name

        self.current_round = 0
        self._queue: List[InterventionOp] = []
        self.pending_tasks: List[Dict[str, Any]] = []
        self.operation_log: List[OperationLogEntry] = []
        self.silent_gm_state: Dict[str, Any] = {}
        self._dirty = False
        self._progress_sink: Optional[Callable[[str], None]] = None

    # ── 介入入队（随时可调，线程安全留给调用方/gate）──────────────
    def enqueue_intervention(self, op: InterventionOp) -> None:
        """AI 工具 / 视口 diff 把介入操作排队。不立即重排（防抖）。"""
        self._queue.append(op)
        self._dirty = True
        logger.info("[SceneSession] 介入入队: %s %s (源=%s)",
                    op.op_type, op.actor_id, op.source)

    def set_progress_sink(self, sink: Callable[[str], None]) -> None:
        """注册进度回调（突击方案 E2，复用 phase 边界）。"""
        self._progress_sink = sink

    def _emit_progress(self, phase: str, extra: str = "") -> None:
        msg = PHASE_PROGRESS.get(phase, f"正在处理 {phase}…")
        if extra:
            msg = msg.rstrip("…") + f"（{extra}）…"
        if self._progress_sink:
            try:
                self._progress_sink(msg)
            except Exception:  # noqa: BLE001
                pass
        logger.info("[SceneSession][进度] %s", msg)

    def _append_operation(
        self,
        *,
        source: str,
        op_type: str,
        actor_id: Optional[str],
        user_id: Optional[str] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        intent_text: Optional[str] = None,
    ) -> None:
        self.operation_log.append(OperationLogEntry(
            op_id=f"op-{uuid.uuid4().hex[:12]}",
            round_id=self.current_round,
            timestamp=time.time(),
            source=source,
            op_type=op_type,
            actor_id=actor_id,
            user_id=user_id,
            before=before,
            after=after,
            intent_text=intent_text,
        ))

    # ── 介入 drain（phase 边界统一应用）──────────────────────────
    def drain_interventions(self) -> int:
        """把队列里的介入操作应用到 SceneLayout（打 USER + 当前轮次）。

        返回应用的操作数。视口 diff 已由调用方在 poll 后入队；这里统一落账。
        """
        n = 0
        while self._queue:
            op = self._queue.pop(0)
            if op.op_type == OP_DELETE:
                inst = self.scene_layout.get(op.actor_id)
                if inst is not None:
                    before = {
                        "provenance": getattr(inst, "provenance", None),
                        "layout_status": getattr(inst, "layout_status", None),
                    }
                    inst.layout_status = "stale"   # 标失效，不物理删（可恢复）
                    inst.provenance = "USER"
                    inst.touched_by_user = True
                    inst.intervention_round = self.current_round
                    self._append_operation(
                        source="USER",
                        op_type="DELETE",
                        actor_id=op.actor_id,
                        before=before,
                        after={"layout_status": "stale"},
                        intent_text=op.payload.get("intent_text"),
                    )
            else:
                # ADD/MOVE/SCALE/ROTATE/COLOR → 标用户介入 + 记轮次（近因加权）
                self.scene_layout.mark_user_intervention(
                    op.actor_id, self.current_round, lock_level="HARD")
                self._append_operation(
                    source="USER",
                    op_type=op.op_type.replace("USER_", ""),
                    actor_id=op.actor_id,
                    after=op.payload or None,
                    intent_text=op.payload.get("intent_text"),
                )
            n += 1
        if n:
            logger.info("[SceneSession] drain 应用 %d 条介入（轮次 %d）", n, self.current_round)
        return n

    def poll_viewport(self, snapshot: Any) -> int:
        """采集视口快照 → diff → 把用户介入转成队列操作（路 A 命门解法）。

        snapshot: {actor_id: transform}（由调用方从引擎采集）。
        返回捕获的视口介入数。
        """
        if self.diff_tracker is None:
            return 0
        from .scene_diff import DIFF_MOVED, DIFF_ADDED, DIFF_DELETED
        events = self.diff_tracker.poll(snapshot)
        kind_map = {DIFF_MOVED: OP_MOVE, DIFF_ADDED: OP_ADD, DIFF_DELETED: OP_DELETE}
        for ev in events:
            self.enqueue_intervention(InterventionOp(
                actor_id=ev.actor_id,
                op_type=kind_map.get(ev.kind, OP_MOVE),
                source="viewport",
                payload={"changed": getattr(ev, "changed", [])},
            ))
        return len(events)

    # ── settlement 缩范围（突击方案 §B4 + §2.2）───────────────────
    def settle_current_batch(
        self,
        batch_id: str,
        reasonable_map: Optional[Dict[str, bool]] = None,
        settle_fn: Optional[Callable[[List[Any]], None]] = None,
    ) -> List[str]:
        """只沉降本批 AGENT + 早期不合理用户物体，绝不碰最近用户介入。"""
        settleable = self.scene_layout.list_settleable(
            batch_id, self.current_round, reasonable_map)
        if settle_fn and settleable:
            settle_fn(settleable)
        ids = [getattr(i, "instance_id", "") for i in settleable]
        logger.info("[SceneSession] settle 本批: %s", ids)
        return ids

    # ── 主循环（突击方案 §2.1 路 B：phase 边界交错）────────────────
    def progressive_compose(
        self,
        phase_generators: Dict[str, Callable[["SceneSession", str], List[Dict[str, Any]]]],
        *,
        importer: Optional[Callable[[List[Dict[str, Any]], str], Dict[str, Any]]] = None,
        viewport_sampler: Optional[Callable[[], Any]] = None,
        reasonable_provider: Optional[Callable[[], Dict[str, bool]]] = None,
        settle_fn: Optional[Callable[[List[Any]], None]] = None,
        skip_final_review: bool = False,
    ) -> Dict[str, Any]:
        """渐进式主循环。每个 phase：生成→导入→进度→采集视口→drain介入→settle。

        phase_generators: {phase: fn(session, phase) -> [asset dict]}，缺省的 phase 跳过。
        importer: fn(assets, batch_id) -> result（默认走注入的 incremental_import）。
        viewport_sampler: fn() -> snapshot，phase 边界采集视口（路 A）。
        reasonable_provider: fn() -> {actor_id: 合理?}（E5 检查结果，喂保护降级）。

        返回 {phases_run, imported, final_report}。
        """
        self.current_round += 1
        round_id = self.current_round
        imported_all: List[str] = []
        phases_run: List[str] = []

        for phase in PHASE_ORDER:
            gen = phase_generators.get(phase)
            if gen is None:
                continue
            phases_run.append(phase)
            batch_id = f"r{round_id}_{phase}"

            # 1. 生成本 phase 的资产（纯 API/几何，不碰引擎）
            try:
                assets = gen(self, phase) or []
            except Exception as exc:  # noqa: BLE001
                logger.error("[SceneSession] phase %s 生成失败（跳过）: %s", phase, exc)
                assets = []

            # 2. 导入（只 add 不 clear，经 EngineWriteGate）
            imported_this_phase: List[str] = []
            post_import_snapshot = None
            if assets and importer is not None:
                try:
                    res = importer(assets, batch_id)
                    imported_this_phase = list(res.get("imported", []) or [])
                    imported_all.extend(imported_this_phase)
                except Exception as exc:  # noqa: BLE001
                    logger.error("[SceneSession] phase %s 导入失败（跳过）: %s", phase, exc)

            # Agent 刚导入的 actor 必须纳入 diff 基线，否则下一次 poll 会误判成用户新增。
            if imported_this_phase and viewport_sampler is not None and self.diff_tracker is not None:
                baseline_add = getattr(self.diff_tracker, "baseline_add", None)
                if callable(baseline_add):
                    try:
                        post_import_snapshot = viewport_sampler()
                        baseline_add(imported_this_phase, post_import_snapshot)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("[SceneSession] 导入后 diff 基线更新跳过: %s", exc)

            # 3. 进度反馈（复用 phase 边界，突击方案 E2）
            self._emit_progress(phase, extra=f"{len(assets)}件" if assets else "")

            # 4. 采集视口介入（路 A）+ drain（AI 工具介入已随时入队）
            if viewport_sampler is not None:
                try:
                    self.poll_viewport(post_import_snapshot if post_import_snapshot is not None
                                       else viewport_sampler())
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[SceneSession] 视口采集跳过: %s", exc)
            self.drain_interventions()

            # 5. 防抖懒重建（dirty 才重建 prompt——这里只清标记，重建交给调用方钩子）
            if self._dirty:
                logger.debug("[SceneSession] phase %s 末 dirty → 待懒重建", phase)
                self._dirty = False

            # 6. settle 只碰本批 AGENT（+ 早期不合理用户物体）
            rmap = reasonable_provider() if reasonable_provider else None
            self.settle_current_batch(batch_id, rmap, settle_fn)

        # 7. FinalReview 只修 AGENT（测试可跳过，因为有专门的独立测试覆盖）
        report = None
        if not skip_final_review:
            report = self.final_review(
                reasonable_provider() if reasonable_provider else None)
        return {
            "phases_run": phases_run,
            "imported": imported_all,
            "round": round_id,
            "final_report": report,
        }

    # ── FinalReview（突击方案 §2.5：只修 AGENT，不静默覆盖用户）────
    def final_review(
        self,
        reasonable_map: Optional[Dict[str, bool]] = None,
        protection_fn: Any = None,
    ) -> FinalReviewReport:
        """最后一轮按近因加权保护分三桶处理。覆盖前必产报告。

        protection_fn: 注入点——默认用真 protection_level，离线测可注入假函数。
        """
        if protection_fn is None:
            from ..data_model.layout import (
                protection_level as protection_fn,
                PROTECTION_HARD, PROTECTION_NONE,
            )
        else:
            PROTECTION_HARD, PROTECTION_NONE = "HARD", "NONE"
        report = FinalReviewReport()
        reasonable_map = reasonable_map or {}

        for inst in self.scene_layout.list_active():
            iid = inst.instance_id
            reasonable = reasonable_map.get(iid, True)
            level = protection_fn(inst, self.current_round, reasonable)

            if inst.provenance == "USER":
                if level == PROTECTION_HARD:
                    report.preserved.append(iid)                 # 近因强保护：只检查不动
                elif level == PROTECTION_NONE:
                    # 早期 + 不合理用户物体 → 报告问用户（不静默覆盖）
                    report.needs_confirm.append({
                        "actor_id": iid,
                        "detail": f"你早先放的「{iid}」可能不合理",
                    })
                else:
                    report.preserved.append(iid)                 # 早期但合理：尽量保留
            else:
                # AGENT 物体：可自动调整/让位
                if not reasonable:
                    report.adjusted.append(iid)

        logger.info("[SceneSession] FinalReview: 保留 %d / 调整 %d / 待确认 %d",
                    len(report.preserved), len(report.adjusted), len(report.needs_confirm))
        return report


__all__ = [
    "PHASE_ORDER", "PHASE_PROGRESS", "SceneSession", "InterventionOp",
    "OperationLogEntry", "FinalReviewReport",
    "OP_ADD", "OP_DELETE", "OP_MOVE", "OP_SCALE", "OP_ROTATE", "OP_COLOR",
]
