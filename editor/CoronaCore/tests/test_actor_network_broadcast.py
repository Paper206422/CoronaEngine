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
        self.profiles = []

    def add_profile(self, profile):
        self.profiles.append(profile)
        return profile

    def remove_profile(self, profile):
        if profile in self.profiles:
            self.profiles.remove(profile)
        if self.active_profile is profile:
            self.active_profile = self.profiles[0] if self.profiles else None

    def set_active_profile(self, profile):
        self.active_profile = profile

    def get_active_profile(self):
        return self.active_profile

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
        self.visible = True
        self.metallic = 0.0
        self.roughness = 0.5

    def get_visible(self):
        return self.visible

    def set_visible(self, visible):
        self.visible = bool(visible)

    def get_metallic(self):
        return self.metallic

    def set_metallic(self, value):
        self.metallic = value

    def get_roughness(self):
        return self.roughness

    def set_roughness(self, value):
        self.roughness = value

    def to_dict(self):
        return {
            "visible": self.visible,
            "metallic": self.metallic,
            "roughness": self.roughness,
        }


class FakeComponent:
    def __init__(self, geometry):
        self.engine_obj = object()
        self.physics_enabled = True
        self.collision_enabled = True
        self.mass = 1.0
        self.restitution = 0.8
        self.damping = 0.99
        self.linear_lock = [False, False, False]
        self.angular_lock = [False, False, False]

    def set_collision_callback(self, callback):
        self.collision_callback = callback

    def set_on_move_callback(self, callback):
        self.on_move_callback = callback

    def set_physics_enabled(self, enabled):
        self.physics_enabled = enabled

    def get_physics_enabled(self):
        return self.physics_enabled

    def set_collision_enabled(self, enabled):
        self.collision_enabled = enabled

    def get_collision_enabled(self):
        return self.collision_enabled

    def set_mass(self, value):
        self.mass = value

    def get_mass(self):
        return self.mass

    def set_restitution(self, value):
        self.restitution = value

    def get_restitution(self):
        return self.restitution

    def set_damping(self, value):
        self.damping = value

    def get_damping(self):
        return self.damping

    def set_linear_lock(self, lock_x, lock_y, lock_z):
        self.linear_lock = [lock_x, lock_y, lock_z]

    def get_linear_lock(self):
        return self.linear_lock

    def set_angular_lock(self, lock_x, lock_y, lock_z):
        self.angular_lock = [lock_x, lock_y, lock_z]

    def get_angular_lock(self):
        return self.angular_lock

    def to_dict(self):
        return {
            "mass": self.mass,
            "restitution": self.restitution,
            "damping": self.damping,
            "physics_enabled": self.physics_enabled,
            "linear_lock": list(self.linear_lock),
            "angular_lock": list(self.angular_lock),
        }


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

    def test_set_model_replaces_profile_and_preserves_edit_state(self):
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
            old_profile = actor._profile
            old_geometry = actor._geometry

            actor.set_position([1.0, 2.0, 3.0])
            actor.set_rotation([10.0, 20.0, 30.0])
            actor.set_scale([2.0, 3.0, 4.0])
            actor.set_visible(False)
            actor._optics.set_metallic(0.7)
            actor._optics.set_roughness(0.2)
            actor.set_mass(5.5)
            actor.set_physics_enabled(False)
            actor.set_collision_enabled("none")

            actor.set_model("Resource/sphere.obj")

        self.assertEqual(actor.model_path, "Resource/sphere.obj")
        self.assertEqual(actor.final_model_path, "D:/project/test\\Resource/sphere.obj")
        self.assertIsNot(actor._profile, old_profile)
        self.assertIsNot(actor._geometry, old_geometry)
        self.assertEqual(actor.engine_obj.active_profile, actor._profile)
        self.assertEqual(actor.engine_obj.profiles, [actor._profile])
        self.assertEqual(actor._geometry.model_path, "D:/project/test\\Resource/sphere.obj")
        self.assertEqual(actor.get_position(), [1.0, 2.0, 3.0])
        self.assertEqual(actor.get_rotation(), [10.0, 20.0, 30.0])
        self.assertEqual(actor.get_scale(), [2.0, 3.0, 4.0])
        self.assertFalse(actor.get_visible())
        self.assertEqual(actor._optics.get_metallic(), 0.7)
        self.assertEqual(actor._optics.get_roughness(), 0.2)
        self.assertEqual(actor.get_mass(), 5.5)
        self.assertFalse(actor.get_physics_enabled())
        self.assertEqual(actor.get_collision_enabled(), "none")

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
            scene._main_camera = None
            scene.engine_scene = SimpleNamespace(
                add_camera=lambda camera: None,
                set_active_camera=lambda camera: None,
            )
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
            self.assertEqual(saved["terrain"]["path"], "")
            self.assertEqual(saved["terrain"]["type"], "")
            self.assertNotIn("vision", saved)

            actor_data = scene._build_actor_json(saved["actors"], "hud_quad")
            self.assertTrue(actor_data["follow_camera"])


if __name__ == "__main__":
    unittest.main()
