import importlib
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
AITOOL_ROOT = PROJECT_ROOT / "plugins" / "AITool"
for path in (str(AITOOL_ROOT), str(PROJECT_ROOT)):
    while path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)


class _FakeRegistry:
    def __init__(self):
        self.items = {}

    def register(self, key, value, overwrite=False):
        if not overwrite and key in self.items:
            raise KeyError(key)
        self.items[key] = value


class _FakeRuntime:
    def __init__(self):
        self.metadata = {}
        self.registries = {
            "workflow": _FakeRegistry(),
            "workflow_command": _FakeRegistry(),
        }

    def get_registry(self, name):
        return self.registries[name]


class WorkflowImportTests(unittest.TestCase):
    def setUp(self):
        sys.modules.pop("utils", None)
        sys.modules.pop("utils.settings", None)
        for name in list(sys.modules):
            if name.startswith("plugins.AITool.cai_extensions.flows."):
                sys.modules.pop(name, None)

    def test_scene_composition_workflows_import_without_cycle(self):
        for module_name in (
            "plugins.AITool.cai_extensions.flows.scene_composition_workflow",
            "plugins.AITool.cai_extensions.flows.scene_composition_workflow_v2",
        ):
            module = importlib.import_module(module_name)
            self.assertTrue(module.WORKFLOWS)

    def test_full_pipeline_imports_terrain_classifier_node(self):
        module = importlib.import_module(
            "plugins.AITool.cai_extensions.flows.full_pipeline_workflow"
        )
        self.assertTrue(module.WORKFLOWS)

    def test_cabbage_workflow_plugin_registers_without_import_warnings(self):
        from plugins.AITool.cai_extensions.register import (
            CabbageContext,
            CabbageWorkflowPlugin,
        )

        plugin = CabbageWorkflowPlugin(CabbageContext.from_default_locations())
        runtime = _FakeRuntime()

        with self.assertNoLogs("plugins.AITool.cai_extensions.register", level="WARNING"):
            result = plugin.register(runtime)

        self.assertIn("flows", result)
        self.assertIn("commands", result)
        self.assertTrue(runtime.registries["workflow"].items)
        self.assertTrue(runtime.registries["workflow_command"].items)


if __name__ == "__main__":
    unittest.main()
