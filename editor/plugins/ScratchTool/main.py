import ctypes
import json
import os
import sys
import threading

from CoronaCore.core.corona_editor import CoronaEditor
import logging

from CoronaPlugin.core.corona_plugin_base import PluginBase
from utils.settings import core_path

logger = logging.getLogger(__name__)


def _force_kill_thread(thread: threading.Thread, timeout: float = 3.0):
    """强制终止线程：先 request_stop，等待 timeout 秒，未退出则注入 SystemExit"""
    from CoronaCore.utils import corona_engine_scratch

    corona_engine_scratch.request_stop()

    thread.join(timeout=timeout)
    if not thread.is_alive():
        return True  # 正常退出

    # 仍未退出 → 用 ctypes 注入异常强制终止
    logger.warning(f"[ScratchTool] 线程 {timeout}s 内未退出，强制注入 SystemExit")
    tid = thread.ident
    if tid is not None:
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(tid), ctypes.py_object(SystemExit)
        )
        if res == 0:
            logger.error(f"[ScratchTool] 强制终止失败：无效线程 ID {tid}")
        elif res > 1:
            # 多线程状态被修改，需要恢复
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
            logger.error(f"[ScratchTool] 强制终止异常：修改了多个线程状态，已回滚")

    thread.join(timeout=1.0)
    return not thread.is_alive()


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

            # 5. 清除 Backend 命名空间包的所有缓存模块 + .pyc 字节码
            import importlib
            modules_to_clear = [
                name for name in sys.modules.keys()
                if name == 'Backend' or name.startswith('Backend.')
            ]
            for mod_name in modules_to_clear:
                try:
                    del sys.modules[mod_name]
                except KeyError:
                    pass

            # 同时删除 __pycache__ 中的 .pyc 防止字节码缓存
            import glob as _glob
            pycache_dirs = [
                os.path.join(cls.script_dir, '__pycache__'),
                core_path.repo_root / 'Backend' / '__pycache__',
            ]
            for pc_dir in pycache_dirs:
                if os.path.isdir(pc_dir):
                    for pyc_file in _glob.glob(os.path.join(pc_dir, 'blockly_code*')):
                        try:
                            os.remove(pyc_file)
                        except Exception:
                            pass
                    for pyc_file in _glob.glob(os.path.join(pc_dir, 'runScript*')):
                        try:
                            os.remove(pyc_file)
                        except Exception:
                            pass

            backend_root = str(core_path.repo_root)
            if backend_root not in sys.path:
                sys.path.insert(0, backend_root)

            # 重置 corona_engine_scratch 的全部运行时状态
            try:
                from CoronaCore.utils import corona_engine_scratch
                corona_engine_scratch.reset_state()
                # 开启 fallback 静默模式（抑制 Geometry.set_position 等打印）
                from CoronaCore.utils import corona_engine_fallback
                corona_engine_fallback.set_quiet(True)
                logger.debug("[ScratchTool] 运行时状态已重置")
            except Exception as reset_err:
                logger.warning(f"[ScratchTool] 状态重置失败（使用旧API降级）: {reset_err}")
                try:
                    corona_engine_scratch.reset_stop()
                except Exception:
                    pass

            # 6. 在后台线程中执行脚本（主线程立即返回，不阻塞 UI）
            def _run_in_thread():
                exec_start = time.perf_counter()
                try:
                    from Backend import runScript
                    importlib.reload(runScript)
                    runScript.run()
                    elapsed_exec = (time.perf_counter() - exec_start) * 1000
                    logger.info(f"[ScratchTool] 脚本执行完成: {elapsed_exec:.1f}ms")
                except SystemExit:
                    # 正常的停止流程（check_stop 触发），不是错误
                    elapsed_exec = (time.perf_counter() - exec_start) * 1000
                    logger.info(f"[ScratchTool] 脚本被停止: {elapsed_exec:.1f}ms")
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
            old_thread = None
            with cls._exec_lock:
                if cls._exec_thread and cls._exec_thread.is_alive():
                    old_thread = cls._exec_thread

            if old_thread is not None:
                _force_kill_thread(old_thread, timeout=0.5)

            with cls._exec_lock:
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

        1. 设置停止标志 → 循环内的 check_stop() 抛出 SystemExit
        2. 等待 0.5s → 如未退出，用 ctypes 注入 SystemExit
        """
        thread_to_stop = None
        with cls._exec_lock:
            if cls._exec_thread and cls._exec_thread.is_alive():
                thread_to_stop = cls._exec_thread

        if thread_to_stop is not None:
            killed = _force_kill_thread(thread_to_stop, timeout=0.5)
            if killed:
                logger.info("[ScratchTool] 脚本已停止")
            else:
                logger.error("[ScratchTool] 脚本停止失败（线程未响应）")

            with cls._exec_lock:
                if cls._exec_thread is thread_to_stop:
                    cls._exec_thread = None

        return json.dumps({"status": "stopped"})

    @classmethod
    def get_script_status(cls) -> str:
        """查询当前脚本执行状态：running / idle"""
        with cls._exec_lock:
            if cls._exec_thread and cls._exec_thread.is_alive():
                return json.dumps({"status": "running"})
            return json.dumps({"status": "idle"})

    @classmethod
    def key_event(cls, key: str, modifiers: str = "", display_key: str = "") -> str:
        """CEF 桥接：分发键盘按下事件
        Args:
            key: 物理键码 (e.code, 如 'KeyA', 'Digit0', 'BracketRight')
            modifiers: 修饰键 (如 'Ctrl,Shift')
            display_key: 显示字符 (e.key, 如 'a', '0', ']')
        """
        from CoronaCore.utils import corona_engine_scratch

        mods = [m.strip() for m in modifiers.split(",") if m.strip()] if modifiers else []
        corona_engine_scratch.handle_key_event(key, mods, display_key or key)
        return json.dumps({"status": "ok"})

    @classmethod
    def key_release(cls, key: str, display_key: str = "") -> str:
        """CEF 桥接：分发键盘释放事件"""
        from CoronaCore.utils import corona_engine_scratch

        corona_engine_scratch.handle_key_release(key, display_key or key)
        return json.dumps({"status": "ok"})

    @classmethod
    def mouse_event(cls, event_type: str, button: str = "",
                    x: float = 0.0, y: float = 0.0) -> str:
        """CEF 桥接：分发鼠标事件到积木脚本的 handle_mouse()"""
        from CoronaCore.utils import corona_engine_scratch

        corona_engine_scratch.handle_mouse_event(event_type, button, x, y)
        return json.dumps({"status": "ok"})
