import json
import math
import os

from CoronaCore.core.components import Optics
from CoronaCore.core import network_sync_policy
from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase
from CoronaCore.core.entities import Actor
from CoronaCore.core.entities.camera import Camera
from CoronaCore.core.managers import scene_manager
from CoronaCore.utils.file_handler import FileHandler
try:
    from .vision_import import extract_vision_actor_imports
except ImportError:
    from vision_import import extract_vision_actor_imports

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


def _as_float3(value):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return None


def _normalize_vec3(value):
    vec = _as_float3(value)
    if vec is None:
        return None
    length = math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2])
    if length <= 1e-8:
        return None
    return [vec[0] / length, vec[1] / length, vec[2] / length]


def _extract_vision_camera_pose(document: dict):
    scene_data = document.get("scene", document) if isinstance(document, dict) else {}
    camera = None
    cameras = scene_data.get("cameras")
    if isinstance(cameras, list) and cameras:
        camera = cameras[0]
    if camera is None:
        camera = scene_data.get("camera") or document.get("camera")
    if not isinstance(camera, dict):
        return None

    params = camera.get("param") if isinstance(camera.get("param"), dict) else camera
    transform = params.get("transform") if isinstance(params.get("transform"), dict) else {}
    transform_params = (
        transform.get("param") if isinstance(transform.get("param"), dict) else transform
    )

    position = (
        _as_float3(transform_params.get("position"))
        or _as_float3(params.get("position"))
        or _as_float3(camera.get("position"))
    )
    up = (
        _normalize_vec3(transform_params.get("up"))
        or _normalize_vec3(params.get("up"))
        or _normalize_vec3(params.get("world_up"))
        or [0.0, 1.0, 0.0]
    )
    forward = (
        _normalize_vec3(transform_params.get("forward"))
        or _normalize_vec3(transform_params.get("direction"))
        or _normalize_vec3(params.get("forward"))
        or _normalize_vec3(params.get("direction"))
    )
    target = _as_float3(transform_params.get("target_pos") or transform_params.get("target"))
    if forward is None and position is not None and target is not None:
        forward = _normalize_vec3([
            target[0] - position[0],
            target[1] - position[1],
            target[2] - position[2],
        ])

    fov = (
        params.get("fov_y")
        or params.get("fov")
        or params.get("vfov")
        or camera.get("fov")
        or 45.0
    )
    try:
        fov = float(fov)
    except (TypeError, ValueError):
        fov = 45.0
    if 0.0 < fov <= math.pi:
        fov = math.degrees(fov)

    if position is None or forward is None:
        return None

    return {
        "name": str(params.get("name") or camera.get("name") or "VisionCamera"),
        "position": position,
        "forward": forward,
        "world_up": up,
        "fov": fov,
    }


@PluginBase.register_web("SceneTools")
class SceneTools(PluginBase):
    @staticmethod
    def _find_actor_by_guid(scene, actor_guid: str):
        if scene is None or not actor_guid:
            return None
        try:
            for candidate in scene.get_actors():
                if getattr(candidate, "actor_guid", "") == actor_guid:
                    return candidate
        except Exception:
            pass
        try:
            return scene.find_actor(actor_guid)
        except Exception:
            return None

    @staticmethod
    def _actor_sync_state(actor) -> dict:
        try:
            data = actor.to_dict()
        except Exception:
            data = {}
        data.setdefault("name", getattr(actor, "name", ""))
        data.setdefault("actor_guid", getattr(actor, "actor_guid", ""))
        data.setdefault("path", getattr(actor, "route", ""))
        data.setdefault("model", getattr(actor, "model_path", data.get("path", "")))
        data.setdefault("model_dependencies", list(getattr(actor, "model_dependencies", []) or []))
        data.setdefault("actor_type", getattr(actor, "actor_type", "model"))
        data.setdefault("visible", SceneTools._safe_actor_call(actor, "get_visible", True))
        data.setdefault("follow_camera", SceneTools._safe_actor_call(actor, "get_follow_camera", False))
        geometry = data.setdefault("geometry", {})
        geometry.setdefault("position", SceneTools._safe_actor_call(actor, "get_position", [0.0, 0.0, 0.0]))
        geometry.setdefault("rotation", SceneTools._safe_actor_call(actor, "get_rotation", [0.0, 0.0, 0.0]))
        geometry.setdefault("scale", SceneTools._safe_actor_call(actor, "get_scale", [1.0, 1.0, 1.0]))
        return {
            "actor_guid": data.get("actor_guid", ""),
            "name": data.get("name", ""),
            "actor_type": data.get("actor_type", "model"),
            "path": data.get("path") or data.get("model") or "",
            "model": data.get("model") or data.get("path") or "",
            "model_dependencies": data.get("model_dependencies", []),
            "visible": data.get("visible", True),
            "follow_camera": data.get("follow_camera", False),
            "geometry": data.get("geometry", {}),
        }

    @staticmethod
    def _canonical_actor_sync_state(actor_data) -> dict:
        data = actor_data if isinstance(actor_data, dict) else {}
        geometry = data.get("geometry") if isinstance(data.get("geometry"), dict) else {}

        def list_or_default(value, default):
            return list(value) if value is not None else list(default)

        return {
            "actor_guid": data.get("actor_guid", ""),
            "name": data.get("name", ""),
            "actor_type": data.get("actor_type", "model"),
            "path": data.get("path") or data.get("model") or "",
            "model": data.get("model") or data.get("path") or "",
            "model_dependencies": list(data.get("model_dependencies") or []),
            "visible": data.get("visible", True),
            "follow_camera": data.get("follow_camera", False),
            "geometry": {
                "position": list_or_default(geometry.get("position"), [0.0, 0.0, 0.0]),
                "rotation": list_or_default(geometry.get("rotation"), [0.0, 0.0, 0.0]),
                "scale": list_or_default(geometry.get("scale"), [1.0, 1.0, 1.0]),
            },
        }

    @staticmethod
    def _actor_sync_states_equal(local_actor, remote_actor_data) -> bool:
        local_state = SceneTools._canonical_actor_sync_state(
            SceneTools._actor_sync_state(local_actor))
        remote_state = SceneTools._canonical_actor_sync_state(remote_actor_data)
        return local_state == remote_state

    @staticmethod
    def _actor_snapshot_block_reason(actor_data) -> str | None:
        if not isinstance(actor_data, dict):
            return network_sync_policy.actor_data_sync_block_reason(actor_data)
        policy_data = dict(actor_data)
        # The receiver adds this flag to prevent rebroadcast loops; it should not
        # make an otherwise valid host snapshot actor ineligible for apply.
        policy_data.pop("_suppress_network_broadcast", None)
        return network_sync_policy.actor_data_sync_block_reason(policy_data)

    @staticmethod
    def _safe_actor_call(actor, method_name: str, default=None):
        if actor is None or not hasattr(actor, method_name):
            return default
        try:
            return getattr(actor, method_name)()
        except Exception:
            return default

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
    def get_actor_sync_snapshot(scene_name: str) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}
            actors = []
            for actor in scene.get_actors():
                actor_state = SceneTools._actor_sync_state(actor)
                actor_state["scene"] = actor_state.get("scene") or scene_name
                if not actor_state.get("actor_guid"):
                    continue
                if SceneTools._actor_snapshot_block_reason(actor_state) is not None:
                    continue
                actors.append(actor_state)
            return {"status": "success", "scene": scene_name, "actors": actors}
        except Exception as exc:
            logger.exception("get_actor_sync_snapshot failed")
            return {"status": "error", "message": str(exc), "code": "internal_error"}

    @staticmethod
    def apply_actor_state_internal(scene_name: str, actor_guid: str, actor_data=None) -> dict:
        """Apply remote actor metadata and transform by actor_guid without rebroadcasting."""
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}
            actor = SceneTools._find_actor_by_guid(scene, actor_guid)
            if actor is None:
                return {"status": "warning",
                        "message": f"Actor guid '{actor_guid}' not found",
                        "code": "actor_not_found",
                        "actor_guid": actor_guid}

            actor_data = actor_data or {}
            previous_network_remote = getattr(actor, "network_remote", False)
            previous_suppress = getattr(actor, "_suppress_network_broadcast", False)
            actor.network_remote = True
            actor._suppress_network_broadcast = True
            try:
                if actor_data.get("name"):
                    actor.name = str(actor_data["name"])
                geometry = actor_data.get("geometry") or {}
                if "position" in geometry and hasattr(actor, "set_position"):
                    actor.set_position(geometry["position"], if_init=True)
                if "rotation" in geometry and hasattr(actor, "set_rotation"):
                    actor.set_rotation(geometry["rotation"], if_init=True)
                if "scale" in geometry and hasattr(actor, "set_scale"):
                    actor.set_scale(geometry["scale"], if_init=True)
                if "visible" in actor_data and hasattr(actor, "set_visible"):
                    actor.set_visible(actor_data["visible"])
                if "follow_camera" in actor_data and hasattr(actor, "set_follow_camera"):
                    actor.set_follow_camera(actor_data["follow_camera"], if_init=True)
            finally:
                actor.network_remote = previous_network_remote
                actor._suppress_network_broadcast = previous_suppress
            try:
                scene.save_data()
                if hasattr(scene, "_notify_scene_tree_changed"):
                    scene._notify_scene_tree_changed()
            except Exception:
                logger.debug("apply_actor_state_internal: save/notify failed", exc_info=True)
            return {"status": "success", "scene": scene_name, "actor": actor.to_dict()}
        except Exception as exc:
            logger.exception("apply_actor_state_internal failed")
            return {"status": "error", "message": str(exc), "code": "internal_error"}

    @staticmethod
    def apply_actor_sync_snapshot_internal(scene_name: str, snapshot=None) -> dict:
        """Apply a host actor snapshot. Missing local actors are created; absent host actors are never deleted."""
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}
            actors = snapshot.get("actors") if isinstance(snapshot, dict) else snapshot
            if not isinstance(actors, list):
                actors = []
            created = []
            updated = []
            unchanged = []
            warnings = []
            for actor_data in actors:
                if not isinstance(actor_data, dict):
                    continue
                actor_guid = actor_data.get("actor_guid", "")
                if not actor_guid:
                    continue
                block_reason = SceneTools._actor_snapshot_block_reason(actor_data)
                if block_reason is not None:
                    warnings.append({"status": "warning",
                                     "code": block_reason,
                                     "actor_guid": actor_guid,
                                     "actor": actor_data.get("name", "")})
                    continue
                existing = SceneTools._find_actor_by_guid(scene, actor_guid)
                if existing is not None:
                    if SceneTools._actor_sync_states_equal(existing, actor_data):
                        unchanged.append(SceneTools._actor_sync_state(existing))
                        continue
                    result = SceneTools.apply_actor_state_internal(
                        scene_name, actor_guid, actor_data)
                    if result.get("status") == "success":
                        updated.append(result.get("actor", {}))
                    else:
                        warnings.append(result)
                    continue

                asset_path = actor_data.get("path") or actor_data.get("model") or ""
                if not asset_path:
                    warnings.append({"status": "warning",
                                     "code": "missing_model_path",
                                     "actor_guid": actor_guid})
                    continue
                create_data = dict(actor_data)
                create_data["_suppress_network_broadcast"] = True
                try:
                    result = SceneTools.create_actor_internal(
                        scene_name,
                        asset_path,
                        create_data.get("actor_type", "model"),
                        create_data,
                    )
                except FileNotFoundError as exc:
                    logger.info(
                        "apply_actor_sync_snapshot_internal: skip actor with missing asset "
                        "scene=%s actor=%s guid=%s path=%s error=%s",
                        scene_name,
                        actor_data.get("name", ""),
                        actor_guid,
                        asset_path,
                        exc,
                    )
                    warnings.append({
                        "status": "warning",
                        "code": "missing_asset",
                        "actor_guid": actor_guid,
                        "actor": actor_data.get("name", ""),
                        "path": asset_path,
                        "message": str(exc),
                    })
                    continue
                actor_result = result.get("actor") if isinstance(result, dict) else None
                if actor_result:
                    created.append(actor_result)
                else:
                    warnings.append(result)
            return {
                "status": "success",
                "scene": scene_name,
                "created": created,
                "updated": updated,
                "unchanged": unchanged,
                "warnings": warnings,
            }
        except Exception as exc:
            logger.exception("apply_actor_sync_snapshot_internal failed")
            return {"status": "error", "message": str(exc), "code": "internal_error"}

    @staticmethod
    def apply_actor_transform_internal(scene_name: str, actor_guid: str, actor_data=None) -> dict:
        """Apply a remote actor transform without re-broadcasting it."""
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}

            actor = SceneTools._find_actor_by_guid(scene, actor_guid)
            if actor is None:
                return {"status": "error",
                        "message": f"Actor guid '{actor_guid}' not found",
                        "code": "actor_not_found"}

            geometry = (actor_data or {}).get("geometry") or {}
            if "position" in geometry:
                actor.set_position(geometry["position"], if_init=True)
            if "rotation" in geometry:
                actor.set_rotation(geometry["rotation"], if_init=True)
            if "scale" in geometry:
                actor.set_scale(geometry["scale"], if_init=True)
            try:
                scene.save_data()
            except Exception:
                logger.debug("apply_actor_transform_internal: save_data failed", exc_info=True)
            return {"status": "success", "scene": scene_name, "actor": actor.to_dict()}
        except Exception as exc:
            logger.exception("apply_actor_transform_internal failed")
            return {"status": "error", "message": str(exc), "code": "internal_error"}

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

        actor_data = actor_data or {}
        actor_guid = actor_data.get("actor_guid", "") if isinstance(actor_data, dict) else ""
        existing_actor = SceneTools._find_actor_by_guid(scene, actor_guid)
        if existing_actor is not None:
            applied = SceneTools.apply_actor_state_internal(scene_name, actor_guid, actor_data)
            if applied.get("status") == "success":
                return {"scene": scene_name, "actor": applied.get("actor")}
            return applied

        actor = Actor(route=asset_path,
                      source_index=existing_count,
                      actor_type=actor_type,
                      parent_scene=scene,
                      actor_data=actor_data)
        scene.add_actor(actor)
        if actor_data.get("_suppress_network_broadcast"):
            actor.network_remote = False
            actor._suppress_network_broadcast = False
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
    def rename_actor(scene_name: str, actor_name: str, new_name: str) -> dict:
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                raise ValueError(f"Scene '{scene_name}' not found")
            actor = scene.find_actor(actor_name)
            if actor is None:
                raise ValueError(f"Actor '{actor_name}' not found")
            normalized_name = str(new_name or "").strip()
            if not normalized_name:
                raise ValueError("Actor name cannot be empty")
            if any(other is not actor and other.name == normalized_name
                   for other in scene.get_actors()):
                raise ValueError(f"Actor name '{normalized_name}' already exists")

            old_name = actor.name
            actor.name = normalized_name
            scene.save_data()
            scene._notify_scene_tree_changed()
            try:
                if not getattr(actor, "_suppress_network_broadcast", False) and not getattr(actor, "network_remote", False):
                    CoronaEditor.js_call_func("actor-state-sync-broadcast", [actor.to_dict()])
            except Exception:
                logger.debug("rename_actor: state broadcast failed", exc_info=True)
            return {
                "status": "success",
                "scene": scene_name,
                "actor": actor.to_dict(),
                "old_name": old_name,
                "new_name": normalized_name,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def remove_actor_internal(scene_name: str, actor_guid: str = "", actor_name: str = "") -> dict:
        """Apply a remote actor deletion without re-broadcasting it."""
        try:
            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error",
                        "message": f"Scene '{scene_name}' not found",
                        "code": "scene_not_found"}

            actor = None
            if actor_guid:
                for candidate in scene.get_actors():
                    if getattr(candidate, "actor_guid", "") == actor_guid:
                        actor = candidate
                        break
            if actor is None and actor_name:
                actor = scene.find_actor(actor_name)
            if actor is None and actor_guid:
                actor = scene.find_actor(actor_guid)
            if actor is None:
                return {"status": "warning",
                        "message": f"Actor '{actor_guid or actor_name}' not found",
                        "code": "actor_not_found",
                        "actor_guid": actor_guid,
                        "actor": actor_name}

            actor.network_remote = True
            actor._suppress_network_broadcast = True
            scene.remove_actor(actor)
            logger.info("Remote actor %s/%s removed from %s",
                        actor_guid, actor_name, scene_name)
            return {"status": "success",
                    "scene": scene_name,
                    "actor_guid": actor_guid,
                    "actor": actor_name or getattr(actor, "name", "")}
        except Exception as exc:
            logger.exception("remove_actor_internal failed")
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
    def import_vision_scene_into_current_scene(scene_name: str, path: str) -> dict:
        try:
            if not scene_name:
                return {"status": "error", "message": "scene_name is required"}
            if not path:
                return {"status": "error", "message": "Vision scene path is required"}
            if not CoronaEditor.CoronaEngine.is_vision_available():
                return {"status": "error", "message": "Vision backend is not available in this build"}

            abs_path = os.path.abspath(path)
            if not os.path.isfile(abs_path):
                return {"status": "error", "message": f"Vision scene file not found: {abs_path}"}

            with open(abs_path, "r", encoding="utf-8") as f:
                document = json.load(f)

            scene = scene_manager.get(scene_name)
            if scene is None:
                return {"status": "error", "message": f"Scene '{scene_name}' not found"}

            camera_pose = _extract_vision_camera_pose(document)
            vision_actor_imports = extract_vision_actor_imports(document, abs_path)
            scene.ensure_default_camera()
            active_camera = scene.get_active_camera()
            camera_imported = False
            if camera_pose is not None and active_camera is not None:
                active_camera.name = camera_pose["name"] or active_camera.name
                scene.set_camera(
                    camera_pose["position"],
                    camera_pose["forward"],
                    camera_pose["world_up"],
                    camera_pose["fov"],
                    active_camera.camera_id,
                )
                camera_imported = True

            active_camera = scene.get_active_camera()
            if active_camera is not None:
                active_camera.set_render_backend("vision")
                if hasattr(scene.engine_scene, "set_active_camera"):
                    scene.engine_scene.set_active_camera(getattr(active_camera, "engine_obj", active_camera))

            imported_actors = []
            imported_guids = {
                actor_data["actor_guid"]
                for actor_data in vision_actor_imports["actors"]
            }
            existing_by_guid = {
                getattr(actor, "actor_guid", ""): actor
                for actor in scene.get_actors()
                if getattr(actor, "actor_guid", "")
            }
            source_guid_prefix = f"vision:{abs_path}#"
            for actor in scene.get_actors():
                actor_guid = getattr(actor, "actor_guid", "")
                if actor_guid.startswith(source_guid_prefix) and actor_guid not in imported_guids:
                    scene.remove_actor(actor)

            for actor_data in vision_actor_imports["actors"]:
                actor = existing_by_guid.get(actor_data["actor_guid"])
                if actor is None:
                    actor = Actor(actor_data["name"],
                                  actor_data["route"],
                                  actor_type=actor_data["actor_type"],
                                  parent_scene=scene,
                                  actor_data=actor_data)
                    scene.add_actor(actor)
                else:
                    actor.actor_type = actor_data["actor_type"]
                    actor.actor_guid = actor_data["actor_guid"]
                    if getattr(actor, "route", None) != actor_data["route"]:
                        actor.route = actor_data["route"]
                        actor.set_model(actor_data["route"])
                    geometry_state = actor_data.get("geometry") or {}
                    if "position" in geometry_state:
                        actor.set_position(geometry_state["position"])
                    if "rotation" in geometry_state:
                        actor.set_rotation(geometry_state["rotation"])
                    if "scale" in geometry_state:
                        actor.set_scale(geometry_state["scale"])
                optics_state = actor_data.get("optics") or {}
                optics = getattr(actor, "_optics", None)
                for key, value in optics_state.items():
                    setter = getattr(optics, f"set_{key}", None)
                    if setter is not None:
                        setter(value)
                imported_actors.append(actor.to_dict())

            if "vision" not in scene.file_data:
                scene.file_data["vision"] = {}
            scene.vision_source_path = abs_path
            scene.vision_import_mode = "engine_built"
            scene.file_data["vision"]["source_path"] = abs_path
            scene.file_data["vision"]["import_mode"] = "engine_built"
            scene.save_data()

            scene._notify_scene_tree_changed()
            logger.info("Vision scene imported into current scene %s: %s", scene_name, abs_path)
            return {
                "status": "success",
                "scene": scene_name,
                "path": abs_path,
                "import_mode": "engine_built",
                "imported_actor_count": len(imported_actors),
                "imported_actors": imported_actors,
                "unsupported_shapes": vision_actor_imports["unsupported_shapes"],
                "camera_imported": camera_imported,
                "camera": active_camera.to_dict() if active_camera is not None else None,
            }
        except json.JSONDecodeError as exc:
            return {"status": "error", "message": f"Invalid Vision JSON: {exc}"}
        except Exception as exc:
            logger.exception("import_vision_scene_into_current_scene failed")
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
