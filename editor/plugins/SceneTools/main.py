import json
import math
import os
from pathlib import Path

from CoronaCore.core.components import Optics
from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase
from CoronaCore.core.entities import Actor
from CoronaCore.core.entities.camera import Camera
from CoronaCore.core.managers import scene_manager
from CoronaCore.utils.file_handler import FileHandler

import logging

logger = logging.getLogger(__name__)


def _active_project_path():
    try:
        from utils.settings import settings_manager
        if settings_manager.active_project_path:
            return settings_manager.active_project_path
    except Exception:
        pass
    return getattr(CoronaEditor.CoronaEngine, "active_project_path", None)


@PluginBase.register_web("SceneTools")
class SceneTools(PluginBase):
    @staticmethod
    def _camera_view_payload(scene, camera) -> dict:
        payload = camera.to_dict()
        payload["scene_id"] = scene.route
        return payload

    @staticmethod
    def create_actor(scene_name: str, asset_path: str, actor_type: str = 'model', actor_data=None) -> dict:
        # B-1 + 模型导入修复:场景不存在时不再崩溃,
        # 改为通过 get_or_create 自动补建并返回明确错误信息,避免前端静默失败
        return SceneTools._create_actor_impl(scene_name, asset_path, actor_type, actor_data)

    @staticmethod
    def create_actor_internal(scene_name: str, asset_path: str, actor_type: str = 'model', actor_data=None) -> dict:
        """纯后端 Actor 创建（不发 JS 回调，避免远程同步时触发前端死循环）。
        文件传输完成后由 C++ CEF bridge 调用此方法。"""
        return SceneTools._create_actor_impl(scene_name, asset_path, actor_type, actor_data,
                                             notify_frontend=False)

    @staticmethod
    def ensure_3d_cursor_actor(scene_name: str) -> dict:
        scene = scene_manager.get(scene_name)
        if scene is None:
            try:
                scene = scene_manager.get_or_create(scene_name)
            except Exception as exc:
                logger.error("ensure_3d_cursor_actor: 场景 '%s' 不存在且无法创建: %s", scene_name, exc)
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}
        if scene is None:
            return {"status": "error",
                    "message": f"Scene '{scene_name}' not found",
                    "code": "scene_not_found"}

        existing = getattr(scene, "_editor_3d_cursor_actor", None)
        if existing is not None:
            try:
                if hasattr(existing, "set_editor_temporary"):
                    existing.set_editor_temporary(True)
                existing.set_visible(False)
                existing.set_physics_enabled(False)
                existing.set_collision_enabled("none")
            except Exception:
                logger.exception("ensure_3d_cursor_actor: 重置已有临时光标状态失败")
            return {
                "status": "success",
                "actorHandle": int(getattr(existing, "handle", 0) or 0),
                "cursor": {
                    "actorHandle": int(getattr(existing, "handle", 0) or 0),
                    "name": getattr(existing, "name", "__editor_3d_cursor__"),
                },
            }

        cursor_asset = Path(__file__).resolve().parents[3] / "assets" / "editor" / "Ball.obj"
        actor_data = {
            "_suppress_network_broadcast": True,
            "_editor_temporary": True,
            "actor_guid": f"__editor_3d_cursor__:{scene_name}",
            "name": "__editor_3d_cursor__",
            "geometry": {
                "position": [0.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0],
                "scale": [0.1, 0.1, 0.1],
            },
            "optics": {
                "visible": False,
            },
            "mechanics": {
                "physics_enabled": False,
                "collision_type": "none",
            },
        }

        actor = Actor(route=str(cursor_asset),
                      source_index=0,
                      actor_type="model",
                      parent_scene=scene,
                      actor_data=actor_data)
        actor.name = "__editor_3d_cursor__"
        if hasattr(actor, "set_editor_temporary"):
            actor.set_editor_temporary(True)
        actor.set_visible(False)
        actor.set_physics_enabled(False)
        actor.set_collision_enabled("none")
        actor.set_scale([0.1, 0.1, 0.1], True)

        engine_scene = getattr(scene, "engine_scene", None)
        engine_actor = getattr(actor, "engine_obj", None)
        if engine_scene is not None and engine_actor is not None and hasattr(engine_scene, "add_actor"):
            engine_scene.add_actor(engine_actor)
        scene._editor_3d_cursor_actor = actor

        handle = int(getattr(actor, "handle", 0) or 0)
        return {
            "status": "success",
            "actorHandle": handle,
            "cursor": {
                "actorHandle": handle,
                "name": actor.name,
            },
        }

    @staticmethod
    def _create_actor_impl(scene_name: str, asset_path: str, actor_type: str = 'model',
                           actor_data=None, notify_frontend: bool = True) -> dict:
        scene = scene_manager.get(scene_name)
        if scene is None:
            try:
                scene = scene_manager.get_or_create(scene_name)
            except Exception as exc:
                logger.error("create_actor: 场景 '%s' 不存在且无法创建: %s", scene_name, exc)
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}
        if scene is None:
            logger.error("create_actor: scene '%s' still None after get_or_create", scene_name)
            return {"status": "error",
                    "message": f"Scene '{scene_name}' not found",
                    "code": "scene_not_found"}

        existing_count = 0
        try:
            existing_count = sum(1 for a in scene._actors if a.route == asset_path)
        except Exception as exc:
            logger.warning("create_actor: 统计同路径 actor 失败 (%s),按 0 处理: %s", scene_name, exc)
            existing_count = 0

        actor = Actor(route=asset_path,
                      source_index=existing_count,
                      actor_type=actor_type,
                      parent_scene=scene,
                      actor_data=actor_data)
        scene.add_actor(actor)
        logger.info("Actor %s added to %s type %s", actor.name, scene_name, actor_type)
        if notify_frontend:
            CoronaEditor.js_call_func("import-asset-complete", actor.to_dict())
        return {"scene": scene_name, "actor": actor.to_dict()}

    @staticmethod
    def create_scene(scene_name: str) -> dict:
        if not scene_name:
            raise ValueError("sceneName is required")
        scene = scene_manager.create(scene_name)
        scene.ensure_default_camera()
        actors = scene.get_actors()
        for actor in actors:
            actor._optics = Optics(actor._geometry)
            scene.add_actor(actor, True)
        return scene.to_dict()

    @staticmethod
    def remove_actor(scene_name: str, actor_name: str) -> dict:
        """从场景移除 Actor

        B-1 修复:不再 raise ValueError,改为返回 error dict
        与同模块其他方法(focus_actor / camera_move 等)保持一致,
        前端可统一通过 success===false / status==='error' 判定失败。
        """
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}
            actor = scene.find_actor(actor_name)
            if actor is None:
                return {"status": "error",
                        "message": f"Actor '{actor_name}' not found",
                        "code": "actor_not_found"}
            scene.remove_actor(actor)
            logger.info("Actor %s removed from %s", actor_name, scene_name)
            return {"status": "success", "scene": scene_name, "actor": actor_name}
        except Exception as exc:
            logger.exception("remove_actor 失败")
            return {"status": "error", "message": str(exc), "code": "internal_error"}

    @staticmethod
    def sun_direction(scene_name: str, if_enable: bool, direction: list[float]) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            scene.set_sun_direction(direction)
            logger.info("Sun direction set for %s", scene_name)
            return {"status": "success"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def floor_grid(scene_name: str, enabled: bool) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            scene.set_floor_grid(enabled)
            logger.info("Floor grid set for %s: %s", scene_name, enabled)
            return {"status": "success"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def set_physics_params(scene_name: str, gravity: list = None, floor_y: float = None,
                           floor_restitution: float = None, fixed_dt: float = None) -> dict:
        """设置场景物理参数"""
        try:
            scene = scene_manager.get(scene_name)
            if gravity is not None:
                scene.set_gravity(gravity)
            if floor_y is not None:
                scene.set_floor_y(floor_y)
            if floor_restitution is not None:
                scene.set_floor_restitution(floor_restitution)
            if fixed_dt is not None:
                scene.set_fixed_dt(fixed_dt)
            logger.info("Physics params set for %s", scene_name)
            return {"status": "success"}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def get_physics_params(scene_name: str) -> dict:
        """获取场景物理参数"""
        try:
            scene = scene_manager.get(scene_name)
            return {
                "status": "success",
                "gravity": scene.get_gravity(),
                "floor_y": scene.get_floor_y(),
                "floor_restitution": scene.get_floor_restitution(),
                "fixed_dt": scene.get_fixed_dt(),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def save_screenshot(scene_name: str, path: str, camera_name: str = None) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                raise ValueError(f"Scene '{scene_name}' not found")
            camera = scene.find_camera(camera_name)
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found in scene '{scene_name}'")
            camera.save_screenshot(path)
            logger.info("Screenshot saved for scene %s camera %s to %s",
                        scene_name, getattr(camera, 'name', camera_name), path)
            return {"status": "success", "path": path}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def set_output_mode(scene_name: str, camera_name: str = None, mode: str = "final_color") -> dict:
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                raise ValueError(f"Scene '{scene_name}' not found")
            camera = scene.find_camera(camera_name)
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found in scene '{scene_name}'")
            camera.set_output_mode(mode)
            logger.info("Output mode set to '%s' for scene %s camera %s",
                        mode, scene_name, getattr(camera, 'name', camera_name))
            return {"status": "success", "mode": mode}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def get_output_mode(scene_name: str, camera_name: str = None) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                raise ValueError(f"Scene '{scene_name}' not found")
            camera = scene.find_camera(camera_name)
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found in scene '{scene_name}'")
            mode = camera.get_output_mode()
            return {"status": "success", "mode": mode}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def is_vision_available() -> dict:
        try:
            available = bool(CoronaEditor.CoronaEngine.is_vision_available())
            return {"status": "success", "available": available}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def set_render_backend(mode: str = "native", scene_name: str = None,
                           camera_name: str = None) -> dict:
        try:
            if scene_name:
                scene = scene_manager.get(scene_name)
                if scene is None:
                    raise ValueError(f"Scene '{scene_name}' not found")
                camera = scene.find_camera(camera_name)
                if camera is None:
                    raise ValueError(f"Camera '{camera_name}' not found")
                camera.set_render_backend(mode)
                scene.save_data()
                actual = camera.get_render_backend()
            else:
                CoronaEditor.CoronaEngine.set_render_backend(mode)
                actual = CoronaEditor.CoronaEngine.get_render_backend()
            return {
                "status": "success",
                "mode": actual,
                "fallback": mode == "vision" and actual != "vision",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def get_render_backend(scene_name: str = None, camera_name: str = None) -> dict:
        try:
            if scene_name:
                scene = scene_manager.get(scene_name)
                if scene is None:
                    raise ValueError(f"Scene '{scene_name}' not found")
                camera = scene.find_camera(camera_name)
                if camera is None:
                    raise ValueError(f"Camera '{camera_name}' not found")
                mode = camera.get_render_backend()
            else:
                mode = CoronaEditor.CoronaEngine.get_render_backend()
            return {"status": "success", "mode": mode}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def create_camera_view(scene_name: str, name: str = None) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                raise ValueError(f"Scene '{scene_name}' not found")
            source = scene.get_active_camera()
            if source is None:
                raise ValueError("No source camera is available")

            existing_names = {camera.name for camera in scene.get_cameras()}
            base_name = name or "Camera"
            candidate = base_name
            suffix = 1
            while candidate in existing_names:
                candidate = f"{base_name}_{suffix}"
                suffix += 1

            index = len(scene.get_cameras())
            camera = Camera(
                position=list(source.get_position()),
                forward=list(source.get_forward()),
                world_up=list(source.get_world_up()),
                fov=float(source.get_fov()),
                name=candidate,
                width=source.width,
                height=source.height,
                render_backend=source.get_render_backend(),
                output_mode=source.get_output_mode(),
                move_speed=source.move_speed,
                view_open=True,
                view_x=120 + index * 36,
                view_y=120 + index * 36,
                view_width=960,
                view_height=540,
            )
            camera.set_surface(0)
            scene.add_camera_to_scene(camera)
            scene._notify_scene_tree_changed()
            return {"status": "success", "camera": SceneTools._camera_view_payload(scene, camera)}
        except Exception as exc:
            logger.exception("create_camera_view failed")
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def open_camera_view(scene_name: str, camera_name: str) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            camera = scene.find_camera(camera_name) if scene else None
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found")
            camera.set_view_state(
                True, camera.view_x, camera.view_y,
                camera.view_width, camera.view_height, camera.move_speed)
            scene.save_data()
            return {"status": "success", "camera": SceneTools._camera_view_payload(scene, camera)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def close_camera_view(scene_name: str, camera_name: str) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            camera = scene.find_camera(camera_name) if scene else None
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found")
            camera.refresh_view_state()
            camera.set_view_state(
                False, camera.view_x, camera.view_y,
                camera.view_width, camera.view_height, camera.move_speed)
            camera.set_surface(0)
            scene.save_data()
            return {"status": "success", "camera": SceneTools._camera_view_payload(scene, camera)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def rename_camera_view(scene_name: str, camera_name: str, new_name: str) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            camera = scene.find_camera(camera_name) if scene else None
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found")
            if not new_name.strip():
                raise ValueError("Camera name cannot be empty")
            if any(other is not camera and other.name == new_name.strip()
                   for other in scene.get_cameras()):
                raise ValueError(f"Camera name '{new_name}' already exists")
            camera.name = new_name.strip()
            scene.save_data()
            scene._notify_scene_tree_changed()
            return {"status": "success", "camera": SceneTools._camera_view_payload(scene, camera)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def list_camera_views(scene_name: str) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                raise ValueError(f"Scene '{scene_name}' not found")
            return {
                "status": "success",
                "cameras": [
                    SceneTools._camera_view_payload(scene, camera)
                    for camera in scene.get_cameras()
                ],
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def update_camera_view(scene_name: str, camera_name: str, state: dict) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            camera = scene.find_camera(camera_name) if scene else None
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found")
            camera.set_view_state(
                bool(state.get("view_open", camera.view_open)),
                int(state.get("view_x", camera.view_x)),
                int(state.get("view_y", camera.view_y)),
                int(state.get("view_width", camera.view_width)),
                int(state.get("view_height", camera.view_height)),
                float(state.get("move_speed", camera.move_speed)),
            )
            if "width" in state or "height" in state:
                camera.set_size(
                    int(state.get("width", camera.width)),
                    int(state.get("height", camera.height)))
            scene.save_data()
            return {"status": "success", "camera": SceneTools._camera_view_payload(scene, camera)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def delete_camera(scene_name: str, camera_name: str) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            camera = scene.find_camera(camera_name) if scene else None
            if camera is None:
                raise ValueError(f"Camera '{camera_name}' not found")
            if len(scene.get_cameras()) <= 1:
                raise ValueError("A scene must keep at least one camera")
            if not getattr(camera, 'deletable', True):
                raise ValueError("The main camera cannot be deleted")
            camera.set_surface(0)
            scene.remove_camera_from_scene(camera)
            scene._notify_scene_tree_changed()
            return {"status": "success", "camera_id": camera.camera_id}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def load_vision_scene(path: str = "") -> dict:
        try:
            if not CoronaEditor.CoronaEngine.is_vision_available():
                return {"status": "error", "message": "Vision backend is not available in this build"}
            CoronaEditor.CoronaEngine.load_vision_scene(path)
            logger.info("Vision scene load requested: %s", path or "<unload>")
            return {"status": "success", "path": path}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def select_vision_scene_path() -> dict:
        try:
            _content, path = FileHandler.open_file(
                caption="打开 Vision 场景",
                file_types="Vision 场景 (*.json)",
                read_content=False,
                return_relative_path=False,
            )
            if not path:
                return {"status": "canceled", "path": ""}
            return {"status": "success", "path": path}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def select_screenshot_path(scene_name: str, camera_name: str = None) -> dict:
        try:
            init_path = _active_project_path()
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"screenshot_{timestamp}.png"

            path = FileHandler.choose_save_path(
                caption="保存截图",
                file_types="PNG 图片 (*.png)",
                default_dir=init_path,
                default_filename=default_filename,
                return_relative_path=False,
            )

            if not path:
                return {"status": "canceled", "path": ""}

            return {"status": "success", "path": path, "camera_name": camera_name}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def list_actor_tree(scene_name) -> list:
        scene = scene_manager.get(scene_name)
        final_list = []
        for actor in scene.get_actors():
            final_list.append({
                "name": actor.name,
                "path": actor.route,
                "type": actor.actor_type,
            })
        return final_list

    @staticmethod
    def list_scene_tree(scene_name: str) -> dict:
        scene = scene_manager.get(scene_name)
        if scene is None:
            raise ValueError(f"Scene '{scene_name}' not found")

        actors = []
        for actor in scene.get_actors():
            actors.append({
                "name": actor.name,
                "path": actor.route,
                "type": actor.actor_type,
                "visible": actor.get_visible(),
                "handle": int(getattr(actor, "handle", 0) or 0),
            })

        cameras = []
        for cam in scene.get_cameras():
            camera_info = None
            if cam is not None and hasattr(cam, 'to_dict'):
                camera_info = cam.to_dict()
            elif cam is not None:
                camera_info = {"name": getattr(cam, 'name', 'Unknown')}
            cameras.append(camera_info)

        return {"actors": actors, "cameras": cameras}

    @staticmethod
    def focus_actor(scene_name: str, actor_name: str, camera_name: str = None) -> dict:
        """将摄像头聚焦到指定 Actor 上（基于 AABB 中心和尺寸）"""
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                raise ValueError(f"Scene '{scene_name}' not found")

            actor = scene.find_actor(actor_name)
            if actor is None:
                raise ValueError(f"Actor '{actor_name}' not found in scene '{scene_name}'")

            camera = scene.find_camera(camera_name)
            if camera is None:
                raise ValueError(f"No camera available in scene '{scene_name}'")

            # 获取 actor AABB
            if not hasattr(actor, '_geometry') or actor._geometry is None:
                raise ValueError(f"Actor '{actor_name}' has no geometry")

            aabb = actor._geometry.get_aabb()  # [min_x, min_y, min_z, max_x, max_y, max_z] (模型空间)

            # 获取 Actor 世界变换
            actor_pos = actor.get_position()   # 世界位置
            actor_scale = actor.get_scale()    # 缩放

            # 将模型空间 AABB 中心转换到世界空间（忽略旋转的近似值）
            model_center = [
                (aabb[0] + aabb[3]) / 2.0,
                (aabb[1] + aabb[4]) / 2.0,
                (aabb[2] + aabb[5]) / 2.0,
            ]
            center = [
                actor_pos[0] + model_center[0] * actor_scale[0],
                actor_pos[1] + model_center[1] * actor_scale[1],
                actor_pos[2] + model_center[2] * actor_scale[2],
            ]

            # 计算世界空间 AABB 对角线长度
            dx = (aabb[3] - aabb[0]) * actor_scale[0]
            dy = (aabb[4] - aabb[1]) * actor_scale[1]
            dz = (aabb[5] - aabb[2]) * actor_scale[2]
            diagonal = math.sqrt(dx * dx + dy * dy + dz * dz)

            # 摄像头距离：对角线的 2 倍，最小为 1.0
            distance = max(diagonal * 2.0, 1.0)


            # 摄像头放在物体中心的 -Z 方向，朝向 +Z（看向物体中心）
            forward = [0.0, 0.0, 1.0]

            # 新摄像头位置 = 中心 - forward * 距离（即 center_z - distance）
            position = [
                center[0],
                center[1],
                center[2] - distance,
            ]

            up = [0.0, 1.0, 0.0]
            fov = camera.get_fov()

            camera.set(position, forward, up, fov)

            logger.info(
                "Camera focused on actor '%s': aabb=%s center=%s distance=%.2f pos=%s fwd=%s up=%s",
                actor_name, aabb, center, distance, position, forward, up,
            )
            return {"status": "success", "center": center, "distance": distance}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def open_actor(scene_name: str, actor_name: str):
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                logger.error(f"open_actor: scene '{scene_name}' not found")
                return False
            actor = scene.get_actor(actor_name)
            if actor is None:
                logger.error(f"open_actor: actor '{actor_name}' not found in scene '{scene_name}'")
                return False
            CoronaEditor.js_call_func("actor-change", [actor.actor_type, scene_name, actor_name])
            return True
        except Exception as e:
            logger.error(f"open actor error: {e}")
            return False

    @staticmethod
    def pick_actor_at_pixel(scene_name: str, x: float, y: float,
                            vp_width: float, vp_height: float) -> dict:
        """
        鼠标在3D视口中拾取物体。

        引擎的 pick_actor_at_pixel 是异步的：第一次调用设置GPU拾取请求并返回0，
        需要等待一帧（约16ms）后再次调用才能获取拾取结果。
        前端应在第一次调用后等待约50ms再重试。

        Args:
            scene_name: 场景名称
            x, y: 浏览器视口中的鼠标坐标 (event.clientX, event.clientY)
            vp_width, vp_height: 浏览器视口尺寸 (window.innerWidth, innerHeight)
        Returns:
            {"status": "success", "actor": {...}}  拾取成功
            {"status": "miss"}                      该位置没有物体
            {"status": "pending"}                   结果尚未就绪，需重试
            {"status": "error", "message": "..."}   出错
        """
        try:
            # 获取当前场景和活动摄像机
            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error", "message": f"场景 '{scene_name}' 未找到"}

            camera = scene.get_active_camera()
            if camera is None:
                return {"status": "error", "message": "没有可用的摄像机"}

            # 坐标缩放：浏览器视口坐标 -> 摄像机渲染分辨率坐标
            cam_w = camera.width
            cam_h = camera.height
            if vp_width <= 0 or vp_height <= 0:
                return {"status": "error", "message": "无效的视口尺寸"}
            pick_x = int(x * cam_w / vp_width)
            pick_y = int(y * cam_h / vp_height)

            # 边界检查
            if pick_x < 0 or pick_x >= cam_w or pick_y < 0 or pick_y >= cam_h:
                return {"status": "miss"}

            # 调用引擎拾取API（第一次调用设置拾取请求，返回0或缓存的命中结果）
            handle = camera.pick_actor_at_pixel(pick_x, pick_y)

            if handle != 0:
                # 命中物体：通过handle查找对应的Python Actor对象
                from CoronaCore.core.entities.actor import _handle_to_actor
                actor = _handle_to_actor.get(handle)
                if actor is not None:
                    # 设置选中状态并通知前端更新属性面板
                    CoronaEditor._selected_scene = scene_name
                    CoronaEditor._selected_actor = actor.name
                    CoronaEditor.js_call_func(
                        "actor-change",
                        [actor.actor_type, scene_name, actor.name]
                    )
                    logger.info(
                        "Viewport pick hit: actor='%s' at pixel (%d, %d)",
                        actor.name, pick_x, pick_y
                    )
                    return {"status": "success", "actor": actor.to_dict()}
                else:
                    # handle存在但Python对象已被GC回收
                    logger.warning(
                        "Viewport pick: handle %d 未找到对应的 Python Actor", handle
                    )
                    return {"status": "miss"}

            # handle == 0：无缓存结果，拾取请求已提交，需等待下一帧
            return {"status": "pending"}

        except Exception as e:
            logger.error("pick_actor_at_pixel error: %s", e)
            return {"status": "error", "message": str(e)}
