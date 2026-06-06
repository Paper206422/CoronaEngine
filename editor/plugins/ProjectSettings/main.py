import json
import os
import configparser
import logging
import datetime
from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase
from CoronaCore.utils.file_handler import FileHandler
from utils.settings import settings_manager

logger = logging.getLogger(__name__)


@PluginBase.register_web("ProjectSettings")
class ProjectSettings(PluginBase):

    @staticmethod
    def get_active_project_info() -> dict:
        """
        获取当前激活项目的配置信息
        :return: 配置数据
        """
        if not settings_manager.active_project_path:
            return {"error": "未激活任何项目", "data": {}}

        try:
            # 直接调用 settings_manager 的方法
            full_info = settings_manager.get_active_project_info()
            # 提取 Project 节
            project_info = full_info.get('Project', {})

            # 确保必需字段存在
            defaults = {
                'name': 'project',
                'mode': '3d',
                'entrance_scene': '',
                'core_version': '1.0.0',
                'create_time': '',
                'last_opened': ''
            }
            for key, default_value in defaults.items():
                if key not in project_info or not project_info[key]:
                    project_info[key] = default_value

            return {"data": project_info, "success": True}
        except Exception as e:
            logger.error(f"读取项目配置失败: {e}")
            return {"error": str(e), "data": {}}

    @staticmethod
    def save_active_project_info(settings: dict) -> dict:
        """
        保存当前激活项目的配置
        :param settings: 要保存的配置字典 (包含 name, mode, entrance_scene, core_version 等)
        :return: 操作结果
        """
        if not settings_manager.active_project_path:
            return {"success": False, "error": "未激活任何项目"}

        try:
            # 获取当前项目的配置对象
            config = settings_manager.active_project_config
            if config is None:
                # 如果内存中没有，尝试从文件加载（正常情况下应该存在）
                import configparser
                ini_path = os.path.join(settings_manager.active_project_path, "project.ini")
                config = configparser.ConfigParser()
                if os.path.exists(ini_path):
                    config.read(ini_path, encoding='utf-8')
                settings_manager.active_project_config = config

            if not config.has_section('Project'):
                config.add_section('Project')

            # 更新允许修改的字段
            allowed_keys = ['name', 'mode', 'entrance_scene', 'core_version']
            for key in allowed_keys:
                if key in settings and settings[key]:
                    config.set('Project', key, str(settings[key]))

            # 调用 settings_manager 的方法写入文件并更新 last_opened
            success = settings_manager.save_active_project_info()
            if success:
                return {"success": True, "data": {"message": "保存成功"}}
            else:
                return {"success": False, "error": "保存失败"}
        except Exception as e:
            logger.error(f"保存项目配置失败: {e}")
            return {"success": False, "error": str(e)}

    @staticmethod
    def browse_scene_file() -> dict:
        """
        浏览当前项目中的场景文件
        :return: 选择的场景文件相对路径
        """
        if not settings_manager.active_project_path:
            return {"error": "未激活任何项目", "path": ""}

        project_path = settings_manager.active_project_path
        try:
            default_dir = os.path.join(project_path, "Scene")
            if not os.path.exists(default_dir):
                default_dir = project_path

            title = "选择入口场景文件"
            file_filter = "场景文件 (*.scene);;所有文件 (*)"

            _, file_path = FileHandler.open_file(
                caption=title,
                file_types=file_filter,
                default_dir=default_dir,
                read_content=False
            )

            if file_path and os.path.exists(file_path):
                rel_path = os.path.relpath(file_path, project_path)
                rel_path = rel_path.replace('\\', '/')
                return {"path": rel_path, "success": True}

            return {"path": "", "success": False, "error": "未选择文件"}

        except Exception as e:
            logger.error(f"浏览场景文件失败: {e}")
            return {"error": str(e), "path": ""}