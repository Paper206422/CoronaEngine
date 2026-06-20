from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


AUDIENCES = {"host", "participant", "agent", "gm"}
INTERNAL_KEYS = {
    "prompt",
    "raw_prompt",
    "tool",
    "tool_name",
    "provider",
    "model_provider",
    "api_key",
    "job_id",
    "batch_id",
    "runtime_context",
    "stage_handlers",
    "scheduler_updates",
    "finding_details",
    "debug",
    "trace",
    "chain",
    "messages",
    "hidden_debug_ref",
}


@dataclass
class DisclosureEvent:
    room_id: str
    audience: str
    stage: str
    public_message: str
    progress: int = 0
    available_actions: list[str] = field(default_factory=list)
    requires_confirmation: bool = False
    event_id: str = field(default_factory=lambda: f"disc-{uuid.uuid4().hex[:12]}")
    hidden_debug_ref: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "room_id": self.room_id,
            "audience": self.audience,
            "stage": self.stage,
            "progress": self.progress,
            "public_message": self.public_message,
            "available_actions": list(self.available_actions),
            "requires_confirmation": self.requires_confirmation,
            "metadata": sanitize_public_payload(self.metadata),
            "created_at": self.created_at,
        }


def sanitize_public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in INTERNAL_KEYS:
                continue
            if item is None or callable(item):
                continue
            result[key_text] = sanitize_public_payload(item)
        return result
    if isinstance(value, list):
        return [
            sanitize_public_payload(item)
            for item in value
            if item is not None and not callable(item)
        ]
    return value


class DisclosurePolicy:
    """Role-aware information disclosure for LANChat generation flow.

    Public fields are safe for UI/chat. Internal identifiers and raw tool/model
    details stay in hidden_debug_ref or are omitted.
    """

    _STAGE_LABELS = {
        "draft": "讨论中",
        "clarifying": "方案整理中",
        "proposed": "等待房主确认",
        "confirmed": "已确认方案",
        "queued": "排队中",
        "waiting_resource": "等待资源",
        "executing": "生成中",
        "generating": "生成中",
        "batch": "批次生成中",
        "intervention": "可介入窗口",
        "review": "审查中",
        "final_adjustment": "最终调整中",
        "completed": "完成",
        "paused": "已暂停",
    }

    _INTERNAL_KEYS = INTERNAL_KEYS

    def disclose(
        self,
        *,
        room_id: str,
        stage: str,
        audience: str,
        progress: int = 0,
        plan: dict[str, Any] | None = None,
        intervention: dict[str, Any] | None = None,
        review: dict[str, Any] | None = None,
        debug_ref: str = "",
    ) -> DisclosureEvent:
        audience = audience if audience in AUDIENCES else "participant"
        stage = str(stage or "draft")
        progress = max(0, min(100, int(progress or 0)))
        plan = dict(plan or {})
        intervention = dict(intervention or {})
        review = dict(review or {})
        message = self._message_for(audience, stage, progress, plan, intervention, review)
        return DisclosureEvent(
            room_id=room_id,
            audience=audience,
            stage=self._STAGE_LABELS.get(stage, stage),
            progress=progress,
            public_message=message,
            available_actions=self._actions_for(audience, stage, intervention),
            requires_confirmation=self._requires_confirmation(audience, stage, intervention),
            hidden_debug_ref=debug_ref,
            metadata=self._metadata_for(audience, plan, intervention, review),
        )

    def disclose_all(
        self,
        *,
        room_id: str,
        stage: str,
        progress: int = 0,
        plan: dict[str, Any] | None = None,
        intervention: dict[str, Any] | None = None,
        review: dict[str, Any] | None = None,
        debug_ref: str = "",
    ) -> list[DisclosureEvent]:
        return [
            self.disclose(
                room_id=room_id,
                stage=stage,
                audience=audience,
                progress=progress,
                plan=plan,
                intervention=intervention,
                review=review,
                debug_ref=debug_ref,
            )
            for audience in ("host", "participant", "agent", "gm")
        ]

    def _message_for(
        self,
        audience: str,
        stage: str,
        progress: int,
        plan: dict[str, Any],
        intervention: dict[str, Any],
        review: dict[str, Any],
    ) -> str:
        label = self._STAGE_LABELS.get(stage, stage)
        summary = str(plan.get("intent_summary") or plan.get("summary") or "").strip()
        scene_type = str(plan.get("scene_type") or "").strip()
        clarification_message = str(intervention.get("status_message") or "").strip() if stage == "clarifying" else ""
        if audience == "host":
            if clarification_message:
                return f"{label}：{clarification_message}"
            if stage in {"proposed", "clarifying"}:
                return f"{label}：{summary or '已整理当前方案'}。请确认、继续讨论或暂停。"
            if stage in {"queued", "waiting_resource"}:
                return f"{label}：生成任务已进入队列，正在等待资源调度。你可以继续补充要求，我会在后续批次前吸收。"
            if stage in {"executing", "generating", "batch"}:
                return f"{label} {progress}%：正在按已确认方案分批生成。你可以暂停或要求下一批调整。"
            if stage == "review":
                return f"{label}：正在检查比例、摆放、穿模和风格一致性。"
            return f"{label}：{summary or '当前协作状态已更新'}。"
        if audience == "gm":
            conflicts = plan.get("conflicts") or []
            if conflicts:
                return f"{label}：发现 {len(conflicts)} 条潜在冲突，需要仲裁候选。"
            if intervention:
                return f"{label}：有新的介入请求，需要决定进入下一批、修复或重提案。"
            return f"{label}：请维持讨论节奏并等待房主确认关键动作。"
        if audience == "agent":
            constraints = []
            constraints.extend(plan.get("style_constraints") or [])
            constraints.extend(plan.get("placement_constraints") or [])
            if scene_type:
                constraints.append(f"scene_type={scene_type}")
            detail = "；".join(str(item) for item in constraints[:4] if str(item).strip())
            return f"{label}：使用已确认约束执行。{detail}".strip()
        if clarification_message:
            return f"{label}：{clarification_message}"
        if stage in {"queued", "waiting_resource"}:
            return f"{label}：生成任务已排队，正在等待资源；你可以继续提出调整，我会在下一批前吸收。"
        if stage in {"executing", "generating", "batch"}:
            return f"{label} {progress}%：正在分批生成。你可以继续提出调整，我会在下一批前吸收。"
        if stage == "intervention":
            status_message = str(intervention.get("status_message") or "").strip()
            if status_message:
                return f"可介入窗口：{status_message}"
            target = str(intervention.get("target_hint") or "").strip()
            if target:
                return f"可介入窗口：已记录“{target}”，会优先进入下一批或最终调整。"
            return "可介入窗口：你的补充会优先进入下一批或最终调整。"
        if stage == "review":
            return "审查中：正在检查摆放、比例、接地和风格一致性。"
        return f"{label}：{summary or '你的想法已记录，等待进一步整理。'}"

    def _actions_for(self, audience: str, stage: str, intervention: dict[str, Any] | None = None) -> list[str]:
        intervention = dict(intervention or {})
        if audience == "host":
            if intervention.get("apply_policy") == "host_confirmation":
                return [
                    "confirm_conflict_resolution",
                    "reject_conflict_resolution",
                    "request_clarification",
                    "pause_discussion",
                ]
            if stage in {"proposed", "clarifying"}:
                return ["confirm_plan", "request_clarification", "pause_discussion"]
            if stage in {"queued", "waiting_resource"}:
                return ["add_intervention", "pause_after_batch", "request_status"]
            if stage in {"executing", "generating", "batch"}:
                return ["pause_after_batch", "add_intervention", "request_review"]
            if stage == "review":
                return ["approve_final", "request_repair", "continue_generation"]
        if audience == "participant":
            if stage in {"queued", "waiting_resource", "executing", "generating", "batch", "intervention"}:
                return ["add_note", "request_add", "request_modify", "report_issue"]
            return ["discuss", "clarify_intent"]
        if audience == "gm":
            return ["propose_seed_plan", "resolve_conflict", "control_pace"]
        if audience == "agent":
            return ["execute_constraints", "report_blocker"]
        return []

    @staticmethod
    def _requires_confirmation(audience: str, stage: str, intervention: dict[str, Any] | None = None) -> bool:
        intervention = dict(intervention or {})
        if audience == "host" and intervention.get("apply_policy") == "host_confirmation":
            return True
        return audience == "host" and stage in {"proposed", "review", "final_adjustment"}

    def _metadata_for(
        self,
        audience: str,
        plan: dict[str, Any],
        intervention: dict[str, Any],
        review: dict[str, Any],
    ) -> dict[str, Any]:
        allowed: dict[str, Any] = {}
        if audience in {"host", "gm"}:
            allowed.update(self._safe_subset(plan, {
                "plan_id",
                "version",
                "status",
                "scene_type",
                "conflicts",
                "confirmed_by",
            }))
        elif audience == "agent":
            allowed.update(self._safe_subset(plan, {
                "plan_id",
                "version",
                "scene_type",
                "style_constraints",
                "spatial_constraints",
                "asset_constraints",
                "placement_constraints",
            }))
        else:
            allowed.update(self._safe_subset(plan, {
                "status",
                "scene_type",
            }))
        if intervention:
            allowed["intervention"] = self._safe_subset(intervention, {
                "intent_type",
                "apply_policy",
                "priority",
                "proposal_id",
                "requires_conflict_resolution",
                "target_hint",
                "status_message",
                "scheduler_update_summary",
            })
        if review:
            allowed["review"] = self._safe_subset(review, {
                "status",
                "warnings",
                "repair_count",
            })
        return allowed

    def _safe_subset(self, data: dict[str, Any], keys: set[str]) -> dict[str, Any]:
        result = {}
        for key in keys:
            if key in self._INTERNAL_KEYS:
                continue
            if key in data:
                result[key] = sanitize_public_payload(data[key])
        return result


__all__ = ["DisclosureEvent", "DisclosurePolicy"]
