import json
import math
import os

from CoronaCore.core.components import Optics
from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase
from CoronaCore.core.entities import Actor
from CoronaCore.core.managers import scene_manager
from CoronaCore.utils.file_handler import FileHandler

import logging

logger = logging.getLogger(__name__)


@PluginBase.register_web("SceneTools")
class SceneTools(PluginBase):

    @staticmethod
    def create_actor(scene_name: str, asset_path: str, actor_type: str = 'model', actor_data=None) -> dict:
        # B-1 + 模型导入修复:场景不存在时不再崩溃,
        # 改为通过 get_or_create 自动补建并返回明确错误信息,避免前端静默失败
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
    def set_render_backend(mode: str = "native") -> dict:
        try:
            if not CoronaEditor.CoronaEngine.is_vision_available():
                return {"status": "error", "message": "Vision backend is not available in this build"}
            CoronaEditor.CoronaEngine.set_render_backend(mode)
            logger.info("Render backend switch requested: %s", mode)
            return {"status": "success", "mode": mode}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def get_render_backend() -> dict:
        try:
            mode = CoronaEditor.CoronaEngine.get_render_backend()
            return {"status": "success", "mode": mode}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def select_screenshot_path(scene_name: str, camera_name: str = None) -> dict:
        try:
            init_path = CoronaEditor.CoronaEngine.active_project_path if CoronaEditor.CoronaEngine.active_project_path else None
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