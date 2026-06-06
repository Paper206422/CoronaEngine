from CoronaCore.core.corona_editor import CoronaEditor
from CoronaCore.core.managers import scene_manager
from CoronaCore.utils.file_handler import FileHandler, _FILE_TYPE_CONFIG
from CoronaPlugin.core.corona_plugin_base import PluginBase
import logging
import threading

logger = logging.getLogger(__name__)


@PluginBase.register_web("SceneDatas")
class SceneDatas(PluginBase):

    _save_timers = {}
    _save_lock = threading.Lock()

    @classmethod
    def _schedule_save(cls, actor, delay=0.5):
        """延迟保存：合并短时间内的多次操作，只在最后一次操作后写磁盘"""
        actor_key = id(actor)
        with cls._save_lock:
            old_timer = cls._save_timers.pop(actor_key, None)
            if old_timer is not None:
                old_timer.cancel()

            def _do_save():
                try:
                    actor.save_data()
                except Exception as e:
                    logger.error("Deferred save failed for actor: %s", e)
                finally:
                    with cls._save_lock:
                        cls._save_timers.pop(actor_key, None)

            timer = threading.Timer(delay, _do_save)
            cls._save_timers[actor_key] = timer
            timer.start()

    @staticmethod
    def save_actor(scene_name: str, actor_name: str) -> dict:
        """仅触发写盘：Transform 数据已由 C++ 快速通道写入 SharedDataHub，
        此方法仅负责将数据持久化到 .ini 文件。"""
        if scene_name:
            scene = scene_manager.get(scene_name)
            actor = scene.find_actor(actor_name)
        else:
            actor = scene_manager.find_actor(actor_name)
        if actor is None:
            raise ValueError(f"Actor '{actor_name}' not found")

        actor.save_data()
        logger.info("Saved actor '%s' to disk", actor_name)
        return {"status": "success", "scene": scene_name, "actor": actor_name}

    @staticmethod
    def get_scene(scene_name: str) -> dict:
        scene = scene_manager.get(scene_name)
        return scene.to_dict()

    @staticmethod
    def get_actor(scene_name: str, actor_name: str) -> dict:
        logger.info(f"Getting actor '{actor_name}' from scene '{scene_name}'")
        # 追踪最后选中的场景和单位，供 JS 注入面板使用
        from CoronaCore.core.corona_editor import CoronaEditor
        CoronaEditor._selected_scene = scene_name
        CoronaEditor._selected_actor = actor_name

        if scene_name:
            scene = scene_manager.get(scene_name)
            actor = scene.get_actor(actor_name)
        else:
            actor = scene_manager.find_actor(actor_name)
        return actor.to_dict()

    @staticmethod
    def actor_operation(scene_name: str, actor_name: str, operation: str, vector: list) -> dict:

        if scene_name:
            scene = scene_manager.get(scene_name)
            actor = scene.find_actor(actor_name)
        else:
            actor = scene_manager.find_actor(actor_name)
        if actor is None:
            raise ValueError(f"Actor '{actor_name}' not found")

        if operation == "Scale":
            actor.set_scale(vector, if_init=True)
            SceneDatas._schedule_save(actor)
        elif operation == "Move":
            actor.set_position(vector, if_init=True)
            SceneDatas._schedule_save(actor)
        elif operation == "Rotate":
            actor.set_rotation(vector, if_init=True)
            SceneDatas._schedule_save(actor)
        elif operation == "SetMass":
            actor.set_mass(float(vector[0]))
        elif operation == "SetRestitution":
            actor.set_restitution(float(vector[0]))
        elif operation == "SetDamping":
            actor.set_damping(float(vector[0]))
        elif operation == "SetVisible":
            actor.set_visible(bool(vector[0]))
        elif operation == "SetCameraLock":
            actor.set_camera_lock_enabled(bool(vector[0]))
        elif operation == "SetCameraLockOffset":
            actor.set_camera_lock_offset(vector)
        elif operation == "SetCameraLockRotation":
            actor.set_camera_lock_rotation_offset(vector)
        elif operation == "SetCollision":
            actor.set_collision_enabled(str(vector[0]))
        else:
            raise ValueError(f"Unsupported operation '{operation}'")

        logger.info("Applied %s%s to %s", operation, vector, actor_name)
        return {"scene": scene_name, "actor": actor_name, "operation": operation, "vector": vector}

    @staticmethod
    def select_model_file(scene_name: str, actor_name: str, file_type: str = "model") -> str:
        config = _FILE_TYPE_CONFIG.get(file_type)
        if not config:
            raise ValueError(f"不支持的文件类型: {file_type}")

        title, filter_str = config

        init_path = CoronaEditor.CoronaEngine.active_project_path if CoronaEditor.CoronaEngine.active_project_path else None
        content, file_path = FileHandler.open_file(title, filter_str, init_path, read_content=False,
                                                   return_relative_path=True)
        logger.info(file_path)
        if not file_path:
            return ""

        scene = scene_manager.get(scene_name)
        if scene:
            actor = scene.get_actor(actor_name)
        else:
            actor = scene_manager.find_actor(actor_name)
        if file_type == "model":
            if actor:
                actor.set_model(file_path)
        elif file_type == "script":
            if actor:
                actor.set_script(file_path)
            elif scene:
                scene.set_script(file_path)
        elif file_type == "terrain":
            if scene:
                scene.set_terrain(file_path)
        return file_path
