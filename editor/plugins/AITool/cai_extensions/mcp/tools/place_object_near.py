"""place_object_near 工具 — 基于锚点计算目标坐标 (纯计算, 不导入)。

LLM 描述空间关系, 工具计算精确坐标并返回。
导入由调用方 (tier2_place) 统一处理, 保持和 tier1 一致的数据流。
"""

from __future__ import annotations

import json
import logging
from typing import List, Literal, Optional, Tuple

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)
from pydantic import BaseModel, Field

from Quasar.ai_tools.response_adapter import (
    build_part,
    build_success_result,
    build_error_result,
)

DEFAULT_SCENE_NAME = ""


def _resolve_scene(scene_manager, scene_name: str):
    if scene_name:
        scene = scene_manager.get(scene_name)
        if scene is not None:
            return scene
        for route in scene_manager.list_all():
            s = scene_manager.get(route)
            if s is not None and getattr(s, "name", None) == scene_name:
                return s
    routes = scene_manager.list_all()
    if routes:
        return scene_manager.get(routes[0])
    return None


def _get_actor_position_and_aabb(
    actor,
) -> Optional[Tuple[List[float], Tuple[float, float, float, float, float, float]]]:
    """获取 actor 位置和 AABB。返回 (position, (min_x,min_y,min_z,max_x,max_y,max_z))。

    优先使用引擎 AABB; 获取失败时用 position + scale 估算默认包围盒,
    避免锚点计算完全失效导致绝对坐标回退 → 碰撞/堆叠。
    """
    pos = list(actor.get_position()) if hasattr(actor, "get_position") else [0, 0, 0]

    try:
        aabb = actor.get_world_aabb()
        return (pos, (aabb[0], aabb[1], aabb[2], aabb[3], aabb[4], aabb[5]))
    except Exception as e:
        logger.info("[aabb] get_world_aabb 失败: %s", e)
    geom = getattr(actor, "_geometry", None)
    if geom is not None:
        try:
            aabb = geom.get_aabb()
            return (pos, (aabb[0], aabb[1], aabb[2], aabb[3], aabb[4], aabb[5]))
        except Exception as e:
            logger.info("[aabb] _geometry.get_aabb 失败: %s", e)

    # 回退: 用 scale 估算包围盒。scale 反映模型原始尺寸的比例关系
    scale = [1.0, 1.0, 1.0]
    try:
        scale = list(actor.get_scale())
    except Exception:
        pass
    # 默认家具半尺寸 (米), 乘以 scale 得到实际半尺寸
    default_half = [0.4 * scale[0], 0.5 * scale[1], 0.4 * scale[2]]
    return (pos, (
        pos[0] - default_half[0], 0.0, pos[2] - default_half[2],
        pos[0] + default_half[0], default_half[1] * 2, pos[2] + default_half[2],
    ))


def calculate_position(
    ref_aabb: Tuple[float, float, float, float, float, float],
    relation: str,
    gap_m: float,
    obj_half_dx: float = 0.25,
    obj_half_dz: float = 0.25,
) -> List[float]:
    """纯函数: 根据参考物 AABB + 空间关系 + 间距计算目标位置。

    AABB: (min_x, min_y, min_z, max_x, max_y, max_z)
    Y=0 为地面, 物体底部对齐地面。
    可独立测试, 不依赖引擎。
    """
    min_x, min_y, min_z, max_x, max_y, max_z = ref_aabb
    cx = (min_x + max_x) / 2.0
    cz = (min_z + max_z) / 2.0

    relation = relation.lower()
    if relation == "left":
        return [min_x - gap_m - obj_half_dx, 0.0, cz]
    elif relation == "right":
        return [max_x + gap_m + obj_half_dx, 0.0, cz]
    elif relation == "front":
        return [cx, 0.0, min_z - gap_m - obj_half_dz]
    elif relation == "behind":
        return [cx, 0.0, max_z + gap_m + obj_half_dz]
    elif relation == "above":
        return [cx, max_y + gap_m, cz]
    elif relation == "below":
        return [cx, min_y - gap_m, cz]
    else:
        raise ValueError(f"Unknown relation: {relation}")


class PlaceObjectNearInput(BaseModel):
    object_id: str = Field(description="待放置物体的标识 ID")
    model_path: str = Field(description="待放置物体的 3D 模型文件路径")
    reference_actor: str = Field(description="参考物体的名称 (引擎中已存在的 actor)")
    relation: Literal["left", "right", "front", "behind", "above", "below"] = Field(
        description="相对参考物体的空间方位"
    )
    gap_m: float = Field(default=0.3, description="与参考物体的间距 (米)")
    scene_name: str = Field(
        default=DEFAULT_SCENE_NAME,
        description="目标场景名称，为空则使用当前场景",
    )


def _build_place_object_near_tool(scene_manager) -> StructuredTool:

    def _place_object_near(
        *,
        object_id: str,
        model_path: str,
        reference_actor: str,
        relation: str,
        gap_m: float = 0.3,
        scene_name: str = DEFAULT_SCENE_NAME,
    ) -> str:
        try:
            scene = _resolve_scene(scene_manager, scene_name)
            if scene is None:
                return build_error_result(
                    error_message="没有已加载的场景"
                ).to_envelope(interface_type="scene")

            ref_actor = scene.find_actor(reference_actor)
            if ref_actor is None:
                # case-insensitive fallback (引擎导入时可能改变大小写, 如 L型→l型)
                for a in scene.get_actors():
                    if a.name.lower() == reference_actor.lower():
                        ref_actor = a
                        break
            if ref_actor is None:
                available = [a.name for a in scene.get_actors()]
                return build_error_result(
                    error_message=f"参考物体 '{reference_actor}' 未找到。当前场景: {available}"
                ).to_envelope(interface_type="scene")

            result = _get_actor_position_and_aabb(ref_actor)
            if result is None:
                return build_error_result(
                    error_message=f"无法获取参考物体 '{reference_actor}' 的包围盒"
                ).to_envelope(interface_type="scene")

            ref_pos, ref_aabb = result
            pos = calculate_position(ref_aabb, relation, gap_m)

            payload = {
                "object_id": object_id,
                "model_path": model_path,
                "reference_actor": reference_actor,
                "reference_position": ref_pos,
                "reference_aabb": {
                    "min": list(ref_aabb[:3]),
                    "max": list(ref_aabb[3:]),
                },
                "relation": relation,
                "gap_m": gap_m,
                "calculated_position": pos,
                "rotation": [0.0, 0.0, 0.0],
                "scale": [1.0, 1.0, 1.0],
            }
            part = build_part(
                content_type="text",
                content_text=json.dumps(payload, ensure_ascii=False),
            )
            return build_success_result(parts=[part]).to_envelope(
                interface_type="scene"
            )
        except Exception as e:
            return build_error_result(error_message=str(e)).to_envelope(
                interface_type="scene"
            )

    return StructuredTool(
        name="place_object_near",
        description=(
            "基于参考物体的锚点计算目标位置 (纯计算, 不导入)。"
            "给定参考物体名称和空间方位, 返回计算后的 position/rotation/scale。"
            "left=左侧(-X), right=右侧(+X), front=前方(-Z), behind=后方(+Z), "
            "above=上方(+Y), below=下方(-Y)。"
        ),
        args_schema=PlaceObjectNearInput,
        func=_place_object_near,
    )


def load_place_object_near_tools() -> List[StructuredTool]:
    from CoronaCore.core.managers import scene_manager
    return [_build_place_object_near_tool(scene_manager)]


__all__ = ["load_place_object_near_tools", "calculate_position"]
