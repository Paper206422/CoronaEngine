import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from plugins.SceneTools import main as scene_tools_module


class FakeEngineScene:
    def __init__(self):
        self.added = []

    def add_actor(self, actor):
        self.added.append(actor)


class FakeActor:
    def __init__(self, route, source_index=0, actor_type='model', parent_scene=None, actor_data=None):
        self.route = route
        self.actor_type = actor_type
        self.parent = parent_scene
        self.actor_data = actor_data or {}
        self.handle = 4242
        self.engine_obj = SimpleNamespace(handle=4242)
        self.visible = True
        self.physics_enabled = True
        self.collision_type = 'box'
        self.scale = [1.0, 1.0, 1.0]
        self.editor_temporary = False

    def set_visible(self, visible):
        self.visible = bool(visible)

    def set_editor_temporary(self, enabled):
        self.editor_temporary = bool(enabled)

    def set_physics_enabled(self, enabled):
        self.physics_enabled = bool(enabled)

    def set_collision_enabled(self, collision_type):
        self.collision_type = collision_type

    def set_scale(self, scale, if_init=False):
        self.scale = list(scale)


class CursorActorProvisioningTests(unittest.TestCase):
    def test_ensure_cursor_actor_is_temporary_hidden_and_registered_with_engine_scene(self):
        scene = SimpleNamespace(
            route='Scene/main.scene',
            _actors=[],
            engine_scene=FakeEngineScene(),
        )
        fake_scene_manager = SimpleNamespace(get=lambda name: scene)

        with patch.object(scene_tools_module, 'scene_manager', fake_scene_manager), \
             patch.object(scene_tools_module, 'Actor', FakeActor), \
             patch.object(scene_tools_module, '_active_project_path', lambda: 'D:/Project'):
            result = scene_tools_module.SceneTools.ensure_3d_cursor_actor('Scene/main.scene')

        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['actorHandle'], 4242)
        self.assertEqual(result['cursor']['actorHandle'], 4242)
        self.assertEqual(scene._actors, [])
        self.assertEqual(scene.engine_scene.added, [scene._editor_3d_cursor_actor.engine_obj])
        self.assertFalse(scene._editor_3d_cursor_actor.visible)
        self.assertTrue(scene._editor_3d_cursor_actor.editor_temporary)
        self.assertFalse(scene._editor_3d_cursor_actor.physics_enabled)
        self.assertEqual(scene._editor_3d_cursor_actor.collision_type, 'none')
        self.assertEqual(
            scene._editor_3d_cursor_actor.actor_data['_suppress_network_broadcast'],
            True,
        )


if __name__ == '__main__':
    unittest.main()
