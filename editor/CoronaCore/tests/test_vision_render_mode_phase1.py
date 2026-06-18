import configparser
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from CoronaCore.core.entities import camera as camera_module
from CoronaCore.core.entities import scene as scene_module
from plugins.SceneTools import main as scene_tools_module


class FakeEngineCamera:
    _next_handle = 1

    def __init__(self, position=None, forward=None, world_up=None, fov=None):
        self.position = list(position or [0.0, 0.0, -5.0])
        self.forward = list(forward or [0.0, 0.0, 1.0])
        self.world_up = list(world_up or [0.0, 1.0, 0.0])
        self.fov = float(fov) if fov is not None else 45.0
        self.width = 1920
        self.height = 1080
        self.output_mode = "final_color"
        self.render_backend = "native"
        self.vision_render_mode = "path_tracing"
        self.view_state = (False, 120, 120, 960, 540, 1.0)
        self.surface = 0
        self.handle = FakeEngineCamera._next_handle
        FakeEngineCamera._next_handle += 1

    def set(self, position, forward, world_up, fov):
        self.position = list(position)
        self.forward = list(forward)
        self.world_up = list(world_up)
        self.fov = float(fov)

    def get_position(self):
        return list(self.position)

    def get_forward(self):
        return list(self.forward)

    def get_world_up(self):
        return list(self.world_up)

    def get_fov(self):
        return self.fov

    def set_size(self, width, height):
        self.width = int(width)
        self.height = int(height)

    def get_size(self):
        return [self.width, self.height]

    def set_output_mode(self, mode):
        self.output_mode = mode

    def set_render_backend(self, mode):
        self.render_backend = mode

    def set_vision_render_mode(self, mode):
        self.vision_render_mode = mode

    def get_vision_render_mode(self):
        return self.vision_render_mode

    def set_view_state(self, open_, x, y, width, height, move_speed):
        self.view_state = (bool(open_), int(x), int(y), int(width), int(height), float(move_speed))

    def set_surface(self, surface):
        self.surface = int(surface)

    def get_surface(self):
        return self.surface

    def get_handle(self):
        return self.handle


class FakeEngineScene:
    def __init__(self):
        self.cameras = []
        self.active_camera = None
        self.simulation_enabled = False

    def add_camera(self, camera):
        self.cameras.append(camera)

    def remove_camera(self, camera):
        self.cameras.remove(camera)

    def set_active_camera(self, camera):
        self.active_camera = camera

    def set_environment(self, environment):
        self.environment = environment

    def set_simulation_enabled(self, enabled):
        self.simulation_enabled = bool(enabled)


class FakeEnvironment:
    def __init__(self, name="Environment"):
        self.name = name
        self.engine_obj = object()
        self.sun_direction = [0.0, -1.0, 0.0]
        self.floor_grid = True

    def set_sun_direction(self, direction):
        self.sun_direction = list(direction)

    def get_sun_direction(self):
        return list(self.sun_direction)

    def set_floor_grid(self, enabled):
        self.floor_grid = bool(enabled)

    def get_floor_grid(self):
        return self.floor_grid


class VisionRenderModePhase1Tests(unittest.TestCase):
    def _fake_engine(self):
        return SimpleNamespace(
            active_project_path="",
            Camera=FakeEngineCamera,
            Scene=FakeEngineScene,
            is_vision_available=lambda: True,
        )

    def _patch_engine(self, fake_engine):
        return (
            patch.object(camera_module, "CoronaEngine", fake_engine),
            patch.object(scene_module, "CoronaEngine", fake_engine),
            patch.object(scene_module, "Environment", FakeEnvironment),
        )

    def test_camera_normalizes_and_serializes_vision_render_mode(self):
        fake_engine = self._fake_engine()
        with patch.object(camera_module, "CoronaEngine", fake_engine):
            camera = camera_module.Camera()

            self.assertEqual(camera.get_vision_render_mode(), "path_tracing")
            camera.set_vision_render_mode("SVGF")

            self.assertEqual(camera.get_vision_render_mode(), "svgf")
            self.assertEqual(camera.engine_obj.get_vision_render_mode(), "svgf")
            self.assertEqual(camera.to_dict()["vision_render_mode"], "svgf")
            with self.assertRaises(ValueError):
                camera.set_vision_render_mode("oidn")

    def test_camera_constructor_syncs_vision_render_mode_to_engine(self):
        fake_engine = self._fake_engine()
        with patch.object(camera_module, "CoronaEngine", fake_engine):
            camera = camera_module.Camera(render_backend="vision", vision_render_mode="SSAT")

            self.assertEqual(camera.get_vision_render_mode(), "ssat")
            self.assertEqual(camera.engine_obj.get_vision_render_mode(), "ssat")

    def test_scene_save_and_load_preserves_per_camera_vision_render_modes(self):
        fake_engine = self._fake_engine()
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = Path(tmp) / "multi_camera.scene"
            scene_path.write_text("", encoding="utf-8")

            patches = self._patch_engine(fake_engine)
            with patches[0], patches[1], patches[2]:
                scene = scene_module.Scene(str(scene_path))
                main_camera = scene.get_active_camera()
                main_camera.set_render_backend("vision")
                main_camera.set_vision_render_mode("ssat")

                second_camera = camera_module.Camera(name="Preview", render_backend="vision",
                                                     vision_render_mode="svgf")
                scene.add_camera_to_scene(second_camera)
                scene.save_data()

                saved = configparser.ConfigParser()
                saved.read(scene_path, encoding="utf-8")
                self.assertEqual(saved["camera"]["camera0.vision_render_mode"], "ssat")
                self.assertEqual(saved["camera"]["camera1.vision_render_mode"], "svgf")

                reloaded = scene_module.Scene(str(scene_path))
                cameras = reloaded.get_cameras()

            self.assertEqual(cameras[0].get_vision_render_mode(), "ssat")
            self.assertEqual(cameras[1].get_vision_render_mode(), "svgf")

    def test_scene_tools_set_get_vision_render_mode_targets_active_camera(self):
        fake_engine = self._fake_engine()
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = Path(tmp) / "tools.scene"
            scene_path.write_text("", encoding="utf-8")

            patches = self._patch_engine(fake_engine)
            with patches[0], patches[1], patches[2]:
                scene = scene_module.Scene(str(scene_path))
                fake_scene_manager = SimpleNamespace(get=lambda scene_name: scene)
                with patch.object(scene_tools_module, "scene_manager", fake_scene_manager):
                    result = scene_tools_module.SceneTools.set_vision_render_mode(
                        str(scene_path), None, "svgf")
                    fetched = scene_tools_module.SceneTools.get_vision_render_mode(
                        str(scene_path), None)
                    invalid = scene_tools_module.SceneTools.set_vision_render_mode(
                        str(scene_path), None, "bad_mode")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["mode"], "svgf")
            self.assertEqual(fetched["mode"], "svgf")
            self.assertEqual(invalid["status"], "error")

    def test_scene_tools_create_camera_view_copies_source_vision_render_mode(self):
        fake_engine = self._fake_engine()
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = Path(tmp) / "view_copy.scene"
            scene_path.write_text("", encoding="utf-8")

            patches = self._patch_engine(fake_engine)
            with patches[0], patches[1], patches[2]:
                scene = scene_module.Scene(str(scene_path))
                source = scene.get_active_camera()
                source.set_render_backend("vision")
                source.set_vision_render_mode("ssat")
                fake_scene_manager = SimpleNamespace(get=lambda scene_name: scene)
                with patch.object(scene_tools_module, "scene_manager", fake_scene_manager):
                    result = scene_tools_module.SceneTools.create_camera_view(
                        str(scene_path), "SSAT Preview")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["camera"]["vision_render_mode"], "ssat")


if __name__ == "__main__":
    unittest.main()
