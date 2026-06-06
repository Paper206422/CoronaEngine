import json
import os
import sys
import threading

from CoronaCore.core.corona_editor import CoronaEditor
import logging

from CoronaPlugin.core.corona_plugin_base import PluginBase
from utils.settings import core_path

logger = logging.getLogger(__name__)


@PluginBase.register_web("ScratchTool")
class ScratchTool(PluginBase):
    # 脚本存放目录：Backend/script/（与 runScript.py 的 import 路径一致）
    script_dir = core_path.repo_root / "Backend" / "script"
    os.makedirs(script_dir, exist_ok=True)

    # 当前执行的线程引用（用于停止控制）
    _exec_thread = None
    _exec_lock = threading.Lock()

    @classmethod
    def execute_python_code(cls, code: str, index: int,
                            scene_name: str = "", actor_name: str = "") -> str:
        """
        保存 Blockly 生成的 Python 代码到 Backend/script/，
        然后在独立线程中动态加载并执行 run() 函数

        此方法立即返回，不等待执行完成。执行状态通过 stop_script_execution() 控制。

        Args:
            code: Blockly 生成的 Python 代码
            index: 脚本索引
            scene_name: 目标场景名称（可选，用于绑定到场景中的真实 Actor）
            actor_name: 目标 Actor 名称（可选）
        """
        import time
        start_time = time.perf_counter()

        try:
            filename = f"blockly_code{'_' + str(index) if index else ''}.py"
            filepath = os.path.join(cls.script_dir, filename)

            # 1. 如果有 scene/actor 上下文，在代码前注入 set_target 调用
            final_code = code
            if scene_name and actor_name:
                set_target_prelude = (
                    f"from CoronaCore.utils import corona_engine_scratch as _CE\n"
                    f"_CE.set_target({repr(scene_name)}, {repr(actor_name)})\n"
                )
                final_code = set_target_prelude + code

            # 2. 写入代码文件（先清除旧的 blockly_code*.py，避免旧脚本中的错误影响）
            for old_file in os.listdir(cls.script_dir):
                if old_file.startswith("blockly_code") and old_file.endswith(".py"):
                    old_path = os.path.join(cls.script_dir, old_file)
                    try:
                        os.remove(old_path)
                    except Exception:
                        pass

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(final_code)

            # 3. 生成 runScript.py（聚合所有 blockly_code*.py）
            script_files = sorted(
                f.replace(".py", "")
                for f in os.listdir(cls.script_dir)
                if f.startswith("blockly_code") and f.endswith(".py")
            )

            run_script_path = core_path.repo_root / "Backend" / "runScript.py"
            run_script_content = ""
            for script in script_files:
                run_script_content += f"from Backend.script import {script}\n"
            run_script_content += "\n\ndef run():\n"
            for script in script_files:
                run_script_content += f"    {script}.run()\n"

            with open(run_script_path, "w", encoding="utf-8") as f:
                f.write(run_script_content)

            # 4. 修正生成代码中的旧路径引用
            try:
                for sf in script_files:
                    sf_path = os.path.join(cls.script_dir, f"{sf}.py")
                    if os.path.exists(sf_path):
                        with open(sf_path, 'r', encoding='utf-8') as sf_f:
                            content = sf_f.read()
                        new_content = content.replace('from utils.', 'from Backend.utils.').replace(
                            'from corona_engine_fallback import',
                            'from Backend.engine_core.corona_engine_fallback import')
                        if new_content != content:
                            with open(sf_path, 'w', encoding='utf-8') as sf_f:
                                sf_f.write(new_content)
            except Exception:
                pass

            elapsed_save = (time.perf_counter() - start_time) * 1000
            target_info = f", target={scene_name}/{actor_name}" if scene_name and actor_name else ""
            logger.info(f"[ScratchTool] 脚本保存完成: {elapsed_save:.1f}ms -> {filepath}{target_info}")

            # 5. 先在主线程中清除模块缓存 + 重置停止标志
            import importlib
            modules_to_clear = [
                name for name in sys.modules.keys()
                if name.startswith('Backend.script.blockly_code') or name == 'runScript'
            ]
            for mod_name in modules_to_clear:
                try:
                    del sys.modules[mod_name]
                except KeyError:
                    pass

            backend_root = str(core_path.repo_root)
            if backend_root not in sys.path:
                sys.path.insert(0, backend_root)

            # 重置 corona_engine_scratch 的停止标志
            from CoronaCore.utils import corona_engine_scratch
            corona_engine_scratch.reset_stop()

            # 6. 在后台线程中执行脚本（主线程立即返回，不阻塞 UI）
            def _run_in_thread():
                exec_start = time.perf_counter()
                try:
                    from Backend import runScript
                    importlib.reload(runScript)
                    runScript.run()
                    elapsed_exec = (time.perf_counter() - exec_start) * 1000
                    logger.info(f"[ScratchTool] 脚本执行完成: {elapsed_exec:.1f}ms")
                except Exception as exec_err:
                    elapsed_exec = (time.perf_counter() - exec_start) * 1000
                    logger.exception(
                        f"[ScratchTool] 脚本执行失败 ({elapsed_exec:.1f}ms): {exec_err}")
                finally:
                    # 清理线程引用
                    with cls._exec_lock:
                        if cls._exec_thread is threading.current_thread():
                            cls._exec_thread = None

            # 取消上一个未完成的线程
            with cls._exec_lock:
                if cls._exec_thread and cls._exec_thread.is_alive():
                    from CoronaCore.utils import corona_engine_scratch
                    corona_engine_scratch.request_stop()
                    cls._exec_thread.join(timeout=2.0)
                cls._exec_thread = threading.Thread(
                    target=_run_in_thread, daemon=True, name="blockly-exec"
                )
                cls._exec_thread.start()

            return json.dumps({"status": "started", "filepath": filepath})

        except Exception as e:
            logger.exception("[ScratchTool] 处理Python代码时出错: %s", str(e))
            return json.dumps({"status": "error", "message": str(e)})

    @classmethod
    def stop_script_execution(cls) -> str:
        """
        停止当前正在执行的脚本

        设置 corona_engine_scratch 的停止标志并等待线程结束
        """
        from CoronaCore.utils import corona_engine_scratch

        corona_engine_scratch.request_stop()

        with cls._exec_lock:
            if cls._exec_thread and cls._exec_thread.is_alive():
                cls._exec_thread.join(timeout=2.0)
                cls._exec_thread = None

        logger.info("[ScratchTool] 脚本已停止")
        return json.dumps({"status": "stopped"})

    @classmethod
    def get_script_status(cls) -> str:
        """查询当前脚本执行状态：running / idle"""
        with cls._exec_lock:
            if cls._exec_thread and cls._exec_thread.is_alive():
                return json.dumps({"status": "running"})
            return json.dumps({"status": "idle"})
