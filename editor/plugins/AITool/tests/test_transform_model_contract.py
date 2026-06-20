import importlib
import json
import sys
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EDITOR_ROOT = PROJECT_ROOT.parent
AITOOL_ROOT = PROJECT_ROOT / "plugins" / "AITool"
for path in (EDITOR_ROOT, AITOOL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


def install_tool_import_stubs():
    langchain_core = types.ModuleType("langchain_core")
    langchain_tools = types.ModuleType("langchain_core.tools")

    class FakeStructuredTool:
        def __init__(self, *, name, description, args_schema, func):
            self.name = name
            self.description = description
            self.args_schema = args_schema
            self.func = func

    langchain_tools.StructuredTool = FakeStructuredTool
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.tools"] = langchain_tools

    pydantic = types.ModuleType("pydantic")

    class FakeBaseModel:
        def __init__(self, **kwargs):
            for cls in reversed(type(self).mro()):
                for key, value in cls.__dict__.items():
                    if key.startswith("_") or callable(value):
                        continue
                    setattr(self, key, value)
            for key, value in kwargs.items():
                setattr(self, key, value)

    def fake_field(default=None, **_kwargs):
        return default

    pydantic.BaseModel = FakeBaseModel
    pydantic.Field = fake_field
    sys.modules["pydantic"] = pydantic

    quasar = types.ModuleType("Quasar")
    ai_tools = types.ModuleType("Quasar.ai_tools")
    response_adapter = types.ModuleType("Quasar.ai_tools.response_adapter")

    class FakeToolResult:
        def __init__(self, *, parts, error_code=0, status_info="success"):
            self.parts = parts
            self.error_code = error_code
            self.status_info = status_info

        def to_envelope(self, interface_type=None, **_kwargs):
            return json.dumps(
                {
                    "error_code": self.error_code,
                    "status_info": self.status_info,
                    "llm_content": [
                        {
                            "role": "tools",
                            "interface_type": interface_type,
                            "part": self.parts,
                        }
                    ],
                },
                ensure_ascii=False,
            )

    response_adapter.build_part = lambda **kwargs: {
        "content_type": kwargs["content_type"],
        "content_text": kwargs.get("content_text", ""),
    }
    response_adapter.build_success_result = lambda *, parts, **_kwargs: FakeToolResult(
        parts=parts
    )
    response_adapter.build_error_result = lambda *, error_message, **_kwargs: FakeToolResult(
        parts=[response_adapter.build_part(content_type="text", content_text=error_message)],
        error_code=1,
        status_info=error_message,
    )

    ai_config = types.ModuleType("Quasar.ai_config")
    prompts = types.ModuleType("Quasar.ai_config.prompts")

    @dataclass
    class ToolPromptConfig:
        tool_description: str
        fields: dict = field(default_factory=dict)

    @dataclass
    class SceneToolPrompts:
        query: ToolPromptConfig
        transform: ToolPromptConfig

    prompts.ToolPromptConfig = ToolPromptConfig
    prompts.SceneToolPrompts = SceneToolPrompts

    sys.modules["Quasar"] = quasar
    sys.modules["Quasar.ai_tools"] = ai_tools
    sys.modules["Quasar.ai_tools.response_adapter"] = response_adapter
    sys.modules["Quasar.ai_config"] = ai_config
    sys.modules["Quasar.ai_config.prompts"] = prompts


class FakeActor:
    name = "cube"

    def __init__(self):
        self.position = [1.0, 2.0, 3.0]
        self.rotation = [10.0, 20.0, 30.0]
        self.scale = [2.0, 3.0, 4.0]

    def translate(self, vector):
        self.position = [a + b for a, b in zip(self.position, vector)]

    def rotate_delta(self, vector):
        self.rotation = [a + b for a, b in zip(self.rotation, vector)]

    def scale_delta(self, factor):
        if isinstance(factor, (int, float)):
            factor = [factor, factor, factor]
        self.scale = [a * b for a, b in zip(self.scale, factor)]

    def get_position(self):
        return self.position

    def get_rotation(self):
        return self.rotation

    def get_scale(self):
        return self.scale


class FakeScene:
    def __init__(self, actor):
        self.actor = actor

    def find_actor(self, name):
        return self.actor if name == self.actor.name else None


class FakeSceneManager:
    def __init__(self, scene):
        self.scene = scene

    def get(self, route):
        return self.scene if route in ("", "main.scene") else None

    def list_all(self):
        return ["main.scene"]


def envelope_payload(result):
    envelope = json.loads(result)
    text = envelope["llm_content"][0]["part"][0]["content_text"]
    return json.loads(text)


class TransformModelContractTests(unittest.TestCase):
    def setUp(self):
        install_tool_import_stubs()
        for name in (
            "cai_extensions.mcp.tools",
            "cai_extensions.mcp.tools.scene_tools",
        ):
            sys.modules.pop(name, None)

    def assert_transform_tool_uses_relative_contract(self, module_name):
        module = importlib.import_module(module_name)
        actor = FakeActor()
        tool = module._build_transform_tool(FakeSceneManager(FakeScene(actor)))

        payload = envelope_payload(
            tool.func(model_name="cube", operation="translate", vector=(0.5, -1.0, 2.0))
        )
        self.assertEqual(payload["position"], [1.5, 1.0, 5.0])

        payload = envelope_payload(
            tool.func(model_name="cube", operation="rotate_delta", vector=(5.0, 0.0, -10.0))
        )
        self.assertEqual(payload["rotation"], [15.0, 20.0, 20.0])

        payload = envelope_payload(
            tool.func(model_name="cube", operation="scale_delta", scale_factor=2.0)
        )
        self.assertEqual(payload["scale"], [4.0, 6.0, 8.0])

        payload = envelope_payload(
            tool.func(model_name="cube", operation="scale", vector=(0.5, 1.0, 0.25))
        )
        self.assertEqual(payload["scale"], [2.0, 6.0, 2.0])

    def test_package_transform_model_uses_relative_contract(self):
        self.assert_transform_tool_uses_relative_contract("cai_extensions.mcp.tools")

    def test_scene_tools_transform_model_uses_relative_contract(self):
        self.assert_transform_tool_uses_relative_contract(
            "cai_extensions.mcp.tools.scene_tools"
        )


if __name__ == "__main__":
    unittest.main()
