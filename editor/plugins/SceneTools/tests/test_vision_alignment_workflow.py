import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from plugins.SceneTools import main as scene_tools_main
from plugins.SceneTools.vision_import import extract_vision_actor_imports


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "vision_alignment"
VISION_SCENE = FIXTURE_DIR / "vision_scene.json"
REPLACEMENT_MODEL = FIXTURE_DIR / "replacement.obj"


class FakeOptics:
    def __init__(self):
        self.values = {"visible": True}

    def __getattr__(self, name):
        if name.startswith("set_"):
            key = name[4:]

            def setter(value):
                self.values[key] = value

            return setter
        raise AttributeError(name)


class FakeImportedActor:
    def __init__(self, name, route, actor_type, parent_scene, actor_data):
        self.name = name
        self.route = route
        self.actor_type = actor_type
        self.parent = parent_scene
        self.actor_guid = actor_data["actor_guid"]
        geometry = actor_data.get("geometry") or {}
        self.position = list(geometry.get("position", [0.0, 0.0, 0.0]))
        self.rotation = list(geometry.get("rotation", [0.0, 0.0, 0.0]))
        self.scale = list(geometry.get("scale", [1.0, 1.0, 1.0]))
        self._optics = FakeOptics()
        self.engine_obj = SimpleNamespace(handle=self.actor_guid)

    def set_position(self, position):
        self.position = list(position)

    def set_rotation(self, rotation):
        self.rotation = list(rotation)

    def set_scale(self, scale):
        self.scale = list(scale)

    def translate(self, delta):
        self.position = [self.position[i] + delta[i] for i in range(3)]

    def rotate_delta(self, delta):
        self.rotation = [self.rotation[i] + delta[i] for i in range(3)]

    def scale_delta(self, factor):
        self.scale = [self.scale[i] * factor[i] for i in range(3)]

    def set_model(self, route):
        self.route = route

    def set_visible(self, visible):
        self._optics.values["visible"] = bool(visible)

    def to_dict(self):
        return {
            "name": self.name,
            "actor_guid": self.actor_guid,
            "path": self.route,
            "actor_type": self.actor_type,
            "geometry": {
                "position": list(self.position),
                "rotation": list(self.rotation),
                "scale": list(self.scale),
            },
            "visible": self._optics.values.get("visible", True),
            "optics": dict(self._optics.values),
        }


class FakeCamera:
    camera_id = "main-camera"
    name = "MainCamera"
    engine_obj = object()

    def set_render_backend(self, mode):
        self.render_backend = mode

    def to_dict(self):
        return {"name": self.name, "render_backend": getattr(self, "render_backend", "native")}


class FakeAlignmentScene:
    def __init__(self):
        self.route = "Scene/alignment.scene"
        self.file_data = {}
        self._actors = []
        self.removed_actors = []
        self._main_camera = FakeCamera()
        self.engine_scene = SimpleNamespace(set_active_camera=lambda camera: None)
        self.saved_snapshots = []
        self.notified = False

    def ensure_default_camera(self):
        return None

    def get_active_camera(self):
        return self._main_camera

    def set_camera(self, position, forward, up, fov, camera_id):
        self.camera_pose = {
            "position": position,
            "forward": forward,
            "up": up,
            "fov": fov,
            "camera_id": camera_id,
        }

    def get_actors(self):
        return list(self._actors)

    def add_actor(self, actor):
        existing_names = {existing.name for existing in self._actors}
        base_name = actor.name
        suffix = 1
        while actor.name in existing_names:
            actor.name = f"{base_name}_{suffix}"
            suffix += 1
        self._actors.append(actor)

    def remove_actor(self, actor):
        self.removed_actors.append(actor)
        self._actors.remove(actor)

    def save_data(self):
        self.saved_snapshots.append({
            "vision": {
                "source_path": getattr(self, "vision_source_path", ""),
                "import_mode": getattr(self, "vision_import_mode", ""),
            },
            "actors": [actor.to_dict() for actor in self._actors],
        })

    def _notify_scene_tree_changed(self):
        self.notified = True


class VisionAlignmentWorkflowTests(unittest.TestCase):
    def test_fixture_covers_alignment_cases(self):
        with VISION_SCENE.open("r", encoding="utf-8") as f:
            document = json.load(f)

        result = extract_vision_actor_imports(document, str(VISION_SCENE))

        self.assertEqual(len(result["actors"]), 2)
        self.assertEqual(len(result["unsupported_shapes"]), 2)
        self.assertEqual(
            [shape["reason"] for shape in result["unsupported_shapes"]],
            ["unsupported_shape_type", "unsupported_shape_type"],
        )
        self.assertEqual(result["actors"][0]["name"], "AlignedModel")
        self.assertEqual(result["actors"][1]["name"], "AlignedModel")
        self.assertEqual(result["actors"][0]["geometry"]["position"], [1.0, 2.0, -3.0])
        self.assertEqual(result["actors"][0]["geometry"]["scale"], [1.0, 2.0, 3.0])
        self.assertEqual(result["actors"][1]["geometry"]["position"], [-1.0, 0.5, -2.0])
        self.assertEqual(result["actors"][1]["geometry"]["scale"], [0.5, 0.75, 1.25])
        self.assertEqual(result["actors"][0]["optics"]["diffuse"], [0.25, 0.5, 0.75])
        self.assertEqual(result["actors"][0]["optics"]["roughness"], 0.65)
        self.assertEqual(result["actors"][0]["optics"]["metallic"], 0.35)
        self.assertEqual(result["actors"][0]["optics"]["clearcoat"], 0.4)
        self.assertEqual(result["actors"][0]["optics"]["clearcoat_gloss"], 0.8)

    def test_external_import_then_native_edits_stay_on_engine_built_source(self):
        scene = FakeAlignmentScene()
        load_requests = []
        fake_editor = SimpleNamespace(
            CoronaEngine=SimpleNamespace(
                is_vision_available=lambda: True,
                load_vision_scene=lambda path: load_requests.append(path),
            )
        )

        with patch.object(scene_tools_main, "CoronaEditor", fake_editor), \
             patch.object(scene_tools_main, "Actor", FakeImportedActor), \
             patch.object(scene_tools_main.scene_manager, "get", lambda name: scene):
            first = scene_tools_main.SceneTools.import_vision_scene_into_current_scene(
                scene.route,
                str(VISION_SCENE),
            )
            first_actor_ids = [id(actor) for actor in scene.get_actors()]
            second = scene_tools_main.SceneTools.import_vision_scene_into_current_scene(
                scene.route,
                str(VISION_SCENE),
            )
            second_actor_ids = [id(actor) for actor in scene.get_actors()]

        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "success")
        self.assertEqual(second["import_mode"], "engine_built")
        self.assertEqual(second["imported_actor_count"], 2)
        self.assertEqual(load_requests, [])
        self.assertEqual(scene.vision_import_mode, "engine_built")
        self.assertEqual([actor.name for actor in scene.get_actors()], ["AlignedModel", "AlignedModel_1"])
        self.assertEqual(len(scene.get_actors()), 2)
        self.assertEqual(first_actor_ids, second_actor_ids)
        self.assertEqual(scene.removed_actors, [])
        self.assertTrue(scene.notified)

        actor = scene.get_actors()[0]
        actor.set_position([10.0, 20.0, 30.0])
        actor.set_rotation([5.0, 15.0, 25.0])
        actor.set_scale([2.0, 2.5, 3.0])
        actor.set_visible(False)
        actor.set_model(str(REPLACEMENT_MODEL.resolve()))
        scene.remove_actor(scene.get_actors()[1])
        scene.save_data()

        snapshot = scene.saved_snapshots[-1]
        self.assertEqual(snapshot["vision"]["import_mode"], "engine_built")
        self.assertEqual(snapshot["vision"]["source_path"], str(VISION_SCENE.resolve()))
        self.assertEqual(len(snapshot["actors"]), 1)
        saved_actor = snapshot["actors"][0]
        self.assertTrue(saved_actor["actor_guid"].endswith("#scene.shapes[0]"))
        self.assertEqual(saved_actor["path"], str(REPLACEMENT_MODEL.resolve()))
        self.assertEqual(saved_actor["geometry"]["position"], [10.0, 20.0, 30.0])
        self.assertEqual(saved_actor["geometry"]["rotation"], [5.0, 15.0, 25.0])
        self.assertEqual(saved_actor["geometry"]["scale"], [2.0, 2.5, 3.0])
        self.assertFalse(saved_actor["visible"])
        self.assertFalse(saved_actor["optics"]["visible"])


if __name__ == "__main__":
    unittest.main()
