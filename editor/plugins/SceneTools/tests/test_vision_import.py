import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from plugins.SceneTools import main as scene_tools_main
from plugins.SceneTools.vision_import import extract_vision_actor_imports


class VisionImportTests(unittest.TestCase):
    def test_extracts_model_shape_as_corona_actor_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "asset.obj"
            model.write_text("# obj", encoding="utf-8")
            scene_path = root / "vision_scene.json"
            document = {
                "scene": {
                    "materials": [
                        {
                            "type": "principled_bsdf",
                            "name": "mat",
                            "param": {
                                "color": {
                                    "node": {"param": {"value": [0.2, 0.3, 0.4]}}
                                },
                                "roughness": {"node": {"param": {"value": 0.7}}},
                                "metallic": {"node": {"param": {"value": 0.6}}},
                                "coat_roughness": {"node": {"param": {"value": 0.25}}},
                            },
                        }
                    ],
                    "shapes": [
                        {
                            "type": "model",
                            "name": "Imported.Box",
                            "param": {
                                "fn": "asset.obj",
                                "material": "mat",
                                "transform": {
                                    "type": "matrix4x4",
                                    "param": {
                                        "matrix4x4": [
                                            [2.0, 0.0, 0.0, 0.0],
                                            [0.0, 3.0, 0.0, 0.0],
                                            [0.0, 0.0, 4.0, 0.0],
                                            [1.0, 2.0, 3.0, 1.0],
                                        ]
                                    },
                                },
                            },
                        }
                    ],
                }
            }
            scene_path.write_text(json.dumps(document), encoding="utf-8")

            result = extract_vision_actor_imports(document, str(scene_path))

        self.assertEqual(result["unsupported_shapes"], [])
        self.assertEqual(len(result["actors"]), 1)
        actor = result["actors"][0]
        self.assertEqual(actor["name"], "Imported_Box")
        self.assertEqual(actor["route"], str(model.resolve()))
        self.assertTrue(actor["actor_guid"].endswith("#scene.shapes[0]"))
        self.assertEqual(actor["geometry"]["position"], [1.0, 2.0, -3.0])
        self.assertEqual(actor["geometry"]["scale"], [2.0, 3.0, 4.0])
        self.assertEqual(actor["optics"]["diffuse"], [0.2, 0.3, 0.4])
        self.assertEqual(actor["optics"]["roughness"], 0.7)
        self.assertEqual(actor["optics"]["metallic"], 0.6)
        self.assertEqual(actor["optics"]["clearcoat_gloss"], 0.75)

    def test_reports_unsupported_primitives_and_missing_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = Path(tmp) / "vision_scene.json"
            document = {
                "scene": {
                    "shapes": [
                        {"type": "quad", "name": "floor", "param": {}},
                        {"type": "model", "name": "missing", "param": {"fn": "missing.obj"}},
                    ]
                }
            }
            scene_path.write_text(json.dumps(document), encoding="utf-8")

            result = extract_vision_actor_imports(document, str(scene_path))

        self.assertEqual(result["actors"], [])
        self.assertEqual(
            [shape["reason"] for shape in result["unsupported_shapes"]],
            ["unsupported_shape_type", "model_file_not_found"],
        )

    def test_trs_transform_uses_corona_z_flip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "asset.glb").write_bytes(b"glb")
            scene_path = root / "vision_scene.json"
            document = {
                "scene": {
                    "shapes": [
                        {
                            "type": "model",
                            "param": {
                                "fn": "asset.glb",
                                "transform": {
                                    "type": "trs",
                                    "param": {"t": [1, 2, 3], "s": [4, 5, 6]},
                                },
                            },
                        }
                    ]
                }
            }

            result = extract_vision_actor_imports(document, str(scene_path))

        actor = result["actors"][0]
        self.assertEqual(actor["geometry"]["position"], [1.0, 2.0, -3.0])
        self.assertEqual(actor["geometry"]["scale"], [4.0, 5.0, 6.0])

    def test_scene_tools_import_switches_external_json_to_engine_built_actors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "asset.obj"
            model.write_text("# obj", encoding="utf-8")
            scene_path = root / "vision_scene.json"
            document = {
                "scene": {
                    "camera": {
                        "param": {
                            "name": "VisionCam",
                            "fov_y": 45,
                            "transform": {
                                "type": "look_at",
                                "param": {
                                    "position": [0, 1, 2],
                                    "target_pos": [0, 1, 0],
                                    "up": [0, 1, 0],
                                },
                            },
                        }
                    },
                    "shapes": [
                        {
                            "type": "model",
                            "name": "asset",
                            "param": {"fn": "asset.obj"},
                        },
                        {
                            "type": "cube",
                            "name": "primitive",
                            "param": {},
                        },
                    ],
                }
            }
            scene_path.write_text(json.dumps(document), encoding="utf-8")

            load_requests = []
            added_actors = []

            class FakeCamera:
                camera_id = "cam0"
                name = "Main"

                def set_render_backend(self, mode):
                    self.render_backend = mode

                def to_dict(self):
                    return {"name": self.name}

            class FakeScene:
                route = "Scene/main.scene"

                def __init__(self):
                    self.file_data = {}
                    self.vision_source_path = ""
                    self.vision_import_mode = ""
                    self.engine_scene = SimpleNamespace(set_active_camera=lambda camera: None)
                    self.active_camera = FakeCamera()

                def ensure_default_camera(self):
                    return None

                def get_active_camera(self):
                    return self.active_camera

                def set_camera(self, position, forward, up, fov, camera_id):
                    self.camera_pose = (position, forward, up, fov, camera_id)

                def get_actors(self):
                    return []

                def add_actor(self, actor):
                    added_actors.append(actor)

                def save_data(self):
                    self.saved = True

                def _notify_scene_tree_changed(self):
                    self.notified = True

            class FakeActor:
                def __init__(self, name, route, actor_type, parent_scene, actor_data):
                    self.name = name
                    self.route = route
                    self.actor_type = actor_type
                    self.parent = parent_scene
                    self.actor_guid = actor_data["actor_guid"]
                    self._optics = SimpleNamespace()

                def to_dict(self):
                    return {"name": self.name, "actor_guid": self.actor_guid}

            fake_scene = FakeScene()
            fake_editor = SimpleNamespace(
                CoronaEngine=SimpleNamespace(
                    is_vision_available=lambda: True,
                    load_vision_scene=lambda path: load_requests.append(path),
                )
            )

            with patch.object(scene_tools_main, "CoronaEditor", fake_editor), \
                 patch.object(scene_tools_main, "Actor", FakeActor), \
                 patch.object(scene_tools_main.scene_manager, "get", lambda name: fake_scene):
                result = scene_tools_main.SceneTools.import_vision_scene_into_current_scene(
                    "Scene/main.scene",
                    str(scene_path),
                )

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["import_mode"], "engine_built")
        self.assertEqual(result["imported_actor_count"], 1)
        self.assertEqual(result["unsupported_shapes"][0]["reason"], "unsupported_shape_type")
        self.assertEqual(load_requests, [])
        self.assertEqual(fake_scene.vision_import_mode, "engine_built")
        self.assertTrue(fake_scene.saved)
        self.assertTrue(fake_scene.notified)
        self.assertEqual(len(added_actors), 1)
        self.assertTrue(added_actors[0].actor_guid.endswith("#scene.shapes[0]"))


if __name__ == "__main__":
    unittest.main()
