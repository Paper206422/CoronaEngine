import json
import os
import datetime
import logging
from CoronaCore.core.corona_editor import CoronaEditor
from CoronaPlugin.core.corona_plugin_base import PluginBase
from CoronaCore.utils.file_handler import FileHandler, _FILE_TYPE_CONFIG
from utils.settings import settings_manager
from .utils.project_copy import ProjectCopy
logger = logging.getLogger(__name__)


@PluginBase.register_web("ProjectLauncher")
class ProjectLauncher(PluginBase):

    @staticmethod
    def get_default_project_path() -> str:
        # 从配置文件读取
        return settings_manager.get_default_path()

    @staticmethod
    def get_app_version() -> str:
        # 从配置文件读取
        return settings_manager.get_version()

    @staticmethod
    def browse_folder(default_path) -> str:
        """弹出文件夹选择对话框"""
        # 假设 FileHandler 有选择目录的方法，若没有可调用底层 QFileDialog
        path = FileHandler.open_directory(caption="选择项目保存位置",default_dir=default_path)
        return path if path else ""

    @staticmethod
    def get_recent_projects() -> list:
        """前端初始化时调用，获取历史记录"""
        return settings_manager.get_recent_projects()

    @staticmethod
    def create_project(project_data: dict) -> str:
        """创建项目目录及初始化文件"""
        name = project_data.get("name")
        base_dir = project_data.get("path")
        mode = project_data.get("mode", "3d")  # 获取前端传来的 mode
        target_full_path = os.path.join(base_dir, name)

        # 调用工具类处理物理复制和配置修改
        ProjectCopy.create_from_template(target_full_path, name, mode)
        settings_manager.set_default_path(base_dir)
        return target_full_path

    @staticmethod
    def open_project(project_path: str) -> bool:
        """执行打开项目的逻辑（加载资源、初始化环境等）"""
        return ProjectCopy.open_and_update(project_path)

    @staticmethod
    def set_project_mode(mode_data: dict) -> bool:
        """设置当前编辑器的工作模式 (2D/3D/Render)"""
        mode = mode_data.get("mode")
        settings = mode_data.get("settings")
        logger.info(f"Switching editor mode to: {mode} with settings: {settings}")
        # 这里可以根据模式调整渲染引擎参数
        return True

    @staticmethod
    def open_project_file() -> dict:
        """
        弹出文件选择框，指定选择 project.ini 文件。
        成功后返回项目信息并更新最近项目列表。
        """
        # 1. 弹出对话框选择 project.ini

        title, filter_str = _FILE_TYPE_CONFIG.get("project")
        _, file_path = FileHandler.open_file(
            caption=title,
            file_types=filter_str,
            default_dir=settings_manager.get_default_path(),
            read_content=False
        )

        if not file_path or not os.path.exists(file_path):
            return {}

        # 2. 获取项目目录并解析配置
        project_dir = os.path.dirname(file_path)
        try:
            import configparser
            proj_cfg = configparser.ConfigParser()
            proj_cfg.read(file_path, encoding='utf-8')
            project_name = proj_cfg.get('Project', 'name', fallback="default_project")

            # 3. 更新全局最近项目记录 (存储的是目录路径)
            settings_manager.add_recent_project(project_dir)

            # 4. 返回前端 handleSideAction 所需的结构
            return {
                "name": project_name,
                "path": project_dir
            }
        except Exception as e:
            logger.error(f"Failed to open project file: {e}")
            return {}
