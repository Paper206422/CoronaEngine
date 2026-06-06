"""get_scene_snapshot 工具 — 一键返回引擎当前场景的结构化状态。

供 LLM 在布局前了解当前场景中的物体、位置、AABB，避免碰撞。
"""

from __future__ import annotations

import json
from typing import List, Optional

from langchain_core.tools import StructuredTool
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


class SceneSnapshotInput(BaseModel):
    scene_name: str = Field(
        default=DEFAULT_SCENE_NAME,
        description="目标场景名称，为空则使用当前场景",
    )


def _build_scene_snapshot_tool(scene_manager) -> StructuredTool:

    def _scene_snapshot(*, scene_name: str = DEFAULT_SCENE_NAME) -> str:
        try:
            scene = _resolve_scene(scene_manager, scene_name)
            if scene is None:
                return build_error_result(
                    error_message="No scene loaded"
                ).to_envelope(interface_type="scene")

            actors_list = []
            for actor in scene.get_actors():
                entry: dict = {
                    "name": actor.name,
                    "actor_type": getattr(actor, "actor_type", "unknown"),
                }

                model_path = getattr(actor, "model_path", "")
                if model_path:
                    entry["model_path"] = model_path

                try:
                    entry["position"] = list(actor.get_position())
                    entry["rotation"] = list(actor.get_rotation())
                    entry["scale"] = list(actor.get_scale())
                except Exception:
                    pass

                # AABB (世界空间包围盒)
                try:
                    aabb = actor.get_world_aabb()
                    entry["aabb_min"] = [aabb[0], aabb[1], aabb[2]]
                    entry["aabb_max"] = [aabb[3], aabb[4], aabb[5]]
                    entry["size"] = [
                        aabb[3] - aabb[0],
                        aabb[4] - aabb[1],
                        aabb[5] - aabb[2],
                    ]
                except Exception:
                    # 回退: 尝试 _geometry.get_aabb()
                    geom = getattr(actor, "_geometry", None)
                    if geom is not None:
                        try:
                            aabb = geom.get_aabb()
                            entry["aabb_min"] = [aabb[0], aabb[1], aabb[2]]
                            entry["aabb_max"] = [aabb[3], aabb[4], aabb[5]]
                            entry["size"] = [
                                aabb[3] - aabb[0],
                                aabb[4] - aabb[1],
                                aabb[5] - aabb[2],
                            ]
                        except Exception:
                            pass

                actors_list.append(entry)

            result_data = {
                "scene_name": getattr(scene, "name", scene_name),
                "actor_count": len(actors_list),
                "actors": actors_list,
            }
            part = build_part(
                content_type="text",
                content_text=json.dumps(result_data, ensure_ascii=False),
            )
            return build_success_result(parts=[part]).to_envelope(
                interface_type="scene"
            )
        except Exception as e:
            return build_error_result(error_message=str(e)).to_envelope(
                interface_type="scene"
            )

    return StructuredTool(
        name="get_scene_snapshot",
        description=(
            "获取当前引擎场景的完整结构化状态，包括所有物体的名称、类型、模型路径、"
            "位置(position[x,y,z])、旋转(rotation[deg])、缩放(scale)和世界空间包围盒(AABB)。"
            "坐标: X+右, Y+上, Z+屏幕内侧。用于布局前了解场景现状、检测重叠、计算间距。"
        ),
        args_schema=SceneSnapshotInput,
        func=_scene_snapshot,
    )


def load_scene_snapshot_tools() -> List[StructuredTool]:
    from CoronaCore.core.managers import scene_manager
    return [_build_scene_snapshot_tool(scene_manager)]


__all__ = ["load_scene_snapshot_tools"]
