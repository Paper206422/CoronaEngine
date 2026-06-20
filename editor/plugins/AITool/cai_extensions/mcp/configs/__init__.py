"""
场景操作工具提示词配置

包含：
- SCENE_QUERY_PROMPTS: 场景查询工具提示词
- SCENE_TRANSFORM_PROMPTS: 场景变换工具提示词
- SCENE_TOOL_PROMPTS: 场景工具提示词集合
"""

from __future__ import annotations

from Quasar.ai_config.prompts import ToolPromptConfig, SceneToolPrompts

# ===========================================================================
# 场景查询工具提示词
# ===========================================================================

SCENE_QUERY_PROMPTS = ToolPromptConfig(
    tool_description="查询场景中的模型，例如列出全部模型或按名称查找。",
    fields={
        "scene_name": "要查询的场景名称",
        "query_type": "查询类型",
        "model_name": "目标场景名称",
    },
)

# ===========================================================================
# 场景变换工具提示词
# ===========================================================================

SCENE_TRANSFORM_PROMPTS = ToolPromptConfig(
    tool_description=(
        "对模型执行相对变换：translate/move 为位置增量，rotate_delta/rotate 为旋转增量，"
        "scale_delta/scale 为按比例缩放。需要绝对位置/旋转/缩放时使用 set_actor_transform。"
        "坐标系：X正为右，Y正为上，Z正为朝屏幕里侧（左手坐标系）。"
    ),
    fields={
        "model_name": "需要变换的模型名称",
        "transform_type": "相对变换类型：translate/move、rotate_delta/rotate、scale_delta/scale",
        "value": "缩放倍率；例如 1.2 表示在当前缩放基础上放大 20%",
        "axis": "相对变换向量 [x,y,z]。坐标系：X正为右，Y正为上，Z正为朝屏幕里侧",
        "relative": "是否相对变换",
    },
)

# ===========================================================================
# 场景工具提示词集合
# ===========================================================================

SCENE_TOOL_PROMPTS = SceneToolPrompts(
    query=SCENE_QUERY_PROMPTS,
    transform=SCENE_TRANSFORM_PROMPTS,
)

