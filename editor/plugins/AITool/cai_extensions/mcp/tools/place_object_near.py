"""place_object_near 工具 — 基于锚点放置物体。

LLM 描述空间关系, 工具计算精确坐标并导入模型。
简化版: 仅支持 align="center"。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from Quasar.ai_tools.response_adapter import (
    build_part,
    build_success_result,
    build_error_result,
)

DEFAULT_SCENE_NAME = ""
SUPPORTED_EXTS = {".obj", ".dae", ".glb", ".gltf", ".fbx"}


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


def _pick_model_file(path: str) -> Optional[str]:
    if os.path.isfile(path):
        if Path(path).suffix.lower() in SUPPORTED_EXTS:
            return path
        return None
    if os.path.isdir(path):
        for ext in SUPPORTED_EXTS:
            for f in sorted(os.listdir(path)):
                if f.lower().endswith(ext):
                    return os.path.join(path, f)
    return None


def _get_actor_aabb(actor) -> Optional[Tuple[float, float, float, float, float, float]]:
    try:
        aabb = actor.get_world_aabb()
        return (aabb[0], aabb[1], aabb[2], aabb[3], aabb[4], aabb[5])
    except Exception:
        pass
    geom = getattr(actor, "_geometry", None)
    if geom is not None:
        try:
            aabb = geom.get_aabb()
            return (aabb[0], aabb[1], aabb[2], aabb[3], aabb[4], aabb[5])
        except Exception:
            pass
    return None


def _calc_position(
    ref_aabb: Tuple[float, float, float, float, float, float],
    relation: str,
    gap_m: float,
    obj_half_dx: float = 0.25,
    obj_half_dz: float = 0.25,
) -> List[float]:
    """根据参考物 AABB + 空间关系 + 间距计算目标位置。

    AABB: (min_x, min_y, min_z, max_x, max_y, max_z)
    Y=0 为地面, 物体底部对齐地面。
    """
    min_x, min_y, min_z, max_x, max_y, max_z = ref_aabb
    cx = (min_x + max_x) / 2.0
    cz = (min_z + max_z) / 2.0

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
    object_id: str = Field(description="待放置物体的标识 ID (同时作为 actor 名称)")
    model_path: str = Field(description="待放置物体的 3D 模型文件路径 (绝对路径或目录)")
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
            from CoronaCore.core.corona_editor import CoronaEditor
            CoronaEngine = CoronaEditor.CoronaEngine

            scene = _resolve_scene(scene_manager, scene_name)
            if scene is None:
                return build_error_result(
                    error_message="没有已加载的场景"
                ).to_envelope(interface_type="scene")

            ref_actor = scene.find_actor(reference_actor)
            if ref_actor is None:
                available = [a.name for a in scene.get_actors()]
                return build_error_result(
                    error_message=f"参考物体 '{reference_actor}' 未找到。当前场景: {available}"
                ).to_envelope(interface_type="scene")

            ref_aabb = _get_actor_aabb(ref_actor)
            if ref_aabb is None:
                return build_error_result(
                    error_message=f"无法获取参考物体 '{reference_actor}' 的包围盒"
                ).to_envelope(interface_type="scene")

            # 解析模型路径
            if os.path.isabs(model_path):
                resolved_path = model_path
            else:
                project_path = CoronaEngine.active_project_path
                if not project_path:
                    return build_error_result(
                        error_message="未设置活跃项目路径"
                    ).to_envelope(interface_type="scene")
                resolved_path = os.path.join(project_path, model_path)

            final_path = _pick_model_file(resolved_path)
            if final_path is None:
                return build_error_result(
                    error_message=f"找不到支持的模型文件: {resolved_path}"
                ).to_envelope(interface_type="scene")

            # 计算目标位置
            pos = _calc_position(ref_aabb, relation, gap_m)

            # 确定 actor 名称
            existing_names = {a.name for a in scene.get_actors()}
            name = object_id
            suffix = 1
            while name in existing_names:
                name = f"{object_id}_{suffix}"
                suffix += 1

            # 创建 Actor 并导入
            from CoronaCore.core.entities.actor import Actor

            actor = Actor(
                name=name,
                route=final_path,
                actor_type="mesh",
                parent_scene=scene,
            )
            actor.set_position(pos)
            scene.add_actor(actor)

            payload = {
                "status": "success",
                "object_id": object_id,
                "actor_name": actor.name,
                "reference_actor": reference_actor,
                "relation": relation,
                "gap_m": gap_m,
                "position": list(actor.get_position()),
                "model_path": final_path,
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
            "在参考物体旁边放置一个新物体。给定参考物体名称和空间方位，"
            "自动计算目标位置并导入模型到引擎场景。"
            "left=左侧(-X), right=右侧(+X), front=前方(-Z), behind=后方(+Z), "
            "above=上方(+Y), below=下方(-Y)。"
        ),
        args_schema=PlaceObjectNearInput,
        func=_place_object_near,
    )


def load_place_object_near_tools() -> List[StructuredTool]:
    from CoronaCore.core.managers import scene_manager
    return [_build_place_object_near_tool(scene_manager)]


__all__ = ["load_place_object_near_tools"]
