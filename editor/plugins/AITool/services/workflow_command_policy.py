from __future__ import annotations

import os


DEPRECATED_USER_WORKFLOW_COMMANDS = frozenset({
    "/scene_agent",
    "/sc_agent",
    "/scene_composition",
    "/scene_composition_v2",
    "/sc_v2",
    "/full_pipeline",
    "/pipeline",
    "/full_pipeline_v2",
    "/fp_v2",
    "/multi_scene",
    "/parallel_generate",
    "/parallel_generate_v2",
    "/pg_v2",
})

INTERNAL_DEBUG_WORKFLOW_COMMANDS = frozenset({
    "/model_retrieval",
    "/terrain_generate",
    "/terrain",
})

DEPRECATED_WORKFLOW_COMMAND_MESSAGE = (
    "该旧工作流入口已废弃。请在聊天室中先讨论并确认生成方案，"
    "再通过统一的 AI 场景生成链路执行。"
)


def normalize_workflow_command(command: str) -> str:
    value = str(command or "").strip().lower()
    if value and not value.startswith("/"):
        value = f"/{value}"
    return value


def is_deprecated_user_workflow_command(command: str) -> bool:
    return normalize_workflow_command(command) in DEPRECATED_USER_WORKFLOW_COMMANDS


def is_internal_debug_workflow_command(command: str) -> bool:
    return normalize_workflow_command(command) in INTERNAL_DEBUG_WORKFLOW_COMMANDS


def should_register_workflow_command(command: str) -> bool:
    normalized = normalize_workflow_command(command)
    if not normalized:
        return False
    if os.getenv("CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS", "").strip() == "1":
        return True
    if normalized in DEPRECATED_USER_WORKFLOW_COMMANDS:
        return False
    if normalized in INTERNAL_DEBUG_WORKFLOW_COMMANDS:
        return os.getenv("CORONA_ENABLE_INTERNAL_WORKFLOW_COMMANDS", "").strip() == "1"
    return True


__all__ = [
    "DEPRECATED_USER_WORKFLOW_COMMANDS",
    "INTERNAL_DEBUG_WORKFLOW_COMMANDS",
    "DEPRECATED_WORKFLOW_COMMAND_MESSAGE",
    "is_deprecated_user_workflow_command",
    "is_internal_debug_workflow_command",
    "normalize_workflow_command",
    "should_register_workflow_command",
]
