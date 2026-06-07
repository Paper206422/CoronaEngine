from CoronaCore.core.corona_editor import CoronaEditor
import logging

from CoronaPlugin.core.corona_plugin_base import PluginBase

logger = logging.getLogger(__name__)


@PluginBase.register_web("LogTool")
class LogTool(PluginBase):
    ready = False

    @staticmethod
    def log_from_js(message: str):
        """从 JavaScript 接收日志消息并写入 Python 日志"""
        logger.info(message)
        return {"status": "ok"}

    @classmethod
    def show_log(cls):
        if cls.ready:
            log_list = CoronaEditor.CoronaEngine.drain_logs()
            result = []
            for log in log_list:
                if log.message != "":
                    if "[Vue]" in log.message:
                        source = "Vue"
                    elif "[Python]" in log.message:
                        source = "Python"
                    else:
                        source = "Engine"
                    result.append({
                        "time": log.timestamp,
                        "source": source,
                        "level": log.level,
                        "message": log.message
                    })
            if len(result) > 0:
                CoronaEditor.js_call_func("log-batch", [result])

    @classmethod
    def set_log_ready(cls):
        cls.ready = True
        logger.info("LogTool set ready")

    @classmethod
    def set_log_close(cls):
        cls.ready = False
