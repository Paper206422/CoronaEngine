import asyncio
import importlib
import json
import sys
import tempfile
import tomllib
import types
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
AITOOL_ROOT = PROJECT_ROOT / "plugins" / "AITool"
if str(AITOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(AITOOL_ROOT))


class FakeCoronaEditor:
    calls = []

    @classmethod
    def register_page(cls, *_args, **_kwargs):
        return None

    @classmethod
    def js_call_func(cls, *args):
        if len(args) == 2:
            _event_name, payload = args
            cls.calls.append(("/AITalkBar", "receiveAIMessageChunk", payload))
        else:
            path, function_name, payload = args
            cls.calls.append((path, function_name, payload))


class FakeLoop:
    def __init__(self):
        self.calls = []

    def is_closed(self):
        return False

    def call_soon_threadsafe(self, callback, *args):
        self.calls.append((callback, args))


class FakeEventLoopRunner:
    def __init__(self):
        self.calls = []
        self.loop = FakeLoop()

    def submit(self, coro, request_id, request_service):
        self.calls.append((coro, request_id, request_service))


def install_import_stubs():
    langchain_core_module = types.ModuleType("langchain_core")
    langchain_api_module = types.ModuleType("langchain_core._api")
    langchain_deprecation_module = types.ModuleType("langchain_core._api.deprecation")

    class LangChainPendingDeprecationWarning(Warning):
        pass

    setattr(
        langchain_deprecation_module,
        "LangChainPendingDeprecationWarning",
        LangChainPendingDeprecationWarning,
    )
    sys.modules["langchain_core"] = langchain_core_module
    sys.modules["langchain_core._api"] = langchain_api_module
    sys.modules["langchain_core._api.deprecation"] = langchain_deprecation_module

    langchain_tools_module = types.ModuleType("langchain_core.tools")

    class BaseTool:
        pass

    setattr(langchain_tools_module, "BaseTool", BaseTool)
    sys.modules["langchain_core.tools"] = langchain_tools_module

    yaml_module = types.ModuleType("yaml")

    def safe_load(stream):
        text = stream.read() if hasattr(stream, "read") else str(stream)
        result = {"modules": []}
        current = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line == "modules:":
                continue
            if line.startswith("- "):
                current = {}
                result["modules"].append(current)
                line = line[2:].strip()
            if ":" not in line or current is None:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if value.lower() == "true":
                parsed_value = True
            elif value.lower() == "false":
                parsed_value = False
            else:
                parsed_value = value.strip("\"'")
            current[key.strip()] = parsed_value
        return result

    yaml_module.safe_load = safe_load
    sys.modules["yaml"] = yaml_module

    corona_editor_module = types.ModuleType("CoronaCore.core.corona_editor")
    setattr(corona_editor_module, "CoronaEditor", FakeCoronaEditor)
    sys.modules["CoronaCore.core.corona_editor"] = corona_editor_module

    plugin_base_module = types.ModuleType("CoronaPlugin.core.corona_plugin_base")

    class FakePluginBase:
        @classmethod
        def register_web(cls, *_args, **_kwargs):
            def decorator(plugin_cls):
                return plugin_cls

            return decorator

    setattr(plugin_base_module, "PluginBase", FakePluginBase)
    sys.modules["CoronaPlugin.core.corona_plugin_base"] = plugin_base_module

    cai_register_module = types.ModuleType("plugins.AITool.cai_extensions.register")
    setattr(cai_register_module, "install", lambda *_args, **_kwargs: None)
    setattr(cai_register_module, "bootstrap_paths", lambda *_args, **_kwargs: None)
    sys.modules["plugins.AITool.cai_extensions.register"] = cai_register_module

    entrance_module = types.ModuleType(
        "Quasar.ai_service.entrance"
    )
    setattr(
        entrance_module,
        "get_ai_entrance",
        lambda: types.SimpleNamespace(
            handle_integrated_entrance_stream=lambda _payload: iter(())
        ),
    )

    class FakeConfigCollector:
        AI_SETTINGS = {}

        def register_loader(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

        def register_setting(self, *_args, **_kwargs):
            def decorator(func):
                return func

            return decorator

    setattr(entrance_module, "ai_entrance", types.SimpleNamespace(collector=FakeConfigCollector()))
    sys.modules[
        "Quasar.ai_service.entrance"
    ] = entrance_module
    sys.modules[
        "plugins.AITool.Quasar.ai_service.entrance"
    ] = entrance_module

    common_module = types.ModuleType(
        "plugins.AITool.Quasar.ai_tools.common"
    )

    def build_error_response(interface_type, session_id, exc, metadata):
        return json.dumps(
            {
                "session_id": session_id,
                "error_code": "INTERNAL_ERROR",
                "status_info": str(exc),
                "llm_content": [
                    {
                        "role": "assistant",
                        "interface_type": interface_type,
                        "part": [
                            {
                                "content_type": "text",
                                "content_text": str(exc),
                            }
                        ],
                    }
                ],
                "metadata": metadata,
            },
            ensure_ascii=False,
        )

    setattr(common_module, "build_error_response", build_error_response)
    sys.modules["Quasar.ai_tools.common"] = common_module
    sys.modules["plugins.AITool.Quasar.ai_tools.common"] = common_module

    image_utils_module = types.ModuleType("plugins.AITool.utils.image_utils")
    setattr(image_utils_module, "base64_to_image_file", lambda value: value)
    setattr(image_utils_module, "upload_file_to_server", lambda value: value)
    sys.modules["plugins.AITool.utils.image_utils"] = image_utils_module


def import_ai_tool_module():
    install_import_stubs()
    sys.modules.pop("plugins.AITool.main", None)
    module = importlib.import_module("plugins.AITool.main")
    setattr(module, "CoronaEditor", FakeCoronaEditor)
    return module


class AIToolRpcTests(unittest.TestCase):
    def setUp(self):
        FakeCoronaEditor.calls = []
        self.module = import_ai_tool_module()
        self.ai_tool = self.module.AITool
        self.ai_tool._request_service.states = {}
        self.ai_tool._request_states = self.ai_tool._request_service.states

    def test_main_adds_aitool_root_for_cai_package_imports(self):
        sys.modules.pop("plugins.AITool.main", None)
        while str(AITOOL_ROOT) in sys.path:
            sys.path.remove(str(AITOOL_ROOT))

        module = import_ai_tool_module()

        self.assertIs(module.AITool._cai_app, module.AITool._cai_client._cai_app)
        self.assertIn(str(AITOOL_ROOT), sys.path)

    def test_prepare_ai_message_adds_request_id_to_legacy_payload(self):
        payload = {"session_id": "sid-1", "metadata": {}, "llm_content": []}

        ai_message, request_id, session_id = self.ai_tool._controller.request_service.prepare_legacy_message(
            json.dumps(payload)
        )

        parsed = json.loads(ai_message)
        self.assertEqual(session_id, "sid-1")
        self.assertTrue(request_id.startswith("req_"))
        self.assertEqual(parsed["metadata"]["request_id"], request_id)

    def test_ai_rpc_accepts_chat_stream_and_generates_request_id(self):
        fake_runner = FakeEventLoopRunner()
        self.ai_tool._controller._event_loop_runner = fake_runner
        self.ai_tool._controller._process_ai_message_stream = (
            lambda ai_message, request_id=None: (ai_message, request_id)
        )

        response = self.ai_tool.ai_rpc(
            {
                "operation": "chat.stream",
                "session_id": "sid-2",
                "payload": {"session_id": "sid-2", "metadata": {}, "llm_content": []},
            }
        )

        self.assertTrue(response["success"])
        self.assertEqual(response["status"], "accepted")
        self.assertTrue(response["request_id"].startswith("req_"))
        self.assertEqual(self.ai_tool._request_service.states[response["request_id"]]["status"], "accepted")
        self.assertEqual(len(fake_runner.calls), 1)

    def test_request_status_returns_serializable_state(self):
        self.ai_tool._request_service.states["req-known"] = {
            "request_id": "req-known",
            "session_id": "sid-3",
            "status": "running",
            "task": object(),
        }

        response = self.ai_tool.ai_rpc(
            {"operation": "request.status", "request_id": "req-known"}
        )

        self.assertEqual(response["request_id"], "req-known")
        self.assertEqual(response["session_id"], "sid-3")
        self.assertEqual(response["status"], "running")
        self.assertNotIn("task", response)
        json.dumps(response)

    def test_request_cancel_marks_running_task_as_cancelling(self):
        loop = asyncio.new_event_loop()
        task = None
        try:
            task = loop.create_task(asyncio.sleep(60))
            self.ai_tool._controller._event_loop_runner = types.SimpleNamespace(
                loop=types.SimpleNamespace(
                    call_soon_threadsafe=lambda callback, *args: callback(*args)
                )
            )
            self.ai_tool._request_service.states["req-cancel"] = {
                "request_id": "req-cancel",
                "session_id": "sid-4",
                "status": "running",
                "task": task,
            }

            response = self.ai_tool.ai_rpc(
                {"operation": "request.cancel", "request_id": "req-cancel"}
            )

            self.assertTrue(response["success"])
            self.assertEqual(response["status"], "cancelling")
            self.assertEqual(self.ai_tool._request_service.states["req-cancel"]["status"], "cancelling")
            self.assertTrue(task.cancelled() or task.cancelling())
        finally:
            if task is not None:
                task.cancel()
                loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
            loop.close()

    def test_get_stream_event_type_recognizes_heartbeat(self):
        event_type = self.module.StreamDispatcher.get_stream_event_type(
            {"metadata": {"heartbeat": True}, "llm_content": []}
        )

        self.assertEqual(event_type, "heartbeat")

    def test_process_stream_forwards_done_event_with_request_id(self):
        payload = {"session_id": "sid-5", "metadata": {}, "llm_content": []}
        done_chunk = json.dumps(
            {"session_id": "sid-5", "metadata": {"stream_done": True}, "llm_content": []}
        )

        setattr(
            self.module,
            "get_ai_entrance",
            lambda: types.SimpleNamespace(
                handle_integrated_entrance_stream=lambda _payload: iter([done_chunk])
            ),
        )

        async def run_stream():
            self.ai_tool._controller._event_loop_runner.loop = asyncio.get_running_loop()
            await self.ai_tool._controller._process_ai_message_stream(
                json.dumps(payload), "req-done"
            )

        asyncio.run(run_stream())

        self.assertEqual(len(FakeCoronaEditor.calls), 1)
        path, function_name, args = FakeCoronaEditor.calls[0]
        self.assertEqual(path, "/AITalkBar")
        self.assertEqual(function_name, "receiveAIMessageChunk")
        result = json.loads(args[0])
        self.assertTrue(result["metadata"]["stream_done"])
        self.assertEqual(result["metadata"]["request_id"], "req-done")

    def test_process_stream_forwards_error_chunk_with_request_id(self):
        payload = {"session_id": "sid-6", "metadata": {}, "llm_content": []}

        def raising_handler(_payload):
            raise RuntimeError("boom")
            yield  # pragma: no cover

        setattr(
            self.module,
            "get_ai_entrance",
            lambda: types.SimpleNamespace(handle_integrated_entrance_stream=raising_handler),
        )

        async def run_stream():
            self.ai_tool._controller._event_loop_runner.loop = asyncio.get_running_loop()
            await self.ai_tool._controller._process_ai_message_stream(
                json.dumps(payload), "req-error"
            )

        asyncio.run(run_stream())

        self.assertEqual(len(FakeCoronaEditor.calls), 1)
        result = json.loads(FakeCoronaEditor.calls[0][2][0])
        self.assertEqual(result["error_code"], "INTERNAL_ERROR")
        self.assertEqual(result["metadata"]["request_id"], "req-error")
        self.assertIn("boom", result["status_info"])

    def test_cai_app_chat_stream_wraps_legacy_entrance(self):
        from Quasar.cai import CAIApp

        def legacy_stream(payload):
            yield json.dumps(
                {
                    "session_id": payload["session_id"],
                    "metadata": payload["metadata"],
                    "llm_content": [],
                }
            )

        app = CAIApp.from_legacy_entrance(
            lambda: types.SimpleNamespace(handle_integrated_entrance_stream=legacy_stream)
        )

        chunks = list(
            app.chat_stream(
                {
                    "session_id": "sid-7",
                    "metadata": {"request_id": "req-cai"},
                    "llm_content": [],
                }
            )
        )

        self.assertEqual(len(chunks), 1)
        result = json.loads(chunks[0])
        self.assertEqual(result["session_id"], "sid-7")
        self.assertEqual(result["metadata"]["request_id"], "req-cai")

    def test_cai_runtime_accepts_runtime_scoped_registries(self):
        from Quasar.cai import CAIRuntime

        tool_registry = object()
        runtime = CAIRuntime(
            ai_entrance_provider=lambda: types.SimpleNamespace(),
            registries={"tool": tool_registry},
        )

        self.assertIs(runtime.get_registry("tool"), tool_registry)

    def test_event_loop_runner_submits_to_started_loop(self):
        from plugins.AITool.services.event_loop_runner import EventLoopRunner

        runner = EventLoopRunner()
        fake_loop = FakeLoop()
        runner.loop = fake_loop

        with patch("plugins.AITool.services.event_loop_runner.threading.Thread") as thread_cls:
            thread_instance = thread_cls.return_value
            thread_instance.is_alive.return_value = False

            runner.submit("fake-coro", "req-loop", types.SimpleNamespace(attach_task=lambda *_args: None))

            thread_cls.assert_called_once()
            self.assertEqual(thread_cls.call_args.kwargs["args"], (fake_loop,))
            self.assertEqual(len(fake_loop.calls), 1)

    def test_plugin_manager_loads_module_settings_manifest(self):
        from Quasar.cai import CAIRuntime

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_root = root / "phase4_modules"
            module_root = package_root / "demo"
            for directory in [package_root, module_root, module_root / "configs", module_root / "tools"]:
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "__init__.py").write_text("", encoding="utf-8")
            (module_root / "configs" / "settings.py").write_text("LOADED = 'settings'\n", encoding="utf-8")
            (module_root / "base.py").write_text("LOADED = 'base'\n", encoding="utf-8")
            (module_root / "tools" / "loader.py").write_text("LOADED = 'loader'\n", encoding="utf-8")
            manifest = root / "module_settings.yaml"
            manifest.write_text(
                "modules:\n"
                "  - name: demo\n"
                "    enabled: true\n"
                "    module_base: phase4_modules\n"
                "  - name: disabled_demo\n"
                "    enabled: false\n"
                "    module_base: phase4_modules\n",
                encoding="utf-8",
            )

            sys.path.insert(0, str(root))
            try:
                runtime = CAIRuntime(ai_entrance_provider=lambda: types.SimpleNamespace())
                summary = runtime.plugin_manager.load_module_settings(manifest, package_root)
            finally:
                sys.path.remove(str(root))

        self.assertEqual(summary["configs"], ["demo"])
        self.assertEqual(summary["base"], ["demo"])
        self.assertEqual(summary["loader"], ["demo"])
        self.assertEqual(summary["disabled"], ["disabled_demo"])
        self.assertEqual(summary["failed"], [])

    def test_runtime_entrance_registry_overrides_legacy_entrance(self):
        from Quasar.cai import CAIRuntime

        runtime = CAIRuntime(
            ai_entrance_provider=lambda: types.SimpleNamespace(
                handle_integrated_entrance_stream=lambda _payload: iter(["legacy"])
            )
        )
        runtime.register_entrance_handler("handle_integrated_entrance_stream", lambda _payload: iter(["runtime"]))

        self.assertEqual(list(runtime.chat_stream({})), ["runtime"])

    def test_cabbage_adapter_install_registers_runtime_plugins(self):
        sys.modules.pop("plugins.AITool.cai_extensions.register", None)
        from plugins.AITool.cai_extensions.register import CabbageContext, install

        class FakeApp:
            def __init__(self):
                self.plugins = []

            def register_plugin(self, plugin):
                self.plugins.append(plugin)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = CabbageContext(
                aitool_dir=root / "AITool",
                cai_dir=root / "AITool" / "Quasar",
            )
            context.cai_dir.mkdir(parents=True)
            app = FakeApp()
            install(app, context)

        self.assertEqual(
            [plugin.name for plugin in app.plugins],
            [
                "cabbage.paths",
                "cabbage.app_config",
                "cabbage.engine_tools",
                "cabbage.workflows",
                "cabbage.engine_modules",
            ],
        )

    def test_cabbage_adapter_bootstrap_does_not_modify_sys_path(self):
        sys.modules.pop("plugins.AITool.cai_extensions.register", None)
        before = list(sys.path)

        module = importlib.import_module("plugins.AITool.cai_extensions.register")

        self.assertEqual(sys.path, before)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = module.CabbageContext(
                aitool_dir=root / "AITool",
                cai_dir=root / "AITool" / "Quasar",
            )
            context.aitool_dir.mkdir(parents=True)
            context.cai_dir.mkdir(parents=True)

            self.assertIs(module.bootstrap_paths(context), context)
            self.assertEqual(sys.path, before)

    def test_cabbage_adapter_registers_runtime_scoped_capabilities(self):
        sys.modules.pop("plugins.AITool.cai_extensions.register", None)
        from Quasar.cai import CAIRuntime
        from plugins.AITool.cai_extensions.register import (
            CabbageAppConfigPlugin,
            CabbageContext,
            CabbageEngineToolsPlugin,
            CabbagePathsPlugin,
        )

        runtime = CAIRuntime(ai_entrance_provider=lambda: types.SimpleNamespace())

        context = CabbageContext.from_default_locations()
        CabbagePathsPlugin(context).register(runtime)
        CabbageAppConfigPlugin(context).register(runtime)
        CabbageEngineToolsPlugin(context).register(runtime)

        self.assertIsNotNone(runtime.get_capability("paths_resolver"))
        self.assertTrue(callable(runtime.get_capability("app_config_provider")))
        self.assertEqual(len(runtime.get_capability("tool_loader_registrars")), 1)

    def test_cai_core_imports_without_cabbage_adapter(self):
        module_name = "Quasar.cai"
        removed_modules = {
            name: sys.modules.pop(name)
            for name in list(sys.modules)
            if name == module_name or name.startswith(f"{module_name}.")
        }
        try:
            module = importlib.import_module(module_name)
            self.assertTrue(hasattr(module, "CAIApp"))
            self.assertTrue(hasattr(module, "CAIRuntime"))
        finally:
            for name in list(sys.modules):
                if name == module_name or name.startswith(f"{module_name}."):
                    sys.modules.pop(name, None)
            for name in removed_modules:
                sys.modules.pop(name, None)
            sys.modules.update(removed_modules)

    def test_cai_pyproject_declares_standalone_metadata(self):
        cai_root = PROJECT_ROOT / "plugins" / "AITool" / "Quasar"
        data = tomllib.loads((cai_root / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(data["project"]["name"], "quasar")
        self.assertEqual(
            data["project"]["scripts"]["quasar-chat"],
            "Quasar.cai.cli:main",
        )
        optional = data["project"]["optional-dependencies"]
        self.assertTrue({"langchain", "workflow", "media", "cabbage"}.issubset(optional))

    def test_cai_package_imports_from_submodule_parent(self):
        aitool_dir = AITOOL_ROOT
        module_prefix = "Quasar"
        removed_modules = {
            name: sys.modules.pop(name)
            for name in list(sys.modules)
            if name == module_prefix or name.startswith(f"{module_prefix}.")
        }
        inserted = False
        if str(aitool_dir) not in sys.path:
            sys.path.insert(0, str(aitool_dir))
            inserted = True
        try:
            module = importlib.import_module("Quasar.cai")
            self.assertTrue(hasattr(module, "CAIApp"))
            self.assertTrue(hasattr(module, "ChatRequest"))
        finally:
            if inserted:
                sys.path.remove(str(aitool_dir))
            for name in list(sys.modules):
                if name == module_prefix or name.startswith(f"{module_prefix}."):
                    sys.modules.pop(name, None)
            sys.modules.update(removed_modules)


if __name__ == "__main__":
    unittest.main()
