import os
import time
import shutil
from pathlib import Path

from CoronaCore.core.corona_editor import CoronaEditor
from CoronaCore.core.managers import scene_manager
from CoronaCore.utils.proejct_utils import create_scene_from_template, create_actor_from_template
from CoronaPlugin.core.corona_plugin_base import PluginBase

import logging

from utils.settings import settings_manager

logger = logging.getLogger(__name__)


@PluginBase.register_web("FileManager")
class FileManager(PluginBase):
    """文件管理器插件"""

    @staticmethod
    def get_project_info() -> dict:
        """获取当前打开项目的根目录信息"""
        path = settings_manager.active_project_path
        return {
            "path": path,
            "name": os.path.basename(path) if path else "未打开项目",
            "exists": os.path.exists(path) if path else False
        }

    @staticmethod
    def get_file_tree(relative_path: str = "") -> dict:
        """获取项目目录下的文件树结构"""
        root = settings_manager.active_project_path
        if not root:
            return {"name": "", "path": "", "children": [], "isDirectory": True, "level": 0}

        # 安全拼接路径
        target_path = os.path.normpath(os.path.join(root, relative_path))
        if not target_path.startswith(os.path.normpath(root)):
            return {"name": "", "path": "", "children": [], "isDirectory": True, "level": 0}

        def build_tree(dir_path, rel_path, level=0):
            """递归构建树结构，附带层级信息"""
            name = os.path.basename(dir_path) or os.path.basename(root)

            # 第一层目录（level=0）默认展开
            expanded = (level <= 1)

            node = {
                "name": name,
                "path": rel_path.replace("\\", "/"),
                "isDirectory": True,
                "children": [],
                "expanded": expanded,
                "level": level  # 添加层级信息
            }

            try:
                for entry in os.scandir(dir_path):
                    entry_rel_path = os.path.relpath(entry.path, root).replace("\\", "/")

                    if entry.is_dir():
                        # 递归处理子目录，层级+1
                        child_node = build_tree(entry.path, entry_rel_path, level + 1)
                        node["children"].append(child_node)
                    else:
                        # 处理文件
                        stats = entry.stat()
                        node["children"].append({
                            "name": entry.name,
                            "path": entry_rel_path,
                            "isDirectory": False,
                            "size": stats.st_size,
                            "mtime": time.strftime('%Y-%m-%d %H:%M', time.localtime(stats.st_mtime)),
                            "level": level + 1  # 文件层级比父目录深一级
                        })

                # 排序：文件夹优先，然后按名称
                node["children"].sort(key=lambda x: (not x["isDirectory"], x["name"].lower()))

            except Exception as e:
                logger.error(f"Read dir error: {e}")

            return node

        # 从根目录开始构建，level=0
        return build_tree(target_path, relative_path, 0)

    @staticmethod
    def create_folder(path: str, folder_name: str) -> bool:
        """在指定路径下创建文件夹"""
        root = settings_manager.active_project_path
        if not root:
            return False

        target_path = os.path.normpath(os.path.join(root, path, folder_name))
        if not target_path.startswith(os.path.normpath(root)):
            return False

        try:
            os.makedirs(target_path, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"Create folder error: {e}")
            return False

    @staticmethod
    def create_file(path: str, file_name: str, file_type: str) -> bool:
        """在指定路径下创建文件"""
        root = settings_manager.active_project_path
        if not root:
            return False

        target_path = os.path.normpath(os.path.join(root, path))
        if not target_path.startswith(os.path.normpath(root)):
            return False

        try:
            if file_type == "scene":
                create_scene_from_template(target_path, file_name)
            elif file_type == "actor":
                create_actor_from_template(target_path, file_name)
            else:
                logger.error(f"No file type: {file_type}")
                return False
            return True
        except Exception as e:
            logger.error(f"Create file error: {e}")
            return False

    @staticmethod
    def delete_item(path: str) -> bool:
        """删除文件或文件夹"""
        root = settings_manager.active_project_path
        if not root:
            return False

        target_path = os.path.normpath(os.path.join(root, path))
        if not target_path.startswith(os.path.normpath(root)) or target_path == root:
            return False  # 防止删除项目根目录

        try:
            if os.path.isdir(target_path):
                shutil.rmtree(target_path)
            else:
                os.remove(target_path)
            return True
        except Exception as e:
            logger.error(f"Delete item error: {e}")
            return False

    @staticmethod
    def rename_item(old_path: str, new_name: str) -> bool:
        """重命名文件或文件夹"""
        root = settings_manager.active_project_path
        if not root:
            return False

        old_full_path = os.path.normpath(os.path.join(root, old_path))
        if not old_full_path.startswith(os.path.normpath(root)):
            return False

        parent_dir = os.path.dirname(old_full_path)
        new_full_path = os.path.normpath(os.path.join(parent_dir, new_name))

        if not new_full_path.startswith(os.path.normpath(root)):
            return False

        try:
            os.rename(old_full_path, new_full_path)

            if old_path.endswith(".scene"):
                scene = scene_manager.get_or_create(old_path)
                new_path = os.path.normpath(os.path.join(os.path.dirname(old_path), new_name)).replace('\\', '/')
                scene.set_route(new_path)
                scene_manager.remove(old_path)
                scene_manager.register(new_path, scene)

                CoronaEditor.js_call_func("scene-rename", [old_path, new_path, scene.name])
                CoronaEditor.js_call_func("actor-change", ['scene', new_path, "", old_path])
            elif old_path.endswith(".actor"):
                actor = scene_manager.find_actor_by_route(old_path)
                if actor is None:
                    logger.warning("Rename actor: '%s' not found in any scene", old_path)
                    return False
                new_path = os.path.normpath(os.path.join(os.path.dirname(old_path), new_name)).replace('\\', '/')
                actor.set_route(new_path)

                CoronaEditor.js_call_func("actor-change", ['actor', '',  new_path, old_path])
            return True
        except Exception as e:
            logger.error(f"Rename error: {e}")
            return False


    @staticmethod
    def open_file(path: str, file_type: str):
        try:
            if file_type == "scene":
                scene = scene_manager.get_or_create(path)
                scene.ensure_default_camera()
                CoronaEditor.js_call_func("scene-add", [scene.name, scene.route])
                CoronaEditor.js_call_func("actor-change", ['scene', scene.route, ""])
            elif file_type == "actor":
                actor = scene_manager.find_actor_by_route(path)
                if actor is None:
                    from CoronaCore.core.entities import Actor
                    actor = Actor(route=path, actor_type="actor")
                CoronaEditor.js_call_func("actor-change", ['actor', "", actor.route])
            else:
                logger.error(f"No file type: {file_type}")
                return False
            return True
        except Exception as e:
            logger.error(f"Open file error: {e}")
            return False