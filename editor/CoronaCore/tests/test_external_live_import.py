import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.SceneTools import main as scene_tools_module


class FakeCamera:
    def __init__(self):
        self.render_backend = "native"
        self.call_order = []
        self.name = "Camera"
        self.camera_id = "camera-1"
        self.position = [0.0, 0.0, 0.0]
        self.forward = [0.0, 0.0, 1.0]
        self.world_up = [0.0, 1.0, 0.0]
        self.fov = 45.0

    def set(self, position, forward, world_up, fov):
        self.position = list(position)
        self.forward = list(forward)
        self.world_up = list(world_up)
        self.fov = float(fov)

    def set_render_backend(self, mode):
        self.call_order.append(f"set_render_backend:{mode}")
        self.render_backend = mode

    def to_dict(self):
        return {
            "name": self.name,
            "position": self.position,
            "forward": self.forward,
            "world_up": self.world_up,
            "fov": self.fov,
            "render_backend": self.render_backend,
        }


class FakeEngineScene:
    def set_active_camera(self, camera):
        self.active_camera = camera


class FakeScene:
    def __init__(self):
        self.route = "Scene/main.scene"
        self.file_data = {}
        self.engine_scene = FakeEngineScene()
        self._actors = []
        self._camera = FakeCamera()
        self.vision_source_path = ""
        self.vision_import_mode = ""
        self.vision_bindings = []
        self.vision_unsupported_shapes = []
        self.saved = False
        self.tree_notified = False

    def ensure_default_camera(self):
        return None

    def get_active_camera(self):
        return self._camera

    def get_actors(self):
        return self._actors

    def set_camera(self, position, forward, up, fov, camera_name=None):
        self._camera.set(position, forward, up, fov)
        return True

    def add_actor(self, actor):
        existing_names = {item.name for item in self._actors}
        base_name = actor.name
        suffix = 1
        while actor.name in existing_names:
            actor.name = f"{base_name}_{suffix}"
            suffix += 1
        self._actors.append(actor)

    def save_data(self):
        self.saved = True

    def _notify_scene_tree_changed(self):
        self.tree_notified = True


class FakeActor:
    def __init__(self, name="", route=None, source_index=0, actor_type="actor",
                 parent_scene=None, actor_data=None):
        self.name = name
        self.route = route
        self.actor_type = actor_type
        self.parent_scene = parent_scene
        self.actor_guid = actor_data.get("actor_guid", "") if actor_data else ""
        geometry = actor_data.get("geometry", {}) if actor_data else {}
        self.position = geometry.get("position", [0.0, 0.0, 0.0])
        self.rotation = geometry.get("rotation", [0.0, 0.0, 0.0])
        self.scale = geometry.get("scale", [1.0, 1.0, 1.0])
        self.physics_enabled = True

    def set_position(self, position, if_init=False):
        self.position = position

    def set_rotation(self, rotation, if_init=False):
        self.rotation = rotation

    def set_scale(self, scale, if_init=False):
        self.scale = scale

    def set_physics_enabled(self, enabled):
        self.physics_enabled = bool(enabled)


class ExternalLiveImportTests(unittest.TestCase):
    def test_vision_cube_primitive_uses_vision_dimension_fallbacks(self):
        vertices, faces = scene_tools_module._vision_primitive_vertices({
            "param": {"x": 2, "y": 0, "z": 0},
        }, "cube")

        self.assertEqual(len(vertices), 8)
        self.assertEqual(len(faces), 6)
        self.assertEqual(max(abs(vertex[1]) for vertex in vertices), 1.0)
        self.assertEqual(max(abs(vertex[2]) for vertex in vertices), 1.0)

    def test_vision_sphere_primitive_matches_vision_subdivision_counts(self):
        vertices, faces = scene_tools_module._vision_primitive_vertices({
            "param": {"radius": 2, "sub_div": 3},
        }, "sphere")

        self.assertEqual(len(vertices), 14)
        self.assertEqual(len(faces), 24)
        self.assertEqual(vertices[0], [0.0, 2.0, 0.0])
        self.assertEqual(vertices[-1], [0.0, -2.0, 0.0])

    def test_import_creates_proxy_actors_and_persists_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model_path = root / "chair.obj"
            model_path.write_text("mesh", encoding="utf-8")
            vision_scene = root / "scene.json"
            vision_scene.write_text(json.dumps({
                "scene": {
                    "camera": {
                        "param": {
                            "transform": {
                                "param": {
                                    "position": [4, 5, 6],
                                    "target_pos": [4, 5, 5],
                                    "up": [0, 1, 0],
                                },
                            },
                            "fov_y": 1.0,
                        },
                    },
                    "shapes": [
                        {
                            "type": "model",
                            "name": "Chair",
                            "guid": "shape-chair",
                            "param": {
                                "fn": "chair.obj",
                                "transform": {
                                    "type": "trs",
                                    "param": {
                                        "t": [1, 2, 3],
                                        "s": [2, 2, 2],
                                    },
                                },
                            },
                        },
                        {
                            "type": "quad",
                            "name": "Floor",
                            "param": {
                                "width": 2,
                                "height": 2,
                                "transform": {
                                    "type": "matrix4x4",
                                    "param": {
                                        "matrix4x4": [
                                            [1, 0, 0, 0],
                                            [0, 1, 0, 0],
                                            [0, 0, 1, 0],
                                            [0, 0, 1, 1],
                                        ],
                                    },
                                },
                            },
                        },
                        {
                            "type": "sphere",
                            "name": "Ball",
                            "param": {
                                "radius": 0.5,
                                "sub_div": 4,
                                "transform": {
                                    "type": "trs",
                                    "param": {
                                        "t": [0, 0, 2],
                                        "s": [2, 1, 1],
                                    },
                                },
                            },
                        },
                        {"type": "cylinder", "name": "NotYetSupported"},
                    ],
                },
            }), encoding="utf-8")

            scene = FakeScene()
            loaded_paths = []
            call_order = scene._camera.call_order
            fake_editor = SimpleNamespace(
                CoronaEngine=SimpleNamespace(
                    active_project_path=str(root),
                    is_vision_available=lambda: True,
                    load_vision_scene=lambda path: (
                        call_order.append("load_vision_scene"),
                        loaded_paths.append(path),
                    ),
                )
            )
            fake_scene_manager = SimpleNamespace(get=lambda scene_name: scene)

            with patch.object(scene_tools_module, "CoronaEditor", fake_editor), \
                 patch.object(scene_tools_module, "scene_manager", fake_scene_manager), \
                 patch.object(scene_tools_module, "Actor", FakeActor):
                result = scene_tools_module.SceneTools.import_vision_scene_into_current_scene(
                    scene.route, str(vision_scene))

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["import_mode"], "external_live")
            self.assertTrue(result["camera_imported"])
            self.assertEqual(scene._camera.position, [4.0, 5.0, -6.0])
            self.assertEqual(scene._camera.forward, [0.0, 0.0, 1.0])
            self.assertAlmostEqual(scene._camera.fov, 57.29577951308232)
            self.assertEqual(result["proxy_actors_created"], 3)
            self.assertEqual(result["proxy_actors_reused"], 0)
            self.assertEqual(len(scene.get_actors()), 3)
            self.assertEqual(scene.get_actors()[0].name, "Chair")
            self.assertFalse(scene.get_actors()[0].physics_enabled)
            self.assertEqual(scene.get_actors()[0].position, [1.0, 2.0, -3.0])
            self.assertEqual(scene.get_actors()[0].scale, [2.0, 2.0, 2.0])
            self.assertEqual(scene.get_actors()[1].name, "Floor")
            self.assertFalse(scene.get_actors()[1].physics_enabled)
            self.assertEqual(scene.get_actors()[1].position, [0.0, 0.0, -1.0])
            self.assertEqual(scene.get_actors()[1].scale, [2.0, 2.0, 2.0])
            self.assertTrue(scene.get_actors()[1].route.startswith("Resource/vision_proxies/"))
            self.assertTrue((root / scene.get_actors()[1].route).exists())
            proxy_text = (root / scene.get_actors()[1].route).read_text(encoding="utf-8")
            self.assertIn("v 1 0 2", proxy_text)
            self.assertIn("f 1 2 3", proxy_text)
            self.assertEqual(scene.get_actors()[2].name, "Ball")
            self.assertFalse(scene.get_actors()[2].physics_enabled)
            self.assertEqual(scene.get_actors()[2].position, [0.0, 0.0, -2.0])
            self.assertEqual(scene.get_actors()[2].scale, [2.0, 2.0, 2.0])
            sphere_proxy_text = (root / scene.get_actors()[2].route).read_text(encoding="utf-8")
            self.assertIn("v 0 0.5 2", sphere_proxy_text)
            self.assertIn("f 1 3 2", sphere_proxy_text)
            self.assertEqual(scene.vision_import_mode, "external_live")
            self.assertEqual(scene.vision_bindings[0]["actor_guid"],
                             scene.get_actors()[0].actor_guid)
            self.assertEqual(scene.vision_bindings[0]["shape_guid"], "shape-chair")
            self.assertEqual(scene.vision_bindings[0]["json_path"], "/scene/shapes/0")
            self.assertEqual(scene.vision_bindings[1]["shape_type"], "quad")
            self.assertEqual(scene.vision_bindings[2]["shape_type"], "sphere")
            self.assertEqual(scene.vision_unsupported_shapes[0]["type"], "cylinder")
            self.assertEqual(scene.vision_unsupported_shapes[0]["reason"],
                             "unsupported_shape_type")
            self.assertEqual(loaded_paths, [str(vision_scene.resolve())])
            self.assertLess(call_order.index("load_vision_scene"),
                            call_order.index("set_render_backend:vision"))
            self.assertTrue(scene.saved)
            self.assertTrue(scene.tree_notified)


if __name__ == "__main__":
    unittest.main()
