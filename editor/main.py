import logging
import os
import sys
import threading
import time
from pathlib import Path

from CoronaCore.core.corona_editor import CoronaEditor

# 1. 设置项目根目录路径
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

# 2. 加载全局配置
from config.app_config import get_app_config

app_config = get_app_config()
# 确保 repo_root 在 sys.path 中
sys.path.append(str(app_config.paths.repo_root))

# 4. 初始化日志（尽早进行）
try:
    from utils.logging import configure_logging

    configure_logging()
except Exception:
    # 日志桥失败时不能静默——直接打到原始 stderr，便于排查
    import traceback as _tb

    _tb.print_exc()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s [%(filename)s:%(lineno)d] %(message)s",
        force=True,
    )

try:
    from CoronaPlugin.utils.load_utils import reimport

    reimport()
except:
    pass
editor = CoronaEditor
editor.module_list["CoronaEditor"] = CoronaEditor


def run():
    try:
        from plugins.AITool.Quasar.ai_tools.warmup import (
            warmup_all,
        )
        from plugins.AITool.utils.load_local_ai_setting import load_ai_setting

        load_ai_setting()
        warmup_all()
    except:
        pass

    # editor.open_browser()
    # editor.module_list["MainView"].open()

    # 定义执行打开操作的函数
    def delayed_startup():
        logging.info("Timer started: Waiting 30s for CEF and Vulkan to stabilize...")
        # 打开StartScreen作为起始界面
        editor.open_browser(route_path="/StartScreen", docking_pos="main", dock_width=1920, dock_height=1080, dock_fixed=True)
        logging.info("StartScreen opened after 30s delay.")

    # 使用 threading.Timer 在 30 秒后触发
    # 参数 30.0 代表延迟秒数
    startup_timer = threading.Timer(0.0, delayed_startup)

    # 设置为守护线程，防止阻塞程序退出
    startup_timer.daemon = True

    # 启动定时器
    startup_timer.start()