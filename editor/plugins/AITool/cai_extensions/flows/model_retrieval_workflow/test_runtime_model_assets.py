from __future__ import annotations

import io
import importlib.util
import json
import os
import struct
import sys
import tempfile
import types
import unittest
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[6]
EDITOR_ROOT = PROJECT_ROOT / "editor"
AITOOL_ROOT = EDITOR_ROOT / "plugins" / "AITool"
for path in (EDITOR_ROOT, AITOOL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

_PKG = "cai_extensions.flows.model_retrieval_workflow"
if _PKG not in sys.modules:
    pkg = types.ModuleType(_PKG)
    pkg.__path__ = [os.path.dirname(__file__)]  # type: ignore[attr-defined]
    sys.modules[_PKG] = pkg


def _load_workflow_module(name: str):
    path = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"{_PKG}.{name}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{_PKG}.{name}"] = module
    spec.loader.exec_module(module)
    return module


def _png_bytes(size: tuple[int, int]) -> bytes:
    image = Image.new("RGBA", size, (120, 80, 40, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _pad4(data: bytes, pad_byte: bytes) -> bytes:
    return data + pad_byte * ((4 - len(data) % 4) % 4)


def _write_embedded_texture_glb(path: Path, texture_size: tuple[int, int]) -> bytes:
    png = _png_bytes(texture_size)
    document = {
        "asset": {"version": "2.0"},
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(png)}],
        "buffers": [{"byteLength": len(png)}],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
    }
    json_chunk = _pad4(json.dumps(document, separators=(",", ":")).encode("utf-8"), b" ")
    bin_chunk = _pad4(png, b"\x00")
    total_length = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    glb = b"".join(
        [
            struct.pack("<III", 0x46546C67, 2, total_length),
            struct.pack("<II", len(json_chunk), 0x4E4F534A),
            json_chunk,
            struct.pack("<II", len(bin_chunk), 0x004E4942),
            bin_chunk,
        ]
    )
    path.write_bytes(glb)
    return glb


def _read_first_image_size(glb_path: Path) -> tuple[int, int]:
    data = glb_path.read_bytes()
    offset = 12
    document = None
    binary = b""
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        payload = data[offset: offset + chunk_length]
        offset += chunk_length
        if chunk_type == 0x4E4F534A:
            document = json.loads(payload.rstrip(b" \x00\t\r\n").decode("utf-8"))
        elif chunk_type == 0x004E4942:
            binary = payload
    assert document is not None
    view = document["bufferViews"][document["images"][0]["bufferView"]]
    start = int(view.get("byteOffset", 0))
    end = start + int(view["byteLength"])
    with Image.open(io.BytesIO(binary[start:end])) as image:
        return image.size


class RuntimeModelAssetTests(unittest.TestCase):
    def test_prepare_runtime_model_bundle_downsamples_embedded_glb_without_touching_original(self):
        runtime_assets = _load_workflow_module("runtime_assets")

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "base.glb"
            original_bytes = _write_embedded_texture_glb(source, (2048, 1024))

            bundle = runtime_assets.prepare_runtime_model_bundle(str(source), max_texture_size=1024)

            runtime_path = Path(bundle.runtime_model_path)
            self.assertEqual(Path(bundle.original_model_path), source)
            self.assertEqual(source.read_bytes(), original_bytes)
            self.assertTrue(runtime_path.exists())
            self.assertEqual(runtime_path.name, "base.glb")
            self.assertEqual(runtime_path.parent.name, "runtime")
            self.assertEqual(_read_first_image_size(runtime_path), (1024, 512))

    def test_local_model_library_saves_original_and_returns_runtime_directory(self):
        _load_workflow_module("runtime_assets")
        helpers_mod = types.ModuleType(f"{_PKG}.helpers")

        def resolve_model_file(model_path: str) -> str:
            path = Path(model_path)
            if path.is_file():
                return str(path)
            if path.is_dir():
                runtime = path / "runtime" / "base.glb"
                if runtime.is_file():
                    return str(runtime)
                candidate = path / "base.glb"
                if candidate.is_file():
                    return str(candidate)
            return ""

        helpers_mod.resolve_model_file = resolve_model_file
        sys.modules[f"{_PKG}.helpers"] = helpers_mod
        local_model_library = _load_workflow_module("local_model_library")

        with tempfile.TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            source_dir = project_root / "models" / "椅子"
            source_dir.mkdir(parents=True)
            _write_embedded_texture_glb(source_dir / "base.glb", (2048, 2048))

            paths_config = types.ModuleType("Quasar.ai_config.paths_config")
            paths_config._get_active_project_path = lambda: project_root
            sys.modules.setdefault("Quasar", types.ModuleType("Quasar"))
            sys.modules.setdefault("Quasar.ai_config", types.ModuleType("Quasar.ai_config"))
            sys.modules["Quasar.ai_config.paths_config"] = paths_config

            local_model_library.save_model("椅子", str(source_dir / "base.glb"))
            runtime_dir = Path(local_model_library.lookup_model("椅子"))

            index = json.loads(
                (project_root / "assets" / "local_model_library" / "index.json").read_text(
                    encoding="utf-8"
                )
            )
            entry = index["椅子"]
            self.assertEqual(entry["runtime_texture_max"], 1024)
            self.assertIn("/runtime", entry["model_dir"].replace("\\", "/"))
            self.assertIn("/original", entry["original_model_dir"].replace("\\", "/"))
            self.assertEqual(runtime_dir.name, "runtime")
            self.assertTrue((runtime_dir / "base.glb").exists())
            self.assertEqual(_read_first_image_size(runtime_dir / "base.glb"), (1024, 1024))


if __name__ == "__main__":
    unittest.main()
