import logging
import os
import sys
import threading
import time
from pathlib import Path

from CoronaCore.core.corona_editor import CoronaEditor

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from config.app_config import get_app_config

app_config = get_app_config()
sys.path.append(str(app_config.paths.repo_root))

try:
    from utils.logging import configure_logging
    configure_logging()
except Exception:
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
        from plugins.AITool.Quasar.ai_tools.warmup import warmup_all
        from plugins.AITool.utils.load_local_ai_setting import load_ai_setting
        load_ai_setting()
        warmup_all()
    except:
        pass

    # 启动延迟：确保 CEF 就绪后创建起始 Tab（与旧行为一致，从 StartScreen 开始）
    def delayed_startup():
        logging.info("Creating initial CEF tab at StartScreen...")
        tab_id = editor.CoronaEngine.create_browser_tab(
            editor.url, "/StartScreen", "main", 1920, 1080, True
        )
        CoronaEditor._main_tab_id = tab_id
        logging.info("Main CEF tab created: ID=%s", tab_id)

    startup_timer = threading.Timer(0.0, delayed_startup)
    startup_timer.daemon = True
    startup_timer.start()
