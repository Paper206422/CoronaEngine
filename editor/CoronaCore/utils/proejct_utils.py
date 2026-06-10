import configparser
import datetime
import logging
import os
import shutil
import threading
from functools import wraps
from typing import Any, Callable, Dict, Tuple

from utils.settings import version

logger = logging.getLogger(__name__)


def create_project_from_template(target_path, project_name, mode):
    """从 demo 目录下的 project 复制并初始化新项目"""
    try:
        # 1. 定位模板：project 位于插件包根目录
        # 路径：ProjectLauncher/utils/project_copy.py -> 向上退两级到 ProjectLauncher/
        launcher_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_src = os.path.join(launcher_dir, "demo", "project")

        if not os.path.exists(template_src):
            raise Exception(f"模板目录未找到: {template_src}")

        # 2. 物理复制
        if os.path.exists(target_path):
            raise Exception("目标文件夹已存在，请更换名称或路径")

        shutil.copytree(template_src, target_path)

        # 3. 修改新项目内的 project.ini
        project_ini = os.path.join(target_path, "project.ini")
        update_project_config(project_ini, project_name, mode, False)

        return project_ini
    except Exception as e:
        logger.error(f"ProjectCopy Error: {e}")
        raise e


def update_project_config(ini_path, name=None, mode='3d', update_only_time=False):
    """内部方法：读写 project.ini"""
    config = configparser.ConfigParser()
    if os.path.exists(ini_path):
        config.read(ini_path, encoding='utf-8')

    if 'Project' not in config:
        config['Project'] = {}

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not update_only_time:
        config['Project']['name'] = name
        config['Project']['mode'] = mode
        config['Project']['create_time'] = now_str
        config['Project']['core_version'] = version

    config['Project']['last_opened'] = now_str

    with open(ini_path, 'w', encoding='utf-8') as f:
        config.write(f)


def create_scene_from_template(target_path, scene_name):
    """从 demo 目录下的 scene 复制并初始化新场景"""
    try:
        # 1. 确保 scene_name 有正确扩展名
        if not scene_name.endswith('.scene'):
            scene_name += '.scene'

        # 2. 定位模板文件
        launcher_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_file = os.path.join(launcher_dir, "demo", "scene", "demo.scene")

        if not os.path.exists(template_file):
            raise FileNotFoundError(f"模板文件未找到: {template_file}")

        # 3. 确保目标目录存在
        os.makedirs(target_path, exist_ok=True)

        # 4. 处理文件名冲突
        base_name = os.path.splitext(scene_name)[0]  # 不含扩展名的文件名
        extension = '.scene'
        counter = 1
        target_file = os.path.join(target_path, f"{base_name}{extension}")

        # 如果文件已存在，自动添加数字后缀
        while os.path.exists(target_file):
            new_name = f"{base_name}_{counter}{extension}"
            target_file = os.path.join(target_path, new_name)
            counter += 1

        # 5. 复制文件
        shutil.copy2(template_file, target_file)  # 使用 copy2 保留元数据

        logger.info(f"场景文件创建成功: {target_file}")

        update_config_name(target_file, base_name)

        # 返回实际创建的文件名，方便调用方使用
        return os.path.basename(target_file)

    except Exception as e:
        logger.error(f"ProjectCopy Error: {e}")
        raise


def create_actor_from_template(target_path, scene_name):
    """从 demo 目录下的 actor 复制并初始化新场景"""
    try:
        # 1. 确保 scene_name 有正确扩展名
        if not scene_name.endswith('.actor'):
            scene_name += '.actor'

        # 2. 定位模板文件
        launcher_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_file = os.path.join(launcher_dir, "demo", "actor", "demo.actor")

        if not os.path.exists(template_file):
            raise FileNotFoundError(f"模板文件未找到: {template_file}")

        # 3. 确保目标目录存在
        os.makedirs(target_path, exist_ok=True)

        # 4. 处理文件名冲突
        base_name = os.path.splitext(scene_name)[0]  # 不含扩展名的文件名
        extension = '.actor'
        counter = 1
        target_file = os.path.join(target_path, f"{base_name}{extension}")

        # 如果文件已存在，自动添加数字后缀
        while os.path.exists(target_file):
            new_name = f"{base_name}_{counter}{extension}"
            target_file = os.path.join(target_path, new_name)
            counter += 1

        # 5. 复制文件
        shutil.copy2(template_file, target_file)  # 使用 copy2 保留元数据

        logger.info(f"单位文件创建成功: {target_file}")

        update_config_name(target_file, base_name)

        # 返回实际创建的文件名，方便调用方使用
        return os.path.basename(target_file)

    except Exception as e:
        logger.error(f"ProjectCopy Error: {e}")
        raise


def update_config_name(target_file, file_name):
    config = configparser.ConfigParser()
    config.read(target_file, encoding='utf-8')
    config['base']['name'] = file_name
    with open(target_file, 'w', encoding='utf-8') as f:
        config.write(f)


def get_project_scenes(ini_path: str) -> list[str]:
    """
    从 project.ini 读取场景列表（[Project] scenes 字段）。
    格式：逗号分隔的相对路径，例如 Scene/场景1.scene,Scene/场景2.scene
    返回有序的路径列表；若字段不存在则返回空列表。
    """
    config = configparser.ConfigParser()
    config.read(ini_path, encoding='utf-8')
    raw = config.get('Project', 'scenes', fallback='').strip()
    if not raw:
        return []
    return [s.strip() for s in raw.split(',') if s.strip()]


def set_project_scenes(ini_path: str, scenes: list[str]) -> None:
    """
    将场景路径列表写回 project.ini 的 [Project] scenes 字段。
    scenes: 有序的相对路径列表，例如 ['Scene/场景1.scene', 'Scene/场景2.scene']
    """
    config = configparser.ConfigParser()
    config.read(ini_path, encoding='utf-8')
    if 'Project' not in config:
        config['Project'] = {}
    config['Project']['scenes'] = ','.join(scenes)
    with open(ini_path, 'w', encoding='utf-8') as f:
        config.write(f)


def append_project_scene(ini_path: str, scene_route: str) -> None:
    """
    向 project.ini 的 scenes 列表末尾追加一个场景路径（如已存在则不重复添加）。
    """
    scenes = get_project_scenes(ini_path)
    if scene_route not in scenes:
        scenes.append(scene_route)
        set_project_scenes(ini_path, scenes)


_save_timers: Dict[int, Tuple[threading.Timer, Any]] = {}
_save_timers_lock = threading.RLock()


def flush_pending_auto_saves() -> int:
    """
    同步执行所有仍在防抖队列中的 save_data。
    用于预览快照前，确保磁盘状态已经追上内存状态。
    """
    with _save_timers_lock:
        pending = list(_save_timers.items())
        _save_timers.clear()

    flushed = 0
    for _, (timer, target) in pending:
        timer.cancel()
        try:
            if hasattr(target, 'save_data'):
                target.save_data()
                flushed += 1
        except Exception:
            logger.exception("flush pending auto-save failed")
    return flushed


def cancel_pending_auto_saves() -> int:
    """
    取消所有仍在防抖队列中的 save_data。
    用于预览恢复前，避免运行时状态在恢复后再次写回磁盘。
    """
    with _save_timers_lock:
        pending = list(_save_timers.values())
        _save_timers.clear()

    for timer, _ in pending:
        timer.cancel()
    return len(pending)


def auto_save(func: Callable) -> Callable:
    """
    装饰器：被装饰函数返回 True 时，延迟 0.5 秒后自动调用 save_data。
    短时间内的多次修改合并为一次磁盘写入。
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        if result is True and hasattr(self, 'save_data'):
            obj_key = id(self)
            with _save_timers_lock:
                old = _save_timers.pop(obj_key, None)
            if old is not None:
                old[0].cancel()

            def _do_save():
                try:
                    self.save_data()
                except Exception:
                    pass
                finally:
                    with _save_timers_lock:
                        current = _save_timers.get(obj_key)
                        if current and current[0] is timer:
                            _save_timers.pop(obj_key, None)

            timer = threading.Timer(0.5, _do_save)
            with _save_timers_lock:
                _save_timers[obj_key] = (timer, self)
            timer.start()
        return result
    return wrapper
