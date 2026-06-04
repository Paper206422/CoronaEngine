import os
import sys
import importlib.util
from pathlib import Path
import logging

from utils.settings import core_path

logger = logging.getLogger(__name__)


def reimport():
    """
    遍历plugins目录下的文件夹，并导入文件夹中的main.py模块
    """
    plugins_path = core_path.plugins_dir

    if not plugins_path.exists():
        logger.error(f"插件目录不存在: {plugins_path}")
        return

    # 遍历plugins目录下的所有项目
    for item in plugins_path.iterdir():
        # 只处理目录
        if not item.is_dir():
            continue

        # 跳过以点开头的隐藏文件夹
        if item.name.startswith('.'):
            continue

        # 检查是否存在main.py文件
        plugin_file = item / "main.py"
        if not plugin_file.exists():
            logger.debug(f"插件目录 {item.name} 缺少main.py文件，跳过")
            continue

        # 尝试导入main.py模块
        try:
            # 构建模块名
            module_name = f"plugins.{item.name}.main"

            # 如果模块已经导入，先重新加载
            if module_name in sys.modules:
                spec = importlib.util.spec_from_file_location(module_name, plugin_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                logger.info(f"重新加载插件模块: {item.name}")
            else:
                # 新导入模块
                spec = importlib.util.spec_from_file_location(module_name, plugin_file)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                logger.info(f"导入插件模块: {item.name}")

            # 这里可以添加对模块的进一步处理，比如注册插件等

        except Exception as e:
            logger.error(f"导入插件 {item.name} 失败: {e}", exc_info=True)