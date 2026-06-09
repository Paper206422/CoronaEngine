import json
import logging
import os
import sys
from typing import Dict, List, Any, Optional

from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase
from CoronaCore.core.managers import scene_manager
from CoronaCore.utils.file_handler import FileHandler, _FILE_TYPE_CONFIG
from CoronaCore.utils.proejct_utils import (
    create_scene_from_template,
    get_project_scenes,
    set_project_scenes,
    append_project_scene,
)
from utils.settings import core_path, settings_manager
from plugins.SceneTools.main import SceneTools

logger = logging.getLogger(__name__)


@PluginBase.register_web("MainView")
class MainView(PluginBase):

    @staticmethod
    def on_init():
        project_path = settings_manager.active_project_path
        ini_path = os.path.join(project_path, 'project.ini') if project_path else None
        default_scene = settings_manager.active_project_config['Project']['entrance_scene']

        # 从 project.ini 读取有序场景列表
        ini_scenes = get_project_scenes(ini_path) if ini_path else []

        # 首次加载： ini 内没有列表时，自动扫描 Scene 目录并写回 ini
        if not ini_scenes and project_path:
            scene_dir = os.path.join(project_path, 'Scene')
            if os.path.isdir(scene_dir):
                ini_scenes = [
                    f'Scene/{f}'
                    for f in sorted(os.listdir(scene_dir))
                    if f.endswith('.scene')
                ]
            # 确保入口场景在列表中，且处于首位
            if default_scene not in ini_scenes:
                ini_scenes.insert(0, default_scene)
            elif ini_scenes[0] != default_scene:
                ini_scenes.remove(default_scene)
                ini_scenes.insert(0, default_scene)
            if ini_path:
                set_project_scenes(ini_path, ini_scenes)

        # 按 ini 列表顺序创建/获取场景对象，仅激活入口场景
        scenes = []
        for route in ini_scenes:
            try:
                s = scene_manager.get_or_create(route)
                s.set_enabled(route == default_scene)
                scenes.append({"path": s.route, "name": s.name})
            except Exception as e:
                logger.warning("加载场景 '%s' 失败，已跳过：%s", route, e)

        # 安全兄弟：如果入口场景不在列表中则补入头部
        if not any(s['path'] == default_scene for s in scenes):
            s = scene_manager.get_or_create(default_scene)
            s.set_enabled(True)
            scenes.insert(0, {"path": s.route, "name": s.name})
            if ini_path:
                set_project_scenes(ini_path, [default_scene] + ini_scenes)

        active_index = next((i for i, s in enumerate(scenes) if s['path'] == default_scene), 0)
        return {"scenes": scenes, "active_index": active_index}

    @staticmethod
    def create_new_scene(scene_name: str) -> dict:
        """在项目文件夹中创建场景文件，然后初始化引擎场景"""
        project_path = settings_manager.active_project_path
        if not project_path:
            raise ValueError("没有打开的项目")

        scene_dir = os.path.join(project_path, "Scene")
        actual_filename = create_scene_from_template(scene_dir, scene_name)
        route = f"Scene/{actual_filename}"

        scene = scene_manager.get_or_create(route)
        scene.ensure_default_camera()

        # 将新场景追加写入 project.ini
        ini_path = os.path.join(project_path, 'project.ini')
        append_project_scene(ini_path, route)

        logger.info("New scene file created: %s -> %s", scene_name, route)
        return {"path": route, "name": scene.name}

    @staticmethod
    def remove_scene(scene_path: str) -> dict:
        """从 project.ini 的 scenes 列表中移除指定场景，并禁用其引擎对象"""
        project_path = settings_manager.active_project_path
        if not project_path:
            raise ValueError("没有打开的项目")

        ini_path = os.path.join(project_path, 'project.ini')
        scenes = get_project_scenes(ini_path)
        if scene_path in scenes:
            scenes.remove(scene_path)
            set_project_scenes(ini_path, scenes)

        scene = scene_manager.get(scene_path)
        if scene:
            scene.set_enabled(False)

        logger.info("Scene removed from project: %s", scene_path)
        return {"status": "success", "path": scene_path}

    @staticmethod
    def switch_scene(current_scene_path: str, to_scene_path: str) -> bool:
        # 隐藏当前场景（仅禁用，不销毁任何 C++ 对象，避免 ProfileDevice 中的 handle 失效）
        if current_scene_path:
            now_scene = scene_manager.get(current_scene_path)
            if now_scene:
                now_scene.set_enabled(False)

        # 激活目标场景（若首次访问则自动创建并加载 actors）
        scene = scene_manager.get_or_create(to_scene_path)
        scene.set_enabled(True)

        CoronaEditor.js_call_func("actor-change", ['scene', scene.route, ""])
        return True

    @staticmethod
    def scene_save(scene_name: str) -> str:
        try:
            scene = scene_manager.get(scene_name)
            snap = scene.to_dict()

            content = json.dumps(snap, indent=2)
            save_path = FileHandler.save_file(
                content, "保存场景文件", "场景文件 (*.json)", default_filename=scene_name
            )
            if save_path:
                return json.dumps({"status": "success", "filepath": save_path})
            return json.dumps({"status": "canceled"})
        except Exception as exc:
            return json.dumps({"status": "error", "message": str(exc)})

    @staticmethod
    def import_resource_file(scene_name: str, file_type: str = "model") -> dict:
        try:
            """通用资源导入方法"""
            config = _FILE_TYPE_CONFIG.get(file_type)
            if not config:
                raise ValueError(f"不支持的文件类型: {file_type}")

            title, filter_str = config

            # 对于场景文件，传路径即可由 import_scene_file 自行解析
            read_content = False

            init_path = CoronaEditor.CoronaEngine.active_project_path if CoronaEditor.CoronaEngine.active_project_path else None

            content, file_path = FileHandler.open_file(title, filter_str, init_path, read_content=read_content,
                                                       return_relative_path=True)

            # 模型导入修复:用户取消文件选择时,显式返回 canceled 状态,
            # 让前端能正确区分"未选择"和"导入失败",避免静默无反馈
            if not file_path:
                logger.info("import_resource_file: user canceled file selection (scene=%s, type=%s)",
                            scene_name, file_type)
                return {"status": "canceled", "message": "用户取消了文件选择"}

            if not scene_name:
                return {"status": "error", "message": "scene_name is required", "code": "scene_name_missing"}

            # 场景文件通过路径解析
            if file_type == "scene":
                payload = MainView.import_scene_file(scene_name, file_path)
            elif file_type == "multimedia":
                # 音视频是独立资源，不创建 Actor（不走 Geometry/Scene 模型加载路径）
                payload = MainView.import_media(scene_name, file_path)
            else:
                # model 使用 import_model
                payload = MainView.import_model(scene_name, file_path, file_type)
            if payload is None:
                return {"status": "canceled", "message": "导入已取消"}
            if isinstance(payload, dict) and payload.get("status") == "error":
                # 下游 import_model/create_actor 已经显式返回错误,直接透传
                return payload
            return {"status": "success", **payload}
        except Exception as exc:
            logger.exception("import_resource_file 失败 (scene=%s, type=%s)", scene_name, file_type)
            return {"status": "error", "message": str(exc), "code": "internal_error"}

    @staticmethod
    def import_model(scene_name: str, model_path: str, file_type: str) -> dict:
        try:
            payload = SceneTools.create_actor(scene_name, model_path, file_type)
        except Exception as exc:
            logger.exception("import_model 失败 (scene=%s, path=%s)", scene_name, model_path)
            return {"status": "error", "message": str(exc), "code": "create_actor_failed"}
        # 透传 create_actor 的 status/error 状态
        if isinstance(payload, dict) and payload.get("status") == "error":
            return payload
        return payload

    @staticmethod
    def import_media(scene_name: str, file_path: str) -> dict:
        """导入音频/视频文件作为独立资源（不创建 Actor）

        通过 CoronaEngine.import_media 加载，返回资源 ID 与元数据，
        供前端加入资源列表。
        """
        # 相对路径转绝对路径（与 import_scene_file 保持一致）
        abs_path = file_path
        if not os.path.isabs(abs_path):
            project_path = CoronaEditor.CoronaEngine.active_project_path or ''
            abs_path = os.path.join(project_path, abs_path)

        import_media_fn = getattr(CoronaEditor.CoronaEngine, 'import_media', None)
        if import_media_fn is None:
            logger.error("import_media: CoronaEngine 未提供 import_media 接口")
            return {"status": "error",
                    "message": "engine import_media unavailable",
                    "code": "import_media_unavailable"}

        try:
            info = import_media_fn(abs_path)
        except Exception as exc:
            logger.exception("import_media 失败 (scene=%s, path=%s)", scene_name, file_path)
            return {"status": "error", "message": str(exc), "code": "import_media_failed"}

        media_type = getattr(info, 'media_type', '') or ''
        resource_id = getattr(info, 'resource_id', 0) or 0
        if not media_type or resource_id == 0:
            logger.error("import_media: 引擎无法解析为音视频 (path=%s)", file_path)
            return {"status": "error",
                    "message": f"无法识别的音视频文件: {file_path}",
                    "code": "media_unrecognized"}

        name = os.path.splitext(os.path.basename(file_path))[0]
        media = {
            "name": name,
            "path": file_path,
            "type": media_type,  # "video" / "audio"
            # resource_id 是 64 位整数，超过 JS Number.MAX_SAFE_INTEGER（约 9e15）会
            # 在前端被 double 截断，故以字符串形式传递，全程当字符串处理。
            "resource_id": str(resource_id),
            "duration": getattr(info, 'duration_seconds', 0.0),
            "codec": getattr(info, 'codec', ''),
            "width": getattr(info, 'width', 0),
            "height": getattr(info, 'height', 0),
            "fps": getattr(info, 'fps', 0.0),
            "sample_rate": getattr(info, 'sample_rate', 0),
            "channels": getattr(info, 'channels', 0),
        }
        logger.info("import_media: 已导入 %s 资源 '%s' (id=%s)", media_type, name, resource_id)
        return {"media": media}

    @staticmethod
    def import_scene_file(scene_name: str, file_path: str) -> dict:
        """从 .json 导出文件导入场景内容到当前场景"""
        # 将相对路径转为绝对路径
        if not os.path.isabs(file_path):
            project_path = CoronaEditor.CoronaEngine.active_project_path or ''
            file_path = os.path.join(project_path, file_path)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"场景文件不存在: {file_path}")

        with open(file_path, encoding='utf-8') as f:
            data = json.load(f)

        actors = []
        for actor in data.get("actors", []):
            result = SceneTools.create_actor(scene_name, actor.get("path"), data.get('actor_type', 'model'), data)
            actors.append(result.get("actor"))

        sun = data.get("sun", {})
        sun_direction = []
        if sun:
            sun_direction = sun.get("direction", [])
            if sun_direction:
                scene_manager.get_or_create(scene_name).set_sun_direction(sun_direction)

        logger.info("Scene '%s' imported from '%s'", scene_name, file_path)
        return {"scene": scene_name, "actors": actors, "sun_direction": sun_direction}

    @staticmethod
    def run_project(scene_path: Optional[str] = None) -> dict:
        """
        运行项目或场景。
        如果传入 scene_path，则运行指定场景；否则运行整个项目。
        同时加载并执行 Backend/runScript.py（由 Blockly 积木编辑器生成）。
        """
        import importlib

        try:
            if scene_path:
                scene = scene_manager.get(scene_path)
                if not scene:
                    return {"status": "error", "message": f"场景不存在: {scene_path}"}
                scene_name = scene.name
                logger.info(f"开始运行场景: {scene_name}")
            else:
                project_name = settings_manager.active_project_config['Project']['entrance_scene']
                scene_name = project_name
                logger.info("开始运行项目...")

            # ── 执行 Blockly 生成的脚本（如果存在） ──
            blockly_result = None
            run_script_path = core_path.repo_root / "Backend" / "runScript.py"
            if run_script_path.exists():
                try:
                    # 清除旧模块缓存，确保加载最新版本
                    modules_to_clear = [
                        name for name in sys.modules.keys()
                        if name.startswith('Backend.script.blockly_code')
                           or name in ('Backend.runScript', 'runScript')
                    ]
                    for mod_name in modules_to_clear:
                        del sys.modules[mod_name]

                    # 确保 repo_root 在 sys.path 中
                    backend_root = str(core_path.repo_root)
                    if backend_root not in sys.path:
                        sys.path.insert(0, backend_root)

                    from Backend import runScript
                    importlib.reload(runScript)
                    runScript.run()
                    logger.info("Blockly 脚本执行完成")
                    blockly_result = "executed"
                except Exception as e:
                    logger.exception(f"Blockly 脚本执行失败: {e}")
                    blockly_result = f"error: {e}"

            return {
                "status": "success",
                "type": "scene" if scene_path else "project",
                "scene_name": scene_name,
                "blockly_result": blockly_result,
            }
        except Exception as exc:
            logger.error(f"运行失败: {str(exc)}")
            return {"status": "error", "message": str(exc)}
