"""set_actor_transform 工具 — 绝对设置引擎中 actor 的位置/旋转/缩放。

区别于 transform_model（相对操作），本工具直接设置绝对坐标。
同时更新关联的 scene.json 文件保持一致性。
"""

from __future__ import annotations

import json
import os
from typing import List, Optional, Tuple

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from Quasar.ai_tools.response_adapter import (
    build_part,
    build_success_result,
    build_error_result,
)

from .transform_grounding import resolve_actor_overlaps, snap_actor_to_ground

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


def _try_update_scene_json(
    actor_name: str,
    position: Optional[List[float]],
    rotation: Optional[List[float]],
    scale: Optional[List[float]],
) -> bool:
    """尝试更新关联的 scene.json 文件中的 actor transform。"""
    try:
        from CoronaCore.core.managers import scene_manager as sm

        scene = _resolve_scene(sm, "")
        if scene is None:
            return False

        scene_path = getattr(scene, "scene_path", None)
        if not scene_path or not os.path.exists(scene_path):
            return False

        with open(scene_path, "r", encoding="utf-8") as f:
            scene_data = json.load(f)

        actors = scene_data.get("actors", [])
        updated = False
        for a in actors:
            if a.get("name") == actor_name:
                geom = a.setdefault("geometry", {})
                if position is not None:
                    geom["pos"] = position
                if rotation is not None:
                    geom["rot"] = rotation
                if scale is not None:
                    geom["scale"] = scale
                updated = True
                break

        if updated:
            with open(scene_path, "w", encoding="utf-8") as f:
                json.dump(scene_data, f, ensure_ascii=False, indent=2)

        return updated
    except Exception:
        return False


class SetActorTransformInput(BaseModel):
    scene_name: str = Field(
        default=DEFAULT_SCENE_NAME,
        description="目标场景名称，为空则使用当前场景",
    )
    actor_name: str = Field(description="要修改的物体名称")
    position: Optional[Tuple[float, float, float]] = Field(
        default=None,
        description="绝对位置 [x, y, z]，不传则不修改",
    )
    rotation: Optional[Tuple[float, float, float]] = Field(
        default=None,
        description="绝对旋转 [rx, ry, rz] (欧拉角，弧度)，不传则不修改；用户说角度时需先转换为弧度",
    )
    scale: Optional[Tuple[float, float, float]] = Field(
        default=None,
        description="绝对缩放 [sx, sy, sz]，不传则不修改",
    )
    snap_to_ground: bool = Field(
        default=True,
        description="变换后是否按当前模型 AABB 自动贴地，默认开启以减少缩放后的底座穿模",
    )
    ground_y: float = Field(
        default=0.0,
        description="贴地目标高度，默认世界地面/平台高度 0",
    )
    ground_clearance: float = Field(
        default=0.02,
        description="贴地后的安全抬高余量，避免底座与地面轻微穿模",
    )


def _build_set_actor_transform_tool(scene_manager) -> StructuredTool:

    def _set_actor_transform(
        *,
        scene_name: str = DEFAULT_SCENE_NAME,
        actor_name: str,
        position: Optional[Tuple[float, float, float]] = None,
        rotation: Optional[Tuple[float, float, float]] = None,
        scale: Optional[Tuple[float, float, float]] = None,
        snap_to_ground: bool = True,
        ground_y: float = 0.0,
        ground_clearance: float = 0.02,
    ) -> str:
        try:
            if position is None and rotation is None and scale is None:
                return build_error_result(
                    error_message="至少需要提供 position / rotation / scale 中的一个"
                ).to_envelope(interface_type="scene")

            scene = _resolve_scene(scene_manager, scene_name)
            if scene is None:
                return build_error_result(
                    error_message="No scene loaded"
                ).to_envelope(interface_type="scene")

            actor = scene.find_actor(actor_name)
            if actor is None:
                # shell 外壳 actor 实际名带 __shell_ 前缀（如 "__shell_蒙古包"），
                # 但用户/LLM 只说 "蒙古包"。精确匹配失败时回退到带前缀名。
                actor = scene.find_actor(f"__shell_{actor_name}")
            if actor is None:
                return build_error_result(
                    error_message=f"Actor '{actor_name}' not found"
                ).to_envelope(interface_type="scene")

            pos_list = list(position) if position is not None else None
            rot_list = list(rotation) if rotation is not None else None
            scl_list = list(scale) if scale is not None else None

            if pos_list is not None:
                actor.set_position(pos_list)
            if rot_list is not None:
                actor.set_rotation(rot_list)
            if scl_list is not None:
                actor.set_scale(scl_list)

            snap_position = None
            overlap_result = None
            if snap_to_ground and (pos_list is not None or scl_list is not None):
                snap_position = snap_actor_to_ground(
                    actor,
                    ground_y=ground_y,
                    clearance=ground_clearance,
                )
                if snap_position is not None:
                    pos_list = snap_position
                try:
                    overlap_result = resolve_actor_overlaps(
                        actor,
                        [a for a in scene.get_actors() if a is not actor],
                    )
                    if overlap_result and overlap_result.get("changed"):
                        pos_list = list(actor.get_position())
                except Exception:
                    overlap_result = None

            # 同步更新 scene.json
            json_updated = _try_update_scene_json(
                actor_name, pos_list, rot_list, scl_list
            )

            payload = {
                "actor": actor_name,
                "position": list(actor.get_position()),
                "rotation": list(actor.get_rotation()),
                "scale": list(actor.get_scale()),
                "ground_snapped": snap_position is not None,
                "overlap_resolved": bool(overlap_result and overlap_result.get("changed")),
                "scene_json_updated": json_updated,
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
        name="set_actor_transform",
        description=(
            "绝对设置引擎场景中物体的位置/旋转/缩放。"
            "与 transform_model（相对偏移）不同，本工具直接设置绝对坐标。"
            "传入 None 的字段保持不变。"
            "坐标: X+右, Y+上, Z+屏幕内侧。旋转单位为弧度(欧拉角)，例如 90度=1.5708。"
        ),
        args_schema=SetActorTransformInput,
        func=_set_actor_transform,
    )


def load_set_actor_transform_tools() -> List[StructuredTool]:
    from CoronaCore.core.managers import scene_manager
    return [_build_set_actor_transform_tool(scene_manager)]


__all__ = ["load_set_actor_transform_tools"]
