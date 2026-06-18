import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from plugins.SceneTools import main as scene_tools_main


class FakeActor:
    def __init__(self, name, *, guid=None, route=None):
        self.name = name
        self.route = route or f"models/{name}.obj"
        self.model_path = self.route
        self.model_dependencies = []
        self.actor_type = "model"
        self.actor_guid = guid or f"guid-{name}"
        self.position = [0.0, 0.0, 0.0]
        self.rotation = [0.0, 0.0, 0.0]
        self.scale = [1.0, 1.0, 1.0]
        self.visible = True
        self.follow_camera = False
        self.network_remote = False
        self._suppress_network_broadcast = False

    def get_position(self):
        return list(self.position)

    def set_position(self, position, if_init=False):
        self.position = list(position)

    def get_rotation(self):
        return list(self.rotation)

    def set_rotation(self, rotation, if_init=False):
        self.rotation = list(rotation)

    def get_scale(self):
        return list(self.scale)

    def set_scale(self, scale, if_init=False):
        self.scale = list(scale)

    def get_visible(self):
        return self.visible

    def set_visible(self, visible):
        self.visible = bool(visible)

    def get_follow_camera(self):
        return self.follow_camera

    def set_follow_camera(self, enabled, if_init=False):
        self.follow_camera = bool(enabled)

    def to_dict(self):
        return {
            "name": self.name,
            "path": self.route,
            "model": self.model_path,
            "model_dependencies": list(self.model_dependencies),
            "type": self.actor_type,
            "actor_type": self.actor_type,
            "actor_guid": self.actor_guid,
            "visible": self.visible,
            "follow_camera": self.follow_camera,
            "geometry": {
                "position": list(self.position),
                "rotation": list(self.rotation),
                "scale": list(self.scale),
            },
        }


class FakeScene:
    def __init__(self, actors):
        self.route = "Demo.scene"
        self._actors = actors
        self.saved = False
        self.notified = False

    def get_actors(self):
        return self._actors

    def find_actor(self, name):
        return next(
            (actor for actor in self._actors
             if actor.name == name or actor.actor_guid == name),
            None,
        )

    def save_data(self):
        self.saved = True

    def _notify_scene_tree_changed(self):
        self.notified = True

    def add_actor(self, actor, *_args, **_kwargs):
        self._actors.append(actor)


class FakeSceneManager:
    def __init__(self, scene):
        self.scene = scene

    def get(self, scene_name):
        return self.scene if scene_name == self.scene.route else None


class ActorAliasRenameTests(unittest.TestCase):
    def test_rename_actor_updates_alias_and_refreshes_scene_tree(self):
        actor = FakeActor("chair")
        scene = FakeScene([actor])

        with patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)):
            result = scene_tools_main.SceneTools.rename_actor("Demo.scene", "chair", "Display Chair")

        self.assertEqual(result["status"], "success")
        self.assertEqual(actor.name, "Display Chair")
        self.assertTrue(scene.saved)
        self.assertTrue(scene.notified)
        self.assertEqual(result["actor"]["name"], "Display Chair")
        self.assertEqual(result["old_name"], "chair")
        self.assertEqual(result["new_name"], "Display Chair")

    def test_rename_actor_rejects_duplicate_aliases(self):
        scene = FakeScene([FakeActor("chair"), FakeActor("table")])

        with patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)):
            result = scene_tools_main.SceneTools.rename_actor("Demo.scene", "chair", "table")

        self.assertEqual(result["status"], "error")
        self.assertIn("already exists", result["message"])
        self.assertFalse(scene.saved)
        self.assertFalse(scene.notified)

    def test_get_actor_sync_snapshot_exports_alias_and_basic_state(self):
        actor = FakeActor("Display Chair", guid="actor-chair", route="Resource/chair.obj")
        actor.position = [1.0, 2.0, 3.0]
        actor.rotation = [0.1, 0.2, 0.3]
        actor.scale = [2.0, 2.0, 2.0]
        actor.visible = False
        actor.follow_camera = True
        scene = FakeScene([actor])

        with patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)):
            result = scene_tools_main.SceneTools.get_actor_sync_snapshot("Demo.scene")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["scene"], "Demo.scene")
        self.assertEqual(len(result["actors"]), 1)
        snapshot_actor = result["actors"][0]
        self.assertEqual(snapshot_actor["actor_guid"], "actor-chair")
        self.assertEqual(snapshot_actor["name"], "Display Chair")
        self.assertEqual(snapshot_actor["path"], "Resource/chair.obj")
        self.assertEqual(snapshot_actor["geometry"]["position"], [1.0, 2.0, 3.0])
        self.assertEqual(snapshot_actor["geometry"]["rotation"], [0.1, 0.2, 0.3])
        self.assertEqual(snapshot_actor["geometry"]["scale"], [2.0, 2.0, 2.0])
        self.assertFalse(snapshot_actor["visible"])
        self.assertTrue(snapshot_actor["follow_camera"])

    def test_apply_actor_state_internal_updates_by_guid_not_alias(self):
        actor = FakeActor("Local Chair", guid="actor-chair")
        extra = FakeActor("Local Only", guid="actor-local")
        scene = FakeScene([actor, extra])

        with patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)):
            result = scene_tools_main.SceneTools.apply_actor_state_internal(
                "Demo.scene",
                "actor-chair",
                {
                    "name": "Host Chair",
                    "visible": False,
                    "follow_camera": True,
                    "geometry": {
                        "position": [4.0, 5.0, 6.0],
                        "rotation": [0.4, 0.5, 0.6],
                        "scale": [3.0, 3.0, 3.0],
                    },
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(actor.name, "Host Chair")
        self.assertEqual(actor.position, [4.0, 5.0, 6.0])
        self.assertEqual(actor.rotation, [0.4, 0.5, 0.6])
        self.assertEqual(actor.scale, [3.0, 3.0, 3.0])
        self.assertFalse(actor.visible)
        self.assertTrue(actor.follow_camera)
        self.assertIn(extra, scene.get_actors())
        self.assertTrue(scene.saved)

    def test_apply_actor_state_internal_restores_network_broadcast_flags(self):
        actor = FakeActor("Local Chair", guid="actor-chair")
        scene = FakeScene([actor])

        with patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)):
            result = scene_tools_main.SceneTools.apply_actor_state_internal(
                "Demo.scene",
                "actor-chair",
                {
                    "name": "Host Chair",
                    "geometry": {"position": [1.0, 2.0, 3.0]},
                },
            )

        self.assertEqual(result["status"], "success")
        self.assertFalse(actor.network_remote)
        self.assertFalse(actor._suppress_network_broadcast)

    def test_create_actor_internal_clears_remote_suppress_flags_after_creation(self):
        scene = FakeScene([])

        def fake_actor_factory(route, source_index, actor_type, parent_scene, actor_data):
            actor = FakeActor(
                actor_data.get("name", "Remote Chair"),
                guid=actor_data.get("actor_guid"),
                route=route,
            )
            actor.network_remote = bool(actor_data.get("_suppress_network_broadcast"))
            actor._suppress_network_broadcast = bool(actor_data.get("_suppress_network_broadcast"))
            return actor

        with (
            patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)),
            patch.object(scene_tools_main, "Actor", side_effect=fake_actor_factory),
        ):
            result = scene_tools_main.SceneTools.create_actor_internal(
                "Demo.scene",
                "Resource/chair.obj",
                "model",
                {
                    "actor_guid": "actor-chair",
                    "name": "Remote Chair",
                    "_suppress_network_broadcast": True,
                },
            )

        self.assertIn("actor", result)
        actor = scene.get_actors()[0]
        self.assertEqual(actor.name, "Remote Chair")
        self.assertFalse(actor.network_remote)
        self.assertFalse(actor._suppress_network_broadcast)

    def test_apply_actor_sync_snapshot_reports_unchanged_on_repeat_snapshot(self):
        scene = FakeScene([])

        def fake_actor_factory(route, source_index, actor_type, parent_scene, actor_data):
            actor = FakeActor(
                actor_data.get("name", Path(route).stem),
                guid=actor_data.get("actor_guid"),
                route=route,
            )
            geometry = actor_data.get("geometry", {})
            actor.position = list(geometry.get("position", actor.position))
            actor.rotation = list(geometry.get("rotation", actor.rotation))
            actor.scale = list(geometry.get("scale", actor.scale))
            actor.visible = actor_data.get("visible", actor.visible)
            actor.follow_camera = actor_data.get("follow_camera", actor.follow_camera)
            return actor

        snapshot = {
            "actors": [
                {
                    "actor_guid": f"actor-{index}",
                    "name": f"Actor {index}",
                    "actor_type": "model",
                    "path": f"Resource/model_{index}.obj",
                    "model": f"Resource/model_{index}.obj",
                    "model_dependencies": [],
                    "visible": True,
                    "follow_camera": False,
                    "geometry": {
                        "position": [float(index), 0.0, 0.0],
                        "rotation": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                }
                for index in range(3)
            ],
        }

        with (
            patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)),
            patch.object(scene_tools_main, "Actor", side_effect=fake_actor_factory),
        ):
            first = scene_tools_main.SceneTools.apply_actor_sync_snapshot_internal(
                "Demo.scene", snapshot)
            second = scene_tools_main.SceneTools.apply_actor_sync_snapshot_internal(
                "Demo.scene", snapshot)

        self.assertEqual(first["status"], "success")
        self.assertEqual(len(first["created"]), 3)
        self.assertEqual(len(first["updated"]), 0)
        self.assertEqual(first.get("unchanged"), [])
        self.assertEqual(second["status"], "success")
        self.assertEqual(len(second["created"]), 0)
        self.assertEqual(len(second["updated"]), 0)
        self.assertEqual(len(second["unchanged"]), 3)

    def test_get_actor_sync_snapshot_uses_network_sync_policy(self):
        normal = FakeActor("chair", guid="actor-chair", route="Resource/chair.obj")
        config_actor = FakeActor("config", guid="actor-config", route="Resource/config.actor")
        config_actor.actor_type = "actor"
        internal = FakeActor("__six_view_tmp", guid="actor-internal", route="Resource/tmp.obj")
        framework = FakeActor("__room_box", guid="actor-room", route="Resource/room.obj")
        scene = FakeScene([normal, config_actor, internal, framework])

        with patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)):
            snapshot = scene_tools_main.SceneTools.get_actor_sync_snapshot("Demo.scene")

        self.assertEqual(snapshot["status"], "success")
        self.assertEqual(
            [actor["actor_guid"] for actor in snapshot["actors"]],
            ["actor-chair", "actor-room"],
        )

    def test_apply_actor_sync_snapshot_warns_and_skips_filtered_actor(self):
        scene = FakeScene([])
        snapshot = {
            "actors": [
                {
                    "actor_guid": "actor-config",
                    "name": "Config Actor",
                    "actor_type": "actor",
                    "path": "Resource/config.actor",
                    "model": "Resource/config.actor",
                    "model_dependencies": [],
                    "visible": True,
                    "follow_camera": False,
                    "geometry": {
                        "position": [0.0, 0.0, 0.0],
                        "rotation": [0.0, 0.0, 0.0],
                        "scale": [1.0, 1.0, 1.0],
                    },
                },
            ],
        }

        with patch.object(scene_tools_main, "scene_manager", FakeSceneManager(scene)):
            result = scene_tools_main.SceneTools.apply_actor_sync_snapshot_internal(
                "Demo.scene", snapshot)

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["created"], [])
        self.assertEqual(scene.get_actors(), [])
        self.assertEqual(result["warnings"][0]["code"], "actor_type_actor")
        self.assertEqual(result["warnings"][0]["actor_guid"], "actor-config")


if __name__ == "__main__":
    unittest.main()
