import ctypes
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Optional

from CoronaCore.core.corona_editor import CoronaEditor
from CoronaCore.utils.proejct_utils import (
    cancel_pending_auto_saves,
    flush_pending_auto_saves,
    get_project_scenes,
)
from CoronaPlugin.core.corona_plugin_base import PluginBase
from utils.settings import core_path, settings_manager

logger = logging.getLogger(__name__)


def _force_kill_thread(
    thread: threading.Thread,
    timeout: float = 3.0,
    context_id: str | None = None,
):
    """请求停止脚本线程；超时后注入 SystemExit 兜底。"""
    from CoronaCore.utils import corona_engine_scratch

    corona_engine_scratch.request_stop(context_id)
    thread.join(timeout=timeout)
    if not thread.is_alive():
        return True

    logger.warning("[ScratchTool] thread did not stop in %.1fs; injecting SystemExit", timeout)
    tid = thread.ident
    if tid is not None:
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_ulong(tid), ctypes.py_object(SystemExit)
        )
        if res == 0:
            logger.error("[ScratchTool] invalid thread id: %s", tid)
        elif res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(tid), None)
            logger.error("[ScratchTool] SystemExit injection touched multiple threads; rolled back")

    thread.join(timeout=1.0)
    return not thread.is_alive()


@PluginBase.register_web("ScratchTool")
class ScratchTool(PluginBase):
    script_dir = core_path.repo_root / "Backend" / "script"
    os.makedirs(script_dir, exist_ok=True)

    _exec_thread: Optional[threading.Thread] = None
    _exec_context_id: Optional[str] = None
    _exec_lock = threading.Lock()

    _preview_lock = threading.RLock()
    _preview_threads: list[dict[str, Any]] = []
    _preview_status = "idle"
    _preview_errors: list[str] = []
    _preview_warnings: list[str] = []
    _preview_state_snapshot: Optional[dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Project Blockly persistence
    # ------------------------------------------------------------------
    @classmethod
    def _active_project_path(cls) -> Path:
        project_path = settings_manager.active_project_path
        if not project_path and CoronaEditor.CoronaEngine is not None:
            project_path = getattr(CoronaEditor.CoronaEngine, "active_project_path", None)
        if not project_path:
            raise RuntimeError("没有打开的项目，无法保存或运行积木")
        return Path(project_path)

    @classmethod
    def _blockly_dir(cls) -> Path:
        directory = cls._active_project_path() / "Scripts" / "blockly"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    @classmethod
    def _manifest_path(cls) -> Path:
        return cls._blockly_dir() / "manifest.json"

    @classmethod
    def _load_manifest(cls) -> dict:
        path = cls._manifest_path()
        if not path.exists():
            return {"targets": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"targets": []}
            targets = data.get("targets")
            if not isinstance(targets, list):
                data["targets"] = []
            return data
        except Exception:
            logger.exception("[ScratchTool] failed to load manifest: %s", path)
            return {"targets": []}

    @classmethod
    def _write_manifest(cls, manifest: dict) -> None:
        path = cls._manifest_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _target_id(target_type: str, scene_name: str = "", actor_name: str = "") -> str:
        if target_type == "project":
            return "project:global"
        return f"actor:{scene_name}:{actor_name}"

    @staticmethod
    def _target_digest(target_id: str) -> str:
        return hashlib.sha1(target_id.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _normalize_payload(payload: Any) -> dict:
        if payload is None:
            return {}
        if isinstance(payload, str):
            return json.loads(payload) if payload.strip() else {}
        if isinstance(payload, dict):
            return payload
        raise TypeError("payload must be an object")

    @staticmethod
    def _with_context_prelude(code: str, target_type: str, scene_name: str, actor_name: str) -> str:
        prelude = "from CoronaCore.utils import corona_engine_scratch as _CE\n"
        if target_type == "project":
            prelude += "_CE.set_project_global()\n"
        elif scene_name and actor_name:
            prelude += f"_CE.set_target({scene_name!r}, {actor_name!r})\n"
        return prelude + (code or "")

    @classmethod
    def save_blockly_target(cls, payload: dict | str) -> dict:
        """
        Save generated Python and Blockly workspace JSON into the active project.

        Manifest schema:
        { targets: [{ id, target_type, scene_name, actor_name, code_path,
                      workspace_path, updated_at, enabled }] }
        """
        try:
            data = cls._normalize_payload(payload)
            target_type = data.get("target_type") or "actor"
            if target_type not in ("project", "actor"):
                return {"status": "error", "message": f"unsupported target_type: {target_type}"}

            scene_name = data.get("scene_name") or ""
            actor_name = data.get("actor_name") or ""
            if target_type == "actor" and (not scene_name or not actor_name):
                return {"status": "error", "message": "actor target requires scene_name and actor_name"}
            if target_type == "project":
                scene_name = ""
                actor_name = ""

            target_id = cls._target_id(target_type, scene_name, actor_name)
            digest = cls._target_digest(target_id)
            prefix = "project_global" if target_type == "project" else "actor"
            blockly_dir = cls._blockly_dir()
            code_path = blockly_dir / f"{prefix}_{digest}.py"
            workspace_path = blockly_dir / f"{prefix}_{digest}.blockly.json"
            project_path = cls._active_project_path()

            code = cls._with_context_prelude(
                str(data.get("code") or ""),
                target_type,
                scene_name,
                actor_name,
            )
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(code)
            with open(workspace_path, "w", encoding="utf-8") as f:
                json.dump(data.get("workspace") or {}, f, ensure_ascii=False, indent=2)

            def _rel(path: Path) -> str:
                return path.relative_to(project_path).as_posix()

            target = {
                "id": target_id,
                "target_type": target_type,
                "scene_name": scene_name,
                "actor_name": actor_name,
                "code_path": _rel(code_path),
                "workspace_path": _rel(workspace_path),
                "updated_at": time.time(),
                "enabled": bool(data.get("enabled", True)),
            }

            manifest = cls._load_manifest()
            targets = [t for t in manifest.get("targets", []) if t.get("id") != target_id]
            targets.append(target)
            targets.sort(key=lambda t: (0 if t.get("target_type") == "project" else 1,
                                        t.get("scene_name", ""),
                                        t.get("actor_name", "")))
            manifest["targets"] = targets
            cls._write_manifest(manifest)

            return {"status": "saved", "target": target}
        except Exception as exc:
            logger.exception("[ScratchTool] save_blockly_target failed")
            return {"status": "error", "message": str(exc)}

    @classmethod
    def load_blockly_target(cls, payload: dict | str) -> dict:
        """Load a saved Blockly workspace for one project/actor target."""
        try:
            data = cls._normalize_payload(payload)
            target_type = data.get("target_type") or "actor"
            if target_type not in ("project", "actor"):
                return {"status": "error", "message": f"unsupported target_type: {target_type}"}

            scene_name = data.get("scene_name") or ""
            actor_name = data.get("actor_name") or ""
            if target_type == "project":
                scene_name = ""
                actor_name = ""
            elif not scene_name or not actor_name:
                return {"status": "error", "message": "actor target requires scene_name and actor_name"}

            target_id = cls._target_id(target_type, scene_name, actor_name)
            manifest = cls._load_manifest()
            target = next(
                (item for item in manifest.get("targets", []) if item.get("id") == target_id),
                None,
            )
            if not target:
                return {
                    "status": "missing",
                    "target": {
                        "id": target_id,
                        "target_type": target_type,
                        "scene_name": scene_name,
                        "actor_name": actor_name,
                    },
                    "workspace": {},
                }

            workspace_rel = target.get("workspace_path") or ""
            workspace_path = (cls._active_project_path() / workspace_rel).resolve()
            project_path = cls._active_project_path().resolve()
            try:
                workspace_path.relative_to(project_path)
            except ValueError:
                return {"status": "error", "message": "workspace_path escapes active project"}

            if not workspace_path.exists():
                return {"status": "missing", "target": target, "workspace": {}}
            with open(workspace_path, "r", encoding="utf-8") as f:
                workspace = json.load(f)
            if not isinstance(workspace, dict):
                workspace = {}
            return {"status": "loaded", "target": target, "workspace": workspace}
        except Exception as exc:
            logger.exception("[ScratchTool] load_blockly_target failed")
            return {"status": "error", "message": str(exc)}

    # ------------------------------------------------------------------
    # Legacy single-code execution
    # ------------------------------------------------------------------
    @classmethod
    def execute_python_code(
        cls,
        code: str,
        index: int,
        scene_name: str = "",
        actor_name: str = "",
        target_type: str = "actor",
    ) -> dict:
        try:
            filename = f"blockly_code{'_' + str(index) if index else ''}.py"
            filepath = cls.script_dir / filename

            for old_file in os.listdir(cls.script_dir):
                if old_file.startswith("blockly_code") and old_file.endswith(".py"):
                    try:
                        os.remove(cls.script_dir / old_file)
                    except Exception:
                        pass

            final_code = cls._with_context_prelude(code, target_type, scene_name, actor_name)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(final_code)

            run_script_path = core_path.repo_root / "Backend" / "runScript.py"
            with open(run_script_path, "w", encoding="utf-8") as f:
                f.write("from Backend.script import blockly_code\n\n\ndef run():\n    blockly_code.run()\n")

            backend_root = str(core_path.repo_root)
            if backend_root not in sys.path:
                sys.path.insert(0, backend_root)
            cls._clear_backend_cache()

            old_thread = None
            old_context = None
            with cls._exec_lock:
                if cls._exec_thread and cls._exec_thread.is_alive():
                    old_thread = cls._exec_thread
                    old_context = cls._exec_context_id
            if old_thread is not None:
                _force_kill_thread(old_thread, timeout=0.5, context_id=old_context)

            context_id = cls._target_id(target_type, scene_name, actor_name)

            def _run_in_thread():
                cls._run_code_file(
                    filepath,
                    {
                        "id": context_id,
                        "target_type": target_type,
                        "scene_name": scene_name,
                        "actor_name": actor_name,
                    },
                    single_exec=True,
                )
                with cls._exec_lock:
                    if cls._exec_thread is threading.current_thread():
                        cls._exec_thread = None
                        cls._exec_context_id = None

            with cls._exec_lock:
                cls._exec_context_id = context_id
                cls._exec_thread = threading.Thread(
                    target=_run_in_thread, daemon=True, name="blockly-exec"
                )
                cls._exec_thread.start()

            return {"status": "started", "filepath": str(filepath)}
        except Exception as exc:
            logger.exception("[ScratchTool] execute_python_code failed")
            return {"status": "error", "message": str(exc)}

    @classmethod
    def stop_script_execution(cls) -> dict:
        thread_to_stop = None
        context_id = None
        with cls._exec_lock:
            if cls._exec_thread and cls._exec_thread.is_alive():
                thread_to_stop = cls._exec_thread
                context_id = cls._exec_context_id

        if thread_to_stop is not None:
            _force_kill_thread(thread_to_stop, timeout=0.5, context_id=context_id)

        with cls._exec_lock:
            cls._exec_thread = None
            cls._exec_context_id = None
        return {"status": "stopped"}

    @classmethod
    def get_script_status(cls) -> dict:
        with cls._exec_lock:
            if cls._exec_thread and cls._exec_thread.is_alive():
                return {"status": "running"}
        return {"status": "idle"}

    # ------------------------------------------------------------------
    # Project preview
    # ------------------------------------------------------------------
    @classmethod
    def start_game_preview(cls, payload: dict | str | None = None) -> dict:
        data = cls._normalize_payload(payload)
        scope = data.get("scope", "project")
        if scope != "project":
            return {"status": "error", "message": f"unsupported preview scope: {scope}"}

        cls.stop_game_preview()

        try:
            flush_pending_auto_saves()
            targets, warnings = cls._prepare_preview_targets()
            flush_pending_auto_saves()
        except Exception as exc:
            logger.exception("[ScratchTool] start_game_preview prepare failed")
            return {"status": "error", "message": str(exc)}

        if not targets:
            with cls._preview_lock:
                cls._preview_errors = []
                cls._preview_warnings = list(warnings)
                cls._preview_threads = []
                cls._preview_status = "idle"
            return {
                "status": "idle",
                "started_count": 0,
                "errors": [],
                "warnings": warnings,
            }

        try:
            state_snapshot = cls._create_preview_state_snapshot()
        except Exception as exc:
            logger.exception("[ScratchTool] preview state snapshot failed")
            return {"status": "error", "message": f"创建预览状态快照失败: {exc}"}

        with cls._preview_lock:
            cls._preview_errors = []
            cls._preview_warnings = list(warnings)
            cls._preview_threads = []
            cls._preview_status = "running" if targets else "idle"
            cls._preview_state_snapshot = state_snapshot

        for target in targets:
            code_path = cls._active_project_path() / target["code_path"]
            thread = threading.Thread(
                target=cls._run_preview_target,
                args=(code_path, target),
                daemon=True,
                name=f"blockly-preview-{cls._target_digest(target['id'])}",
            )
            with cls._preview_lock:
                cls._preview_threads.append({"thread": thread, "target": target})
            thread.start()

        return {
            "status": "running" if targets else "idle",
            "started_count": len(targets),
            "errors": [],
            "warnings": warnings,
        }

    @classmethod
    def stop_game_preview(cls) -> dict:
        with cls._preview_lock:
            infos = list(cls._preview_threads)
            if infos:
                cls._preview_status = "stopping"

        from CoronaCore.utils import corona_engine_scratch

        corona_engine_scratch.request_stop_all()
        stopped = 0
        for info in infos:
            thread = info.get("thread")
            target = info.get("target") or {}
            if thread and thread.is_alive():
                if _force_kill_thread(thread, timeout=0.5, context_id=target.get("id")):
                    stopped += 1
            else:
                stopped += 1

        with cls._preview_lock:
            cls._preview_threads = [
                info for info in cls._preview_threads
                if info.get("thread") and info["thread"].is_alive()
            ]
            cls._preview_status = "idle" if not cls._preview_threads else "stopping"
            live_count = len(cls._preview_threads)

        if live_count:
            return {
                "status": cls._preview_status,
                "stopped_count": stopped,
                "restored": False,
                "restore_error": "preview threads are still running",
            }

        restored, restore_error = cls._restore_preview_state_snapshot()
        with cls._preview_lock:
            if restore_error:
                cls._preview_status = "error"
            else:
                cls._preview_status = "idle"

        return {
            "status": cls._preview_status,
            "stopped_count": stopped,
            "restored": restored,
            **({"restore_error": restore_error} if restore_error else {}),
        }

    @classmethod
    def get_game_preview_status(cls) -> dict:
        with cls._preview_lock:
            cls._prune_preview_locked()
            live = [info for info in cls._preview_threads if info["thread"].is_alive()]
            return {
                "status": cls._preview_status,
                "running_count": len(live),
                "has_snapshot": cls._preview_state_snapshot is not None,
                "errors": list(cls._preview_errors),
                "warnings": list(cls._preview_warnings),
            }

    @classmethod
    def _prepare_preview_targets(cls) -> tuple[list[dict], list[str]]:
        manifest = cls._load_manifest()
        project_scenes = cls._project_scene_routes()
        scene_order = {route: i for i, route in enumerate(project_scenes)}
        targets: list[dict] = []
        warnings: list[str] = []

        from CoronaCore.core.managers import scene_manager

        for route in project_scenes:
            try:
                scene_manager.get_or_create(route)
            except Exception as exc:
                warnings.append(f"场景加载失败，已跳过: {route} ({exc})")

        for target in manifest.get("targets", []):
            if not target.get("enabled", True):
                continue
            target_type = target.get("target_type")
            code_path = target.get("code_path")
            if not code_path or not (cls._active_project_path() / code_path).exists():
                warnings.append(f"积木代码不存在，已跳过: {target.get('id')}")
                continue
            if target_type == "project":
                targets.append(target)
                continue
            if target_type != "actor":
                warnings.append(f"未知积木目标，已跳过: {target.get('id')}")
                continue

            scene_name = target.get("scene_name", "")
            actor_name = target.get("actor_name", "")
            if scene_name not in scene_order:
                warnings.append(f"目标场景不在项目列表中，已跳过: {scene_name}/{actor_name}")
                continue
            scene = scene_manager.get_or_create(scene_name)
            if not scene or not scene.find_actor(actor_name):
                warnings.append(f"目标物体不存在，已跳过: {scene_name}/{actor_name}")
                continue
            targets.append(target)

        targets.sort(
            key=lambda t: (
                0 if t.get("target_type") == "project" else 1,
                scene_order.get(t.get("scene_name", ""), 999999),
                t.get("actor_name", ""),
            )
        )
        return targets, warnings

    @classmethod
    def _create_preview_state_snapshot(cls) -> dict[str, Any]:
        from CoronaCore.core.managers import scene_manager

        snapshot: dict[str, Any] = {"scenes": {}}
        for route in cls._project_scene_routes():
            scene = scene_manager.get_or_create(route)
            scene_state: dict[str, Any] = {
                "actors": {},
                "cameras": {},
                "environment": {},
                "enabled": cls._safe_call(scene, "is_enabled"),
                "simulation_enabled": cls._safe_call(scene, "is_simulation_enabled"),
            }

            env = scene.get_environment() if hasattr(scene, "get_environment") else None
            if env is not None:
                scene_state["environment"] = {
                    "sun_direction": cls._safe_call(env, "get_sun_direction"),
                    "floor_grid": cls._safe_call(env, "get_floor_grid"),
                    "gravity": cls._safe_call(env, "get_gravity"),
                    "floor_y": cls._safe_call(env, "get_floor_y"),
                    "floor_restitution": cls._safe_call(env, "get_floor_restitution"),
                    "fixed_dt": cls._safe_call(env, "get_fixed_dt"),
                }

            for camera in scene.get_cameras():
                camera_name = getattr(camera, "name", "")
                if not camera_name:
                    continue
                scene_state["cameras"][camera_name] = {
                    "position": cls._safe_call(camera, "get_position"),
                    "forward": cls._safe_call(camera, "get_forward"),
                    "world_up": cls._safe_call(camera, "get_world_up"),
                    "fov": cls._safe_call(camera, "get_fov"),
                    "output_mode": cls._safe_call(camera, "get_output_mode"),
                    "width": getattr(camera, "width", None),
                    "height": getattr(camera, "height", None),
                }

            for actor in scene.get_actors():
                actor_name = getattr(actor, "name", "")
                if not actor_name:
                    continue
                scene_state["actors"][actor_name] = {
                    "position": cls._safe_call(actor, "get_position"),
                    "rotation": cls._safe_call(actor, "get_rotation"),
                    "scale": cls._safe_call(actor, "get_scale"),
                    "visible": cls._safe_call(actor, "get_visible"),
                    "mass": cls._safe_call(actor, "get_mass"),
                    "restitution": cls._safe_call(actor, "get_restitution"),
                    "damping": cls._safe_call(actor, "get_damping"),
                    "physics_enabled": cls._safe_call(actor, "get_physics_enabled"),
                    "collision_enabled": cls._safe_call(actor, "get_collision_enabled"),
                }

            snapshot["scenes"][route] = scene_state

        logger.info("[ScratchTool] preview state snapshot captured: %d scenes", len(snapshot["scenes"]))
        return snapshot

    @classmethod
    def _restore_preview_state_snapshot(cls) -> tuple[bool, str | None]:
        with cls._preview_lock:
            snapshot = cls._preview_state_snapshot

        if not snapshot:
            return False, None

        try:
            cancel_pending_auto_saves()
            from CoronaCore.core.managers import scene_manager

            restored_scenes = set()
            for route, scene_state in (snapshot.get("scenes") or {}).items():
                scene = scene_manager.get(route)
                if scene is None:
                    continue

                cls._restore_scene_state(scene, scene_state)
                restored_scenes.add(route)
                try:
                    scene.save_data()
                except Exception:
                    logger.exception("[ScratchTool] failed to save restored scene: %s", route)

            with cls._preview_lock:
                cls._preview_state_snapshot = None

            cls._notify_preview_state_restored(restored_scenes)
            logger.info("[ScratchTool] preview state restored: %d scenes", len(restored_scenes))
            return True, None
        except Exception as exc:
            logger.exception("[ScratchTool] preview state restore failed")
            return False, str(exc)

    @staticmethod
    def _safe_call(target: object, method_name: str):
        if target is None or not hasattr(target, method_name):
            return None
        try:
            return getattr(target, method_name)()
        except Exception:
            return None

    @staticmethod
    def _apply_if_present(target: object, method_name: str, value, *extra_args) -> None:
        if value is None or target is None or not hasattr(target, method_name):
            return
        try:
            getattr(target, method_name)(value, *extra_args)
        except TypeError:
            getattr(target, method_name)(value)
        except Exception:
            logger.exception("[ScratchTool] restore %s failed", method_name)

    @classmethod
    def _restore_scene_state(cls, scene: object, scene_state: dict[str, Any]) -> None:
        cls._apply_if_present(scene, "set_enabled", scene_state.get("enabled"))
        cls._apply_if_present(scene, "set_simulation_enabled", scene_state.get("simulation_enabled"))

        env = scene.get_environment() if hasattr(scene, "get_environment") else None
        env_state = scene_state.get("environment") or {}
        if env is not None:
            cls._apply_if_present(env, "set_sun_direction", env_state.get("sun_direction"))
            cls._apply_if_present(env, "set_floor_grid", env_state.get("floor_grid"))
            cls._apply_if_present(env, "set_gravity", env_state.get("gravity"))
            cls._apply_if_present(env, "set_floor_y", env_state.get("floor_y"))
            cls._apply_if_present(env, "set_floor_restitution", env_state.get("floor_restitution"))
            cls._apply_if_present(env, "set_fixed_dt", env_state.get("fixed_dt"))

        for camera_name, camera_state in (scene_state.get("cameras") or {}).items():
            camera = scene.find_camera(camera_name) if hasattr(scene, "find_camera") else None
            if camera is None:
                continue
            position = camera_state.get("position")
            forward = camera_state.get("forward")
            world_up = camera_state.get("world_up")
            fov = camera_state.get("fov")
            if position is not None and forward is not None and world_up is not None and fov is not None:
                cls._apply_if_present(camera, "set", position, forward, world_up, fov)
            output_mode = camera_state.get("output_mode")
            cls._apply_if_present(camera, "set_output_mode", output_mode)
            width = camera_state.get("width")
            height = camera_state.get("height")
            if width is not None and height is not None:
                cls._apply_if_present(camera, "set_size", int(width), int(height))

        for actor_name, actor_state in (scene_state.get("actors") or {}).items():
            actor = scene.find_actor(actor_name) if hasattr(scene, "find_actor") else None
            if actor is None:
                continue
            cls._apply_if_present(actor, "set_position", actor_state.get("position"), True)
            cls._apply_if_present(actor, "set_rotation", actor_state.get("rotation"), True)
            cls._apply_if_present(actor, "set_scale", actor_state.get("scale"), True)
            cls._apply_if_present(actor, "set_visible", actor_state.get("visible"))
            cls._apply_if_present(actor, "set_mass", actor_state.get("mass"))
            cls._apply_if_present(actor, "set_restitution", actor_state.get("restitution"))
            cls._apply_if_present(actor, "set_damping", actor_state.get("damping"))
            cls._apply_if_present(actor, "set_physics_enabled", actor_state.get("physics_enabled"))
            cls._apply_if_present(actor, "set_collision_enabled", actor_state.get("collision_enabled"))

    @staticmethod
    def _notify_preview_state_restored(scene_routes: set[str]) -> None:
        try:
            selected_scene = CoronaEditor._selected_scene
            selected_actor = CoronaEditor._selected_actor
            for route in scene_routes or {selected_scene or ""}:
                CoronaEditor.js_call_func("scene-tree-changed", [route])
            if selected_scene and selected_actor:
                CoronaEditor.js_call_func("actor-change", ["actor", selected_scene, selected_actor])
            elif selected_scene:
                CoronaEditor.js_call_func("actor-change", ["scene", selected_scene, ""])
        except Exception:
            logger.exception("[ScratchTool] failed to notify frontend after preview state restore")

    @classmethod
    def _project_scene_routes(cls) -> list[str]:
        project_path = cls._active_project_path()
        ini_path = project_path / "project.ini"
        scenes = get_project_scenes(str(ini_path)) if ini_path.exists() else []
        if not scenes and (project_path / "Scene").is_dir():
            scenes = [
                f"Scene/{path.name}"
                for path in sorted((project_path / "Scene").iterdir())
                if path.suffix == ".scene"
            ]
        entrance = ""
        try:
            if settings_manager.active_project_config:
                entrance = settings_manager.active_project_config["Project"].get("entrance_scene", "")
        except Exception:
            entrance = ""
        if entrance and entrance not in scenes:
            scenes.insert(0, entrance)
        return scenes

    @classmethod
    def _run_preview_target(cls, code_path: Path, target: dict) -> None:
        cls._run_code_file(code_path, target, single_exec=False)
        with cls._preview_lock:
            cls._prune_preview_locked()

    @classmethod
    def _run_code_file(cls, code_path: Path, target: dict, single_exec: bool) -> None:
        from CoronaCore.utils import corona_engine_fallback, corona_engine_scratch

        context_id = target.get("id") or cls._target_id(
            target.get("target_type", "actor"),
            target.get("scene_name", ""),
            target.get("actor_name", ""),
        )
        ctx = corona_engine_scratch.create_context(
            context_id=context_id,
            target_type=target.get("target_type", "actor"),
            scene_name=target.get("scene_name", ""),
            actor_name=target.get("actor_name", ""),
        )
        corona_engine_scratch.bind_context(ctx)
        corona_engine_fallback.set_quiet(True)

        module_name = f"blockly_runtime_{cls._target_digest(context_id)}_{int(time.time() * 1000)}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, code_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载积木脚本: {code_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            if hasattr(module, "run"):
                module.run()
            if (ctx.key_handler is not None or ctx.mouse_handler is not None) and not ctx.stop_requested:
                while not ctx.stop_requested:
                    time.sleep(0.1)
        except SystemExit:
            logger.info("[ScratchTool] script stopped: %s", context_id)
        except Exception as exc:
            logger.exception("[ScratchTool] script failed: %s", context_id)
            if not single_exec:
                with cls._preview_lock:
                    cls._preview_errors.append(f"{context_id}: {exc}")
                    cls._preview_status = "error"
        finally:
            sys.modules.pop(module_name, None)
            corona_engine_scratch.release_context(ctx)

    @classmethod
    def _prune_preview_locked(cls) -> None:
        cls._preview_threads = [
            info for info in cls._preview_threads
            if info.get("thread") and info["thread"].is_alive()
        ]
        if not cls._preview_threads and cls._preview_status in ("running", "stopping"):
            cls._preview_status = "error" if cls._preview_errors else "idle"

    @staticmethod
    def _clear_backend_cache() -> None:
        for name in list(sys.modules.keys()):
            if name == "Backend" or name.startswith("Backend."):
                sys.modules.pop(name, None)

    # ------------------------------------------------------------------
    # Input bridge
    # ------------------------------------------------------------------
    @classmethod
    def key_event(cls, key: str, modifiers: str = "", display_key: str = "") -> dict:
        from CoronaCore.utils import corona_engine_scratch

        mods = [m.strip() for m in modifiers.split(",") if m.strip()] if modifiers else []
        corona_engine_scratch.handle_key_event(key, mods, display_key or key)
        return {"status": "ok"}

    @classmethod
    def key_release(cls, key: str, display_key: str = "") -> dict:
        from CoronaCore.utils import corona_engine_scratch

        corona_engine_scratch.handle_key_release(key, display_key or key)
        return {"status": "ok"}

    @classmethod
    def mouse_event(
        cls,
        event_type: str,
        button: str = "",
        x: float = 0.0,
        y: float = 0.0,
    ) -> dict:
        from CoronaCore.utils import corona_engine_scratch

        corona_engine_scratch.handle_mouse_event(event_type, button, x, y)
        return {"status": "ok"}
