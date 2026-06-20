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
    "GROUND": "准备场地",
    "SHELL": "放置主体",
    "INTERIOR": "整理内部",
    "BOUNDARY": "处理边界",
    "OBJECTS": "摆放物件",
    "DECORATION": "补充装饰",
}

_PHASE_DETAILS = {
    "GROUND": "先把地面和空间范围搭好。",
    "SHELL": "主体会先落位，后面的物件会围绕它调整。",
    "INTERIOR": "正在处理内部地面和可进入空间。",
    "BOUNDARY": "正在确认边界和通行空间。",
    "OBJECTS": "开始把主要物件放进场景。",
    "DECORATION": "补充装饰，但不会覆盖你刚刚改过的内容。",
}

_SENSITIVE_PROGRESS_KEYS = {
    "api_key",
    "auth",
    "chain",
    "debug",
    "debug_trace",
    "error_trace",
    "finding_details",
    "hidden_debug_ref",
    "internal",
    "job_id",
    "llm_request",
    "llm_response",
    "messages",
    "model_config",
    "model_provider",
    "prompt",
    "provider",
    "raw_prompt",
    "raw_response",
    "request",
    "response",
    "runtime_context",
    "scheduler_updates",
    "session_id",
    "stage_handlers",
    "stack",
    "trace",
    "tool",
    "tool_call",
    "tool_calls",
    "tool_name",
    "token",
    "vlm_raw",
}


def _sanitize_progress_payload(value: Any) -> Any:
    if isinstance(value, dict):
        safe: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()
            if key_lower in _SENSITIVE_PROGRESS_KEYS or key_lower.endswith("_prompt") or "token" in key_lower:
                continue
            if item is None or callable(item):
                continue
            safe[key_text] = _sanitize_progress_payload(item)
        return safe
    if isinstance(value, list):
        return [
            _sanitize_progress_payload(item)
            for item in value
            if item is not None and not callable(item)
        ]
    if isinstance(value, tuple):
        return [
            _sanitize_progress_payload(item)
            for item in value
            if item is not None and not callable(item)
        ]
    return value

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
    final_adjustments: List[Dict[str, Any]] = field(default_factory=list)  # Coordinator 汇总的最终强介入
    deferred_interventions: List[Dict[str, Any]] = field(default_factory=list)  # 早期弱介入，保留原因但不压过收尾
    conflicts: List[Dict[str, Any]] = field(default_factory=list)  # 需要 GM/房主仲裁的冲突
    resolved_conflicts: List[Dict[str, Any]] = field(default_factory=list)  # 已由 GM/房主确认或拒绝的冲突
    applied_final_adjustments: List[Dict[str, Any]] = field(default_factory=list)  # 已安全执行的收尾修复动作
    style_contract_summary: Dict[str, Any] = field(default_factory=dict)  # 长周期场景契约摘要，只放用户可读字段

    @staticmethod
    def _safe_user_text(value: Any, *, fallback: str = "") -> str:
        text = str(value or "").strip()
        if not text:
            return fallback
        lower = text.lower()
        markers = (
            "prompt",
            "raw_prompt",
            "provider",
            "model_provider",
            "runtime_context",
            "scheduler_updates",
            "hidden_debug_ref",
            "debug",
            "job_id",
            "session_id",
            "token",
            "api_key",
            "vlm_raw",
        )
        cut_points = [lower.find(marker) for marker in markers if lower.find(marker) >= 0]
        if cut_points:
            keep = text[:min(cut_points)].strip(" \t\r\n,;；。")
            return keep or fallback or "内部细节已隐藏"
        return text

    @staticmethod
    def _format_conflict(conflict: Dict[str, Any]) -> str:
        target = str(
            conflict.get("target_hint")
            or conflict.get("actor_id")
            or conflict.get("target_key")
            or ""
        ).strip()
        reason = str(conflict.get("reason") or "").strip()
        reason_text = {
            "same_actor_has_remove_and_keep_modify_requests": "同一物体同时存在删除与保留/修改要求",
            "same_target_has_remove_and_keep_modify_requests": "同一目标同时存在删除与保留/修改要求",
        }.get(reason, FinalReviewReport._safe_user_text(reason, fallback="存在未决冲突"))
        target = FinalReviewReport._safe_user_text(target)
        reason_text = FinalReviewReport._safe_user_text(reason_text, fallback="存在未决冲突")
        if target and reason_text:
            return f"{target}：{reason_text}"
        return target or reason_text or "存在未决冲突"

    @staticmethod
    def _safe_text_list(values: Any, *, limit: int = 5) -> List[str]:
        if not isinstance(values, list):
            return []
        out: List[str] = []
        for value in values:
            safe = FinalReviewReport._safe_user_text(value)
            if safe and safe not in out:
                out.append(safe)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _safe_contract_spec(spec: Any, *, keys: Sequence[str]) -> List[str]:
        if not isinstance(spec, dict):
            return []
        out: List[str] = []
        for key in keys:
            value = spec.get(key)
            if isinstance(value, list):
                safe_value = "、".join(FinalReviewReport._safe_text_list(value, limit=3))
            else:
                safe_value = FinalReviewReport._safe_user_text(value)
            if safe_value:
                out.append(safe_value)
        return out

    @staticmethod
    def build_style_contract_summary(contract: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract the stable room-level design contract for the final user report."""
        if not isinstance(contract, dict) or not contract:
            return {}
        summary: Dict[str, Any] = {}
        version = contract.get("version")
        if isinstance(version, int) and version > 0:
            summary["version"] = version
        summary["scene"] = FinalReviewReport._safe_user_text(contract.get("scene_type"))
        summary["environment"] = FinalReviewReport._safe_user_text(contract.get("environment_type"))
        summary["style"] = FinalReviewReport._safe_text_list(contract.get("style_keywords"), limit=4)
        summary["mood"] = FinalReviewReport._safe_text_list(contract.get("mood"), limit=4)
        summary["avoid"] = FinalReviewReport._safe_text_list(contract.get("avoid_keywords"), limit=4)
        summary["palette"] = FinalReviewReport._safe_text_list(contract.get("palette"), limit=3)
        summary["lighting"] = FinalReviewReport._safe_text_list(contract.get("lighting"), limit=3)
        summary["scale_rules"] = FinalReviewReport._safe_text_list(contract.get("scale_rules"), limit=2)
        summary["placement_rules"] = FinalReviewReport._safe_text_list(contract.get("placement_rules"), limit=3)
        summary["terrain"] = FinalReviewReport._safe_contract_spec(
            contract.get("terrain_spec"),
            keys=("type", "surface", "walkable"),
        )
        summary["boundary"] = FinalReviewReport._safe_contract_spec(
            contract.get("boundary_spec"),
            keys=("type", "style", "height", "coverage", "avoid"),
        )
        return {key: value for key, value in summary.items() if value not in ("", [], {}, None)}

    def to_user_text(self) -> str:
        """生成给用户的自然语言报告（不是日志）。"""
        lines: List[str] = []
        if self.style_contract_summary:
            summary = self.style_contract_summary
            descriptors: List[str] = []
            for key in ("mood", "style", "palette", "lighting"):
                values = summary.get(key)
                if isinstance(values, list):
                    descriptors.extend(str(item) for item in values if str(item).strip())
            descriptors = list(dict.fromkeys(descriptors))
            if descriptors:
                lines.append("风格收口：" + "、".join(descriptors[:8]) + "。")
            avoid = summary.get("avoid")
            if isinstance(avoid, list) and avoid:
                lines.append("已持续避开：" + "、".join(str(item) for item in avoid[:5]) + "。")
            placement_bits: List[str] = []
            for key in ("terrain", "boundary", "scale_rules", "placement_rules"):
                values = summary.get(key)
                if isinstance(values, list):
                    placement_bits.extend(str(item) for item in values if str(item).strip())
            placement_bits = list(dict.fromkeys(placement_bits))
            if placement_bits:
                lines.append("组装约束：" + "；".join(placement_bits[:6]) + "。")
        if self.preserved:
            preserved = [self._safe_user_text(item) for item in self.preserved[:5] if self._safe_user_text(item)]
            if preserved:
                lines.append("已保留你最近的调整：" + "、".join(preserved) + "。")
        if self.final_adjustments:
            contents = [
                self._safe_user_text(item.get("content"))
                for item in self.final_adjustments
                if self._safe_user_text(item.get("content"))
            ]
            if contents:
                lines.append("最终收尾会优先处理：" + "；".join(contents[:3]) + "。")
        if self.deferred_interventions:
            deferred_texts = []
            for item in self.deferred_interventions:
                text = (
                    item.get("content")
                    or item.get("text")
                    or item.get("original_text")
                    or item.get("reason")
                    or item.get("status")
                )
                safe = self._safe_user_text(text)
                if safe:
                    deferred_texts.append(safe)
            if deferred_texts:
                lines.append("仍待后续处理：" + "；".join(deferred_texts[:5]) + "。")
        if self.adjusted:
            adjusted = [self._safe_user_text(item) for item in self.adjusted[:5] if self._safe_user_text(item)]
            if adjusted:
                lines.append("系统自动调整了：" + "、".join(adjusted) + "。")
        if self.applied_final_adjustments:
            executed = [
                item for item in self.applied_final_adjustments
                if "skipped_actor_version_mismatch" not in (item.get("actions") or [])
            ]
            skipped_stale = [
                item for item in self.applied_final_adjustments
                if "skipped_actor_version_mismatch" in (item.get("actions") or [])
            ]
            actions = [
                self._safe_user_text(item.get("action"))
                for item in executed
                if self._safe_user_text(item.get("action"))
            ]
            if actions:
                lines.append("已完成收尾调整：" + "、".join(actions[:5]) + "。")
            if skipped_stale:
                targets = [
                    self._safe_user_text(item.get("content") or item.get("actor_id"))
                    for item in skipped_stale
                    if self._safe_user_text(item.get("content") or item.get("actor_id"))
                ]
                if targets:
                    lines.append("已跳过过期介入：" + "、".join(targets[:3]) + "，因为目标物体已被后续批次或用户更新。")
        for nc in self.needs_confirm:
            detail = self._safe_user_text(nc.get("detail", nc.get("actor_id", "")), fallback="这一项")
            lines.append(f"需要你确认：{detail}，是否允许我重新安排？")
        for conflict in self.conflicts:
            lines.append(f"需要 GM/房主确认：{self._format_conflict(conflict)}。")
        rejected = [
            self._format_conflict(conflict)
            for conflict in self.resolved_conflicts
            if str(conflict.get("status") or "") == "rejected"
        ]
        if rejected:
            lines.append("已按房主决定跳过收尾冲突项：" + "、".join(rejected[:3]) + "。")
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
        self._progress_event_sink: Optional[Callable[[Dict[str, Any]], None]] = None

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

    def set_progress_event_sink(self, sink: Callable[[Dict[str, Any]], None]) -> None:
        """注册结构化进度事件回调，供 Coordinator 映射 BatchEvent。"""
        self._progress_event_sink = sink

    def _emit_progress(self, phase: str, extra: str = "") -> str:
        msg = PHASE_PROGRESS.get(phase, "处理场景")
        if extra:
            msg = f"{msg}（{extra}）"
        logger.info("[SceneSession][进度] %s", msg)
        return msg

    def _publish_progress_event(self, event: Dict[str, Any]) -> None:
        """Publish a sanitized progress message to the outer UI/chat layer."""
        user_message = self.format_progress_message(event)
        event["user_message"] = user_message
        sanitized = _sanitize_progress_payload(event)
        event.clear()
        event.update(sanitized)
        if self._progress_event_sink:
            try:
                self._progress_event_sink(dict(event))
            except Exception:  # noqa: BLE001
                pass
        if self._progress_sink:
            try:
                self._progress_sink(user_message)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def format_progress_message(event: Dict[str, Any]) -> str:
        """Format a safe, user-facing progress line.

        Do not include prompts, batch ids, tool names, model provider names, or
        raw phase internals. This text is safe to stream into LANChat while the
        generation is still running.
        """
        percent = max(0, min(100, int(event.get("percent", 0) or 0)))
        phase = str(event.get("phase") or "")
        base_phase = phase.split("#", 1)[0]
        status = str(event.get("status") or "")
        label = PHASE_PROGRESS.get(base_phase, "处理场景")
        detail = _PHASE_DETAILS.get(base_phase, "正在推进当前场景。")
        blocks = max(0, min(10, round(percent / 10)))
        bar = "█" * blocks + "░" * (10 - blocks)
        if status == "start":
            verb = "开始"
        elif status == "done":
            verb = "完成"
        elif status == "paused":
            verb = "暂停"
        else:
            verb = "进行中"
        def _names(values: Any, limit: int = 5) -> str:
            if not isinstance(values, list):
                return ""
            names = [str(item).strip() for item in values if str(item).strip()]
            if not names:
                return ""
            text = "、".join(names[:limit])
            if len(names) > limit:
                text += f" 等 {len(names)} 个"
            return text

        def _note_text(values: Any, limit: int = 3) -> str:
            if not isinstance(values, list):
                return ""
            notes = []
            for item in values:
                if isinstance(item, dict):
                    value = str(item.get("text") or "").strip()
                else:
                    value = str(item or "").strip()
                if value:
                    notes.append(value)
            if not notes:
                return ""
            text = "；".join(notes[:limit])
            if len(notes) > limit:
                text += f"；另有 {len(notes) - limit} 条"
            return text

        def _resource_status(values: Any) -> str:
            if not isinstance(values, list):
                return ""
            requested = 0
            image_done = 0
            image_failed = 0
            resolved = 0
            failed = 0
            pending = 0
            names: list[str] = []
            for item in values:
                if not isinstance(item, dict):
                    continue
                plan = item.get("batch_resource_plan") if isinstance(item.get("batch_resource_plan"), dict) else {}
                requested_items = plan.get("requested_items") if isinstance(plan.get("requested_items"), list) else []
                requested += len(requested_items)
                for request in requested_items:
                    if not isinstance(request, dict):
                        continue
                    name = str(request.get("item_name") or "").strip()
                    if name and name not in names:
                        names.append(name)
                resolved_items = item.get("resolved_assets") if isinstance(item.get("resolved_assets"), list) else []
                failed_items = item.get("failed") if isinstance(item.get("failed"), list) else []
                image_items = item.get("image_generated") if isinstance(item.get("image_generated"), list) else []
                image_failed_items = item.get("image_failed") if isinstance(item.get("image_failed"), list) else []
                image_done += len(image_items)
                image_failed += len(image_failed_items)
                resolved += len(resolved_items)
                failed += len(failed_items)
                status_text = str(item.get("status") or "")
                if status_text in {"model_provider_unavailable", "model_generation_failed", "provider_unavailable", "failed"}:
                    failed += max(0, len(requested_items) - len(failed_items) - len(resolved_items))
                elif status_text in {"model_generating", "planned"}:
                    pending += max(0, len(requested_items) - len(resolved_items) - len(failed_items))
            if not requested:
                return ""
            visible = "、".join(names[:3])
            if len(names) > 3:
                visible += f" 等 {len(names)} 个"
            pieces = [f"资源准备：新增请求 {requested} 个"]
            if visible:
                pieces.append(f"对象：{visible}")
            pieces.append(f"图片 {image_done}/{requested}")
            pieces.append(f"模型 {resolved}/{requested}")
            if image_failed:
                pieces.append(f"图片待重试 {image_failed}")
            if failed:
                pieces.append(f"失败/待重试 {failed}")
            elif pending:
                pieces.append(f"等待 {pending}")
            return "，".join(pieces)

        def _backlog_status(values: Any) -> str:
            if not isinstance(values, list):
                return ""
            queued = 0
            overflow = 0
            names: list[str] = []
            for item in values:
                if not isinstance(item, dict):
                    continue
                queued += int(item.get("remaining_count") or 0)
                overflow += int(item.get("overflow_count") or 0)
                for key in ("queued_items", "dropped_items"):
                    raw = item.get(key)
                    if not isinstance(raw, list):
                        continue
                    for value in raw:
                        name = str(value or "").strip()
                        if name and name not in names:
                            names.append(name)
            if not queued and not overflow:
                return ""
            parts = []
            if queued:
                parts.append(f"下一批资源队列还有 {queued} 个")
            if names:
                parts.append("包括：" + "、".join(names[:4]))
            if overflow:
                parts.append(f"已延后 {overflow} 个较早请求")
            return "，".join(parts)

        suffix = ""
        imported = int(event.get("imported_count", 0) or 0)
        assets = int(event.get("asset_count", 0) or 0)
        cumulative = int(event.get("cumulative_imported", 0) or 0)
        total_assets = int(event.get("total_assets", 0) or 0)
        batch_index = int(event.get("batch_index", 0) or 0)
        batch_total = int(event.get("batch_total", 0) or 0)
        batch_prefix = f"第 {batch_index}/{batch_total} 批，" if batch_index and batch_total else ""
        batch_names = _names(event.get("batch_asset_names"))
        imported_names = _names(event.get("imported_asset_names") or event.get("batch_asset_names"))
        next_names = _names(event.get("next_batch_asset_names"))
        absorbed = _note_text(event.get("absorbed_notes"))
        deferred = _note_text(event.get("deferred_notes"))
        resources = _resource_status(event.get("resource_plans"))
        backlog = _backlog_status(event.get("resource_backlog"))
        if status == "done" and (assets or resources):
            suffix = f" {batch_prefix}本批已放入 {imported}/{assets} 个物件"
            if imported_names:
                suffix += f"：{imported_names}"
            suffix += "。"
            suffix += f" 导入 {imported}/{assets}。"
            if resources:
                suffix += f" {resources}。"
            if backlog:
                suffix += f" {backlog}。"
            if total_assets:
                suffix += f"累计已放入 {cumulative}/{total_assets} 个。"
            if absorbed:
                suffix += f" 已吸收你的要求：{absorbed}。"
            if deferred:
                suffix += f" 已记录待补：{deferred}。"
            if next_names:
                suffix += f" 下一批准备：{next_names}。"
        elif status == "start":
            suffix = f" {batch_prefix}"
            if batch_names:
                suffix += f"准备放入：{batch_names}。"
            else:
                suffix += "准备推进下一批。"
            if resources:
                suffix += f" {resources}。"
            if backlog:
                suffix += f" {backlog}。"
            if next_names:
                suffix += f" 后续还有：{next_names}。"
            suffix += "你可以继续提出调整，我会在下一批前吸收。"
        elif status == "paused":
            mode = str(event.get("mode") or "")
            if mode == "DISCUSSING":
                suffix = " 已切到讨论模式，后续批次暂不写入场景。"
            else:
                suffix = " 已在批次边界暂停，等待 @GM 继续。"
            if next_names or batch_names:
                suffix += f" 暂停前剩余：{next_names or batch_names}。"
        return f"生成进度 {percent:>3}% [{bar}] {verb}：{label}。{detail}{suffix}"

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

    def apply_final_adjustments(self, report: FinalReviewReport) -> List[Dict[str, Any]]:
        """Apply safe, local final adjustments derived from Coordinator summary.

        This intentionally supports only deterministic transform/status fixes.
        Ambiguous content and conflicts remain in the report for GM/host review.
        """
        applied: List[Dict[str, Any]] = []
        conflict_target_keys: set[str] = set()
        for item in report.conflicts:
            conflict_target_keys.update(self._final_adjustment_target_keys(item))
        for item in report.final_adjustments:
            actor_id = str(item.get("actor_id") or "").strip()
            target_keys = self._final_adjustment_target_keys(item)
            if not actor_id or target_keys.intersection(conflict_target_keys):
                continue
            inst = self.scene_layout.get(actor_id)
            if inst is None or getattr(inst, "layout_status", "active") != "active":
                continue
            if self._actor_version_mismatch(item, inst):
                applied.append({
                    "actor_id": actor_id,
                    "intervention_id": item.get("intervention_id", ""),
                    "actions": ["skipped_actor_version_mismatch"],
                    "action": f"{actor_id}:skipped_actor_version_mismatch",
                    "content": item.get("content", ""),
                    "expected_actor_version": int(item.get("actor_version") or 0),
                    "actual_actor_version": self._actor_version(inst),
                })
                continue
            content = str(item.get("content") or "").lower()
            before = {
                "transform": self._copy_transform(getattr(inst, "transform", {})),
                "layout_status": getattr(inst, "layout_status", None),
            }
            actions: List[str] = []
            transform = getattr(inst, "transform", None)
            if isinstance(transform, dict):
                has_scale_correction = False
                for detail in item.get("finding_details") or []:
                    if not isinstance(detail, dict):
                        continue
                    position = self._optional_vector3(detail.get("position_correction"))
                    if position is not None:
                        transform["pos"] = position
                        actions.append("apply_position_correction")
                    rotation = self._optional_vector3(detail.get("rotation_correction"))
                    if rotation is not None:
                        transform["rot"] = rotation
                        actions.append("apply_rotation_correction")
                    scale_correction = self._optional_vector3(detail.get("scale_correction"))
                    if scale_correction is not None:
                        transform["scale"] = [max(0.05, value) for value in scale_correction]
                        actions.append("apply_scale_correction")
                        has_scale_correction = True
                if not has_scale_correction and any(word in content for word in ("缩小", "太大", "偏大", "比例")):
                    scale = self._vector3(transform.get("scale"), default=1.0)
                    transform["scale"] = [max(0.05, round(value * 0.85, 6)) for value in scale]
                    actions.append("scale_down")
                if any(word in content for word in ("贴地", "接地", "地面", "悬空", "穿模")):
                    pos = self._vector3(transform.get("pos"), default=0.0)
                    pos[1] = max(0.0, pos[1])
                    transform["pos"] = pos
                    actions.append("ground_fit")
            if any(word in content for word in ("移除", "删除", "不要")):
                inst.layout_status = "stale"
                actions.append("mark_stale")
            if not actions:
                continue
            after = {
                "transform": self._copy_transform(getattr(inst, "transform", {})),
                "layout_status": getattr(inst, "layout_status", None),
            }
            record = {
                "actor_id": actor_id,
                "intervention_id": item.get("intervention_id", ""),
                "actions": actions,
                "action": f"{actor_id}:{'+'.join(actions)}",
                "content": item.get("content", ""),
            }
            applied.append(record)
            self._append_operation(
                source="SYSTEM",
                op_type="FINAL_ADJUST",
                actor_id=actor_id,
                before=before,
                after=after,
                intent_text=str(item.get("content") or ""),
            )
        report.applied_final_adjustments.extend(applied)
        if applied:
            logger.info("[SceneSession] FinalAdjustment applied: %s", applied)
        return applied

    @staticmethod
    def _final_adjustment_target_keys(item: Dict[str, Any]) -> set[str]:
        keys: set[str] = set()
        for key in ("actor_id", "target_actor_id", "object_id", "target_object_id", "target_hint", "target_key"):
            value = str(item.get(key) or "").strip()
            if value:
                keys.add(value)
        for detail in item.get("finding_details") or []:
            if not isinstance(detail, dict):
                continue
            for key in ("actor_id", "target_actor_id", "object_id", "target_object_id", "target_hint", "target_key"):
                value = str(detail.get(key) or "").strip()
                if value:
                    keys.add(value)
        return keys

    @staticmethod
    def _actor_version(inst: Any) -> int:
        metadata = getattr(inst, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            return 0
        for key in ("actor_version", "version"):
            if metadata.get(key) in (None, ""):
                continue
            try:
                return int(metadata.get(key) or 0)
            except (TypeError, ValueError):
                continue
        return 0

    def _actor_version_mismatch(self, item: Dict[str, Any], inst: Any) -> bool:
        try:
            expected = int(item.get("actor_version") or 0)
        except (TypeError, ValueError):
            expected = 0
        actual = self._actor_version(inst)
        return bool(expected and actual and expected != actual)

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
        post_import_hook: Optional[Callable[[List[str], str], None]] = None,
        skip_final_review: bool = False,
        phase_sequence: Optional[Sequence[str]] = None,
        phase_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
        runtime_mode_provider: Optional[Callable[[], str]] = None,
        final_adjustment_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        scene_design_contract_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        pre_final_review_hook: Optional[Callable[[], None]] = None,
        final_review_protection_fn: Any = None,
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
        progress_timeline: List[Dict[str, Any]] = []
        ordered_phases = list(phase_sequence) if phase_sequence else list(PHASE_ORDER)
        active_phases = [phase for phase in ordered_phases if phase_generators.get(phase)]
        total_phases = max(1, len(active_phases))
        total_assets = sum(int((phase_metadata or {}).get(phase, {}).get("asset_count", 0) or 0)
                           for phase in active_phases)
        cumulative_imported = 0
        paused = False
        paused_mode = ""
        paused_before_phase = ""

        for phase in ordered_phases:
            gen = phase_generators.get(phase)
            if gen is None:
                continue
            base_phase = phase.split("#", 1)[0]
            if phase_metadata:
                total_assets = sum(int(value.get("asset_count", 0) or 0)
                                   for value in phase_metadata.values())
            meta = dict((phase_metadata or {}).get(phase, {}) or {})
            phase_index = len(phases_run) + 1
            batch_id = f"r{round_id}_{phase.replace('#', '_b')}"
            start_percent = int(((phase_index - 1) / total_phases) * 100)

            mode = ""
            if runtime_mode_provider is not None:
                try:
                    mode = str(runtime_mode_provider() or "").strip().upper()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[SceneSession] runtime mode provider skipped: %s", exc)
                    mode = ""
            if mode in {"PAUSED", "DISCUSSING"}:
                paused = True
                paused_mode = mode
                paused_before_phase = phase
                pause_msg = self._emit_progress(base_phase, extra=f"暂停 {phase_index}/{total_phases}")
                progress_timeline.append({
                    "phase": phase,
                    "status": "paused",
                    "mode": mode,
                    "percent": start_percent,
                    "message": pause_msg,
                    "asset_count": int(meta.get("asset_count", 0) or 0),
                    "imported_count": 0,
                    "cumulative_imported": cumulative_imported,
                    "total_assets": total_assets,
                    **meta,
                })
                self._publish_progress_event(progress_timeline[-1])
                logger.info("[SceneSession] runtime mode %s pauses before phase %s", mode, phase)
                break

            phases_run.append(phase)
            start_msg = self._emit_progress(base_phase, extra=f"开始 {phase_index}/{total_phases}")
            progress_timeline.append({
                "phase": phase,
                "status": "start",
                "percent": start_percent,
                "message": start_msg,
                "asset_count": 0,
                "imported_count": 0,
                "cumulative_imported": cumulative_imported,
                "total_assets": total_assets,
                **meta,
            })
            self._publish_progress_event(progress_timeline[-1])

            # 1. 生成本 phase 的资产（纯 API/几何，不碰引擎）
            try:
                before_task_count = len(self.pending_tasks)
                assets = gen(self, phase) or []
            except Exception as exc:  # noqa: BLE001
                logger.error("[SceneSession] phase %s 生成失败（跳过）: %s", phase, exc)
                assets = []
                before_task_count = len(self.pending_tasks)

            dynamic_meta = dict((phase_metadata or {}).get(phase, {}) or {})
            if dynamic_meta:
                meta.update(dynamic_meta)
            asset_names = [str(item.get("name") or "").strip()
                           for item in assets if isinstance(item, dict) and str(item.get("name") or "").strip()]
            if asset_names:
                meta["batch_asset_names"] = asset_names
            if phase_metadata:
                meta["asset_count"] = len(assets)
                phase_metadata.setdefault(phase, {})["asset_count"] = len(assets)
                phase_metadata[phase]["batch_asset_names"] = asset_names
                total_assets = sum(int(value.get("asset_count", 0) or 0)
                                   for value in phase_metadata.values())
            recent_tasks = list(self.pending_tasks[before_task_count:])
            absorbed_tasks = [task for task in recent_tasks
                              if str(task.get("status") or "").startswith(("applied", "inserted", "already"))]
            deferred_tasks = [task for task in recent_tasks
                              if str(task.get("status") or "").startswith(("deferred", "pending"))]
            resource_plan_tasks = [task for task in recent_tasks
                                   if str(task.get("kind") or "") == "batch_resource_plan"]
            resource_backlog_tasks = [task for task in recent_tasks
                                      if str(task.get("kind") or "") == "resource_backlog"]

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

            if imported_this_phase and post_import_hook is not None:
                try:
                    post_import_hook(imported_this_phase, batch_id)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[SceneSession] phase %s post-import repair skipped: %s", phase, exc)

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
            cumulative_imported += len(imported_this_phase)
            done_percent = int((phase_index / total_phases) * 100)
            done_msg = self._emit_progress(base_phase, extra=f"{len(assets)}件" if assets else "")
            progress_timeline.append({
                "phase": phase,
                "status": "done",
                "percent": done_percent,
                "message": done_msg,
                **meta,
                "asset_count": len(assets),
                "imported_count": len(imported_this_phase),
                "cumulative_imported": cumulative_imported,
                "total_assets": total_assets,
                "imported_asset_names": asset_names[:len(imported_this_phase) or len(asset_names)],
                "absorbed_notes": absorbed_tasks,
                "deferred_notes": deferred_tasks,
                "resource_plans": resource_plan_tasks,
                "resource_backlog": resource_backlog_tasks,
            })
            self._publish_progress_event(progress_timeline[-1])

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
        final_adjustment_plan = None
        scene_design_contract = None
        if not skip_final_review and not paused:
            if pre_final_review_hook is not None:
                try:
                    pre_final_review_hook()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[SceneSession] pre-final review hook skipped: %s", exc)
            if final_adjustment_provider is not None:
                try:
                    final_adjustment_plan = final_adjustment_provider() or None
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[SceneSession] final adjustment provider skipped: %s", exc)
            if scene_design_contract_provider is not None:
                try:
                    scene_design_contract = scene_design_contract_provider() or None
                except Exception as exc:  # noqa: BLE001
                    logger.debug("[SceneSession] scene design contract provider skipped: %s", exc)
            report = self.final_review(
                reasonable_provider() if reasonable_provider else None,
                protection_fn=final_review_protection_fn,
                final_adjustment_plan=final_adjustment_plan,
                scene_design_contract=scene_design_contract,
            )
        return {
            "phases_run": phases_run,
            "imported": imported_all,
            "round": round_id,
            "final_report": report,
            "final_adjustment_plan": final_adjustment_plan,
            "scene_design_contract": scene_design_contract,
            "progress_timeline": progress_timeline,
            "paused": paused,
            "paused_mode": paused_mode,
            "paused_before_phase": paused_before_phase,
        }

    # ── FinalReview（突击方案 §2.5：只修 AGENT，不静默覆盖用户）────
    def final_review(
        self,
        reasonable_map: Optional[Dict[str, bool]] = None,
        protection_fn: Any = None,
        final_adjustment_plan: Optional[Dict[str, Any]] = None,
        scene_design_contract: Optional[Dict[str, Any]] = None,
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
        if isinstance(final_adjustment_plan, dict):
            report.final_adjustments = list(final_adjustment_plan.get("selected") or [])
            report.deferred_interventions = list(final_adjustment_plan.get("deferred") or [])
            report.conflicts = list(final_adjustment_plan.get("conflicts") or [])
            report.resolved_conflicts = list(final_adjustment_plan.get("resolved_conflicts") or [])
        report.style_contract_summary = FinalReviewReport.build_style_contract_summary(scene_design_contract)
        report.deferred_interventions.extend(self._deferred_resource_tasks_for_report())

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

        self.apply_final_adjustments(report)
        logger.info("[SceneSession] FinalReview: 保留 %d / 调整 %d / 待确认 %d",
                    len(report.preserved), len(report.adjusted), len(report.needs_confirm))
        return report

    def _deferred_resource_tasks_for_report(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for task in self.pending_tasks:
            if not isinstance(task, dict):
                continue
            if str(task.get("kind") or "") != "batch_resource_plan":
                continue
            status = str(task.get("status") or "")
            if status not in {"model_provider_unavailable", "model_generation_failed", "empty_request"}:
                continue
            plan = task.get("batch_resource_plan") if isinstance(task.get("batch_resource_plan"), dict) else {}
            requested = plan.get("requested_items") if isinstance(plan.get("requested_items"), list) else []
            names = [
                str(item.get("item_name") or item.get("name") or "").strip()
                for item in requested
                if isinstance(item, dict) and str(item.get("item_name") or item.get("name") or "").strip()
            ]
            reason = {
                "model_provider_unavailable": "模型生成服务暂不可用",
                "model_generation_failed": "模型生成失败",
                "empty_request": "新增对象信息不足",
            }.get(status, status)
            out.append({
                "content": ("、".join(names) + f"：{reason}") if names else reason,
                "status": status,
                "reason": reason,
            })
        return out

    @staticmethod
    def _vector3(value: Any, *, default: float) -> List[float]:
        if isinstance(value, (list, tuple)):
            out = [float(item) for item in list(value)[:3]]
        else:
            out = []
        while len(out) < 3:
            out.append(float(default))
        return out

    @staticmethod
    def _optional_vector3(value: Any) -> Optional[List[float]]:
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            return None
        try:
            return [round(float(item), 6) for item in list(value)[:3]]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _copy_transform(value: Any) -> Dict[str, List[float]]:
        if not isinstance(value, dict):
            return {}
        copied: Dict[str, List[float]] = {}
        for key, item in value.items():
            if isinstance(item, (list, tuple)):
                copied[key] = [float(v) for v in item]
        return copied


__all__ = [
    "PHASE_ORDER", "PHASE_PROGRESS", "SceneSession", "InterventionOp",
    "OperationLogEntry", "FinalReviewReport",
    "OP_ADD", "OP_DELETE", "OP_MOVE", "OP_SCALE", "OP_ROTATE", "OP_COLOR",
]
