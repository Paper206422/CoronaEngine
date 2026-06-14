import configparser
import unittest
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from CoronaCore.core.entities import actor as actor_module
from CoronaCore.core.entities import scene as scene_module


class FakeActorEngineObject:
    def __init__(self):
        self.active_profile = None
        self.follow_camera = False

    def add_profile(self, profile):
        return profile

    def set_active_profile(self, profile):
        self.active_profile = profile

    def get_handle(self):
        return 1234

    def set_follow_camera(self, enabled):
        self.follow_camera = bool(enabled)

    def get_follow_camera(self):
        return self.follow_camera


class FakeGeometry:
    def __init__(self, model_path):
        self.engine_obj = object()
        self.model_path = model_path
        self.position = [0.0, 0.0, 0.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]

    def get_position(self):
        return self.position

    def set_position(self, position):
        self.position = position

    def get_rotation(self):
        return self.rotation

    def set_rotation(self, rotation):
        self.rotation = rotation

    def get_scale(self):
        return self.scale

    def set_scale(self, scale):
        self.scale = scale


class FakeOptics:
    def __init__(self, geometry):
        self.engine_obj = object()

    def get_visible(self):
        return True


class FakeComponent:
    def __init__(self, geometry):
        self.engine_obj = object()
        self.physics_enabled = True

    def set_collision_callback(self, callback):
        self.collision_callback = callback

    def set_on_move_callback(self, callback):
        self.on_move_callback = callback

    def set_physics_enabled(self, enabled):
        self.physics_enabled = enabled

    def get_physics_enabled(self):
        return self.physics_enabled


class ActorNetworkBroadcastTests(unittest.TestCase):
    def test_actor_create_broadcast_happens_after_handle_is_available(self):
        events = []
        fake_editor = SimpleNamespace(
            CoronaEngine=SimpleNamespace(
                active_project_path="D:/project/test",
                Actor=FakeActorEngineObject,
                ActorProfile=SimpleNamespace,
            ),
            js_call_func=lambda name, args: events.append((name, args)),
        )
        parent = SimpleNamespace(route="Scene/main.scene")

        with patch.object(actor_module, "CoronaEditor", fake_editor), \
             patch.object(actor_module, "CoronaEngine", fake_editor.CoronaEngine), \
             patch.object(actor_module, "Geometry", FakeGeometry), \
             patch.object(actor_module, "Optics", FakeOptics), \
             patch.object(actor_module, "Mechanics", FakeComponent), \
             patch.object(actor_module, "Acoustics", FakeComponent):
            actor_module.Actor(route="Resource/cube.obj",
                               actor_type="model",
                               parent_scene=parent)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "actor-sync-broadcast")
        actor_data = events[0][1][0]
        self.assertEqual(actor_data["handle"], 1234)
        self.assertTrue(actor_data["actor_guid"])
        self.assertEqual(actor_data["scene"], "Scene/main.scene")

    def test_external_model_path_is_copied_into_project_resource_before_broadcast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_root = root / "Project"
            external_root = root / "External"
            project_root.mkdir()
            external_root.mkdir()
            source_model = external_root / "Ball.obj"
            source_model.write_text("mtllib Ball.mtl\nmesh-data", encoding="utf-8")
            (external_root / "Ball.mtl").write_text(
                "map_Kd textures/Ball.png\n", encoding="utf-8")
            (external_root / "textures").mkdir()
            (external_root / "textures" / "Ball.png").write_bytes(b"png-data")

            events = []
            fake_editor = SimpleNamespace(
                CoronaEngine=SimpleNamespace(
                    active_project_path=str(project_root),
                    Actor=FakeActorEngineObject,
                    ActorProfile=SimpleNamespace,
                ),
                js_call_func=lambda name, args: events.append((name, args)),
            )
            parent = SimpleNamespace(route="Scene/main.scene")
            unsafe_route = "../External/Ball.obj"

            with patch.object(actor_module, "CoronaEditor", fake_editor), \
                 patch.object(actor_module, "CoronaEngine", fake_editor.CoronaEngine), \
                 patch.object(actor_module, "Geometry", FakeGeometry), \
                 patch.object(actor_module, "Optics", FakeOptics), \
                 patch.object(actor_module, "Mechanics", FakeComponent), \
                 patch.object(actor_module, "Acoustics", FakeComponent):
                actor_module.Actor(route=unsafe_route,
                                   actor_type="model",
                                   parent_scene=parent)

            actor_data = events[0][1][0]
            self.assertEqual(actor_data["path"], "Resource/Ball.obj")
            self.assertEqual(actor_data["model"], "Resource/Ball.obj")
            self.assertEqual(actor_data["scene"], "Scene/main.scene")
            self.assertEqual(actor_data["model_dependencies"], [
                "Resource/Ball.mtl",
                "Resource/textures/Ball.png",
            ])
            self.assertTrue((project_root / "Resource" / "Ball.obj").exists())
            self.assertEqual((project_root / "Resource" / "Ball.obj").read_text(encoding="utf-8"),
                             "mtllib Ball.mtl\nmesh-data")
            self.assertTrue((project_root / "Resource" / "Ball.mtl").exists())
            self.assertTrue((project_root / "Resource" / "textures" / "Ball.png").exists())

    def test_remote_actor_disables_local_physics(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            (project_root / "Resource").mkdir()
            (project_root / "Resource" / "cube.obj").write_text("mesh", encoding="utf-8")
            fake_editor = SimpleNamespace(
                CoronaEngine=SimpleNamespace(
                    active_project_path=str(project_root),
                    Actor=FakeActorEngineObject,
                    ActorProfile=SimpleNamespace,
                ),
                js_call_func=lambda name, args: None,
            )
            parent = SimpleNamespace(route="Scene/main.scene")

            with patch.object(actor_module, "CoronaEditor", fake_editor), \
                 patch.object(actor_module, "CoronaEngine", fake_editor.CoronaEngine), \
                 patch.object(actor_module, "Geometry", FakeGeometry), \
                 patch.object(actor_module, "Optics", FakeOptics), \
                 patch.object(actor_module, "Mechanics", FakeComponent), \
                 patch.object(actor_module, "Acoustics", FakeComponent):
                actor = actor_module.Actor(
                    route="Resource/cube.obj",
                    actor_type="model",
                    parent_scene=parent,
                    actor_data={
                        "actor_guid": "actor-remote",
                        "_suppress_network_broadcast": True,
                        "geometry": {
                            "position": [0, 0, 0],
                            "rotation": [0, 0, 0],
                            "scale": [1, 1, 1],
                        },
                    },
                )

            self.assertFalse(actor._mechanics.get_physics_enabled())

    def test_actor_move_emits_ownership_claim(self):
        events = []
        fake_editor = SimpleNamespace(
            CoronaEngine=SimpleNamespace(
                active_project_path="D:/project/test",
                Actor=FakeActorEngineObject,
                ActorProfile=SimpleNamespace,
            ),
            js_call_func=lambda name, args: events.append((name, args)),
        )
        parent = SimpleNamespace(route="Scene/main.scene", save_data=lambda: None)

        with patch.object(actor_module, "CoronaEditor", fake_editor), \
             patch.object(actor_module, "CoronaEngine", fake_editor.CoronaEngine), \
             patch.object(actor_module, "Geometry", FakeGeometry), \
             patch.object(actor_module, "Optics", FakeOptics), \
             patch.object(actor_module, "Mechanics", FakeComponent), \
             patch.object(actor_module, "Acoustics", FakeComponent):
            actor = actor_module.Actor(route="Resource/cube.obj",
                                       actor_type="model",
                                       parent_scene=parent)
            actor.on_move()

        claims = [args[0] for name, args in events if name == "actor-ownership-claim"]
        self.assertTrue(claims)
        self.assertEqual(claims[-1]["actor_guid"], actor.actor_guid)

    def test_follow_camera_round_trips_to_engine_and_to_dict(self):
        fake_editor = SimpleNamespace(
            CoronaEngine=SimpleNamespace(
                active_project_path="D:/project/test",
                Actor=FakeActorEngineObject,
                ActorProfile=SimpleNamespace,
            ),
            js_call_func=lambda name, args: None,
        )
        parent = SimpleNamespace(route="Scene/main.scene", save_data=lambda: None)

        with patch.object(actor_module, "CoronaEditor", fake_editor), \
             patch.object(actor_module, "CoronaEngine", fake_editor.CoronaEngine), \
             patch.object(actor_module, "Geometry", FakeGeometry), \
             patch.object(actor_module, "Optics", FakeOptics), \
             patch.object(actor_module, "Mechanics", FakeComponent), \
             patch.object(actor_module, "Acoustics", FakeComponent):
            actor = actor_module.Actor(route="Resource/cube.obj",
                                       actor_type="model",
                                       parent_scene=parent)

            self.assertFalse(actor.to_dict()["follow_camera"])

            actor.set_follow_camera(True)
            data = actor.to_dict()
            self.assertTrue(actor.engine_obj.get_follow_camera())
            self.assertTrue(data["follow_camera"])
            self.assertEqual(data["render_space"], "ui")

            actor.set_follow_camera(False)
            data = actor.to_dict()
            self.assertFalse(actor.engine_obj.get_follow_camera())
            self.assertFalse(data["follow_camera"])
            self.assertEqual(data["render_space"], "scene")

    def test_follow_camera_disables_physics_once_without_restore(self):
        fake_editor = SimpleNamespace(
            CoronaEngine=SimpleNamespace(
                active_project_path="D:/project/test",
                Actor=FakeActorEngineObject,
                ActorProfile=SimpleNamespace,
            ),
            js_call_func=lambda name, args: None,
        )
        parent = SimpleNamespace(route="Scene/main.scene", save_data=lambda: None)

        with patch.object(actor_module, "CoronaEditor", fake_editor), \
             patch.object(actor_module, "CoronaEngine", fake_editor.CoronaEngine), \
             patch.object(actor_module, "Geometry", FakeGeometry), \
             patch.object(actor_module, "Optics", FakeOptics), \
             patch.object(actor_module, "Mechanics", FakeComponent), \
             patch.object(actor_module, "Acoustics", FakeComponent):
            actor = actor_module.Actor(route="Resource/cube.obj",
                                       actor_type="model",
                                       parent_scene=parent)

            self.assertTrue(actor.get_physics_enabled())

            actor.set_follow_camera(True)
            self.assertTrue(actor.get_follow_camera())
            self.assertFalse(actor.get_physics_enabled())

            actor.set_follow_camera(False)
            self.assertFalse(actor.get_follow_camera())
            self.assertFalse(actor.get_physics_enabled())

            actor.set_physics_enabled(True)
            actor.set_follow_camera(True, if_init=True)
            self.assertTrue(actor.get_follow_camera())
            self.assertTrue(actor.get_physics_enabled())

    def test_scene_actor_follow_camera_persists_in_scene_actor_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = Path(tmp) / "main.scene"
            scene = scene_module.Scene.__new__(scene_module.Scene)
            scene.route = str(scene_path)
            scene.name = "main"
            scene.file_data = configparser.ConfigParser()
            scene._environment = None
            scene._cameras = []
            scene.script_path = ""
            scene.terrain_path = ""
            scene._actors = [
                SimpleNamespace(
                    name="hud_quad",
                    actor_type="model",
                    route="Resource/hud.obj",
                    _geometry=True,
                    get_position=lambda: [0.0, 0.0, 2.0],
                    get_rotation=lambda: [0.0, 0.0, 0.0],
                    get_scale=lambda: [1.0, 1.0, 1.0],
                    get_follow_camera=lambda: True,
                )
            ]

            scene.save_data()

            saved = configparser.ConfigParser()
            saved.read(scene_path, encoding="utf-8")
            self.assertTrue(saved["actors"].getboolean("hud_quad.follow_camera"))

            actor_data = scene._build_actor_json(saved["actors"], "hud_quad")
            self.assertTrue(actor_data["follow_camera"])


if __name__ == "__main__":
    unittest.main()
