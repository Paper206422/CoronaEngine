"""把迁出的引擎相关工具 loader 注册回 CAI 的 ``ToolRegistry``。

通过 :func:`ai_tools.load_tools.register_extra_builtin_registrar` 注入。
"""

from __future__ import annotations

import logging

from Quasar.ai_tools.registry import (
    DependencyType,
    ToolCategory,
    ToolDependency,
    ToolRegistry,
)

logger = logging.getLogger(__name__)


def register_engine_loaders(registry: ToolRegistry) -> None:
    """在 CAI 内部 ``_register_builtin_loaders`` 末尾被调用。"""
    # MCP - 场景操作
    try:
        from .mcp.tools.scene_tools import load_scene_tools
        registry.register_loader(
            loader=load_scene_tools,
            category=ToolCategory.SCENE,
            dependencies=[],
            requires_config=False,
            source="cai_extensions.mcp.scene",
        )
    except ImportError as exc:
        logger.warning("scene_tools 注册失败（跳过）: %s", exc)

    # MCP - 摄像头
    try:
        from .mcp.tools.camera_tools import load_camera_tools
        registry.register_loader(
            loader=load_camera_tools,
            category=ToolCategory.SCENE,
            dependencies=[],
            requires_config=False,
            source="cai_extensions.mcp.camera",
        )
    except ImportError as exc:
        logger.warning("camera_tools 注册失败（跳过）: %s", exc)

    # MCP - 模型导入
    try:
        from .mcp.tools.model_import_tools import load_model_import_tools
        registry.register_loader(
            loader=load_model_import_tools,
            category=ToolCategory.SCENE,
            dependencies=[],
            requires_config=False,
            source="cai_extensions.mcp.model_import",
        )
    except ImportError as exc:
        logger.warning("model_import_tools 注册失败（跳过）: %s", exc)

    # 场景布置
    try:
        from .scene_placement.tools.placement_tools import load_placement_tools
        registry.register_loader(
            loader=load_placement_tools,
            category=ToolCategory.SCENE,
            dependencies=[
                # ToolDependency(DependencyType.CONFIG_PROVIDER, provider="rodin"),
            ],
            requires_config=True,
            source="cai_extensions.scene_placement",
        )
    except ImportError as exc:
        logger.warning("placement_tools 注册失败（跳过）: %s", exc)

    # 场景合理性审查
    try:
        from .mcp.tools.scene_review_tools import load_scene_review_tools
        registry.register_loader(
            loader=load_scene_review_tools,
            category=ToolCategory.SCENE,
            dependencies=[],
            requires_config=False,
            source="cai_extensions.mcp.scene_review",
        )
    except ImportError as exc:
        logger.warning("scene_review_tools 注册失败（跳过）: %s", exc)
