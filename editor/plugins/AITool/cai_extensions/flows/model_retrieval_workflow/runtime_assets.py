from __future__ import annotations

import io
import json
import logging
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_GLB_MAGIC = 0x46546C67
_GLB_VERSION = 2
_JSON_CHUNK = 0x4E4F534A
_BIN_CHUNK = 0x004E4942
_SUPPORTED_MODEL_EXTS = {".obj", ".dae", ".glb", ".gltf", ".fbx", ".stl", ".usdz"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class RuntimeModelBundle:
    original_model_path: str
    runtime_model_path: str


def prepare_runtime_model_bundle(
    model_path: str,
    *,
    max_texture_size: int = 1024,
) -> RuntimeModelBundle:
    source = Path(model_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"模型文件不存在: {source}")

    original = _resolve_original_model_path(source)
    if source.parent.name == "runtime":
        return RuntimeModelBundle(
            original_model_path=str(original),
            runtime_model_path=str(source),
        )

    runtime_dir = _runtime_dir_for_source(source)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    runtime_model_path = runtime_dir / source.name

    if source.suffix.lower() == ".glb":
        _write_runtime_glb(source, runtime_model_path, max_texture_size)
    else:
        _copy_runtime_directory(source.parent, runtime_dir)
        if source.suffix.lower() in {".obj", ".gltf"}:
            _downsample_external_textures(runtime_dir, max_texture_size)

    return RuntimeModelBundle(
        original_model_path=str(original),
        runtime_model_path=str(runtime_model_path),
    )


def find_runtime_model_for(source_path: Path) -> Path:
    source = source_path.resolve()
    if source.parent.name == "runtime":
        return source
    runtime_candidate = _runtime_dir_for_source(source) / source.name
    return runtime_candidate if runtime_candidate.is_file() else source


def _resolve_original_model_path(source: Path) -> Path:
    if source.parent.name != "runtime":
        return source
    direct_sibling = source.parent.parent / source.name
    if direct_sibling.is_file():
        return direct_sibling.resolve()
    original_sibling = source.parent.parent / "original" / source.name
    if original_sibling.is_file():
        return original_sibling.resolve()
    return source


def _runtime_dir_for_source(source: Path) -> Path:
    if source.parent.name == "original":
        return source.parent.parent / "runtime"
    return source.parent / "runtime"


def _copy_runtime_directory(source_dir: Path, runtime_dir: Path) -> None:
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir, ignore_errors=True)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for item in source_dir.iterdir():
        if item.name in {"runtime", "original"}:
            continue
        dst = runtime_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dst, ignore=shutil.ignore_patterns("runtime", "original"))
        elif item.is_file():
            shutil.copy2(item, dst)


def _downsample_external_textures(root: Path, max_texture_size: int) -> None:
    for image_path in root.rglob("*"):
        if image_path.suffix.lower() not in _IMAGE_EXTS or not image_path.is_file():
            continue
        try:
            resized = _resize_image_bytes(
                image_path.read_bytes(),
                _mime_from_suffix(image_path.suffix),
                max_texture_size,
            )
            image_path.write_bytes(resized)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[RuntimeAssets] 外部贴图降采样失败: %s, err=%s", image_path, exc)


def _write_runtime_glb(source: Path, runtime_path: Path, max_texture_size: int) -> None:
    try:
        document, binary = _read_glb(source)
        runtime_document, runtime_binary = _rewrite_embedded_images(
            document,
            binary,
            max_texture_size,
        )
        runtime_path.write_bytes(_build_glb(runtime_document, runtime_binary))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RuntimeAssets] GLB runtime 生成失败，回退复制原文件: %s, err=%s", source, exc)
        shutil.copy2(source, runtime_path)


def _read_glb(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError("GLB 文件过短")
    magic, version, total_length = struct.unpack_from("<III", data, 0)
    if magic != _GLB_MAGIC or version != _GLB_VERSION:
        raise ValueError("仅支持 GLB v2")
    if total_length > len(data):
        raise ValueError("GLB 长度字段无效")

    offset = 12
    document: dict | None = None
    binary = b""
    while offset + 8 <= total_length:
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        payload = data[offset: offset + chunk_length]
        offset += chunk_length
        if chunk_type == _JSON_CHUNK:
            document = json.loads(payload.rstrip(b" \x00\t\r\n").decode("utf-8"))
        elif chunk_type == _BIN_CHUNK:
            binary = payload

    if document is None:
        raise ValueError("GLB 缺少 JSON chunk")
    return document, binary


def _rewrite_embedded_images(
    document: dict,
    binary: bytes,
    max_texture_size: int,
) -> tuple[dict, bytes]:
    runtime_document = json.loads(json.dumps(document, ensure_ascii=False))
    buffer_views = runtime_document.get("bufferViews") or []
    images = runtime_document.get("images") or []
    image_by_view: dict[int, dict] = {}
    for image in images:
        if isinstance(image, dict) and "bufferView" in image:
            image_by_view[int(image["bufferView"])] = image

    if not buffer_views or not image_by_view:
        return runtime_document, binary

    bin_parts: list[bytes] = []
    new_offset = 0
    for index, view in enumerate(buffer_views):
        if not isinstance(view, dict):
            continue
        start = int(view.get("byteOffset", 0))
        length = int(view.get("byteLength", 0))
        payload = binary[start: start + length]

        image = image_by_view.get(index)
        if image is not None:
            mime_type = str(image.get("mimeType") or "image/png")
            payload = _resize_image_bytes(payload, mime_type, max_texture_size)
            image["mimeType"] = _mime_from_image_bytes(payload, mime_type)

        aligned_offset = _align4(new_offset)
        if aligned_offset > new_offset:
            bin_parts.append(b"\x00" * (aligned_offset - new_offset))
            new_offset = aligned_offset
        view["byteOffset"] = new_offset
        view["byteLength"] = len(payload)
        bin_parts.append(payload)
        new_offset += len(payload)

    new_binary = b"".join(bin_parts)
    buffers = runtime_document.get("buffers") or []
    if buffers and isinstance(buffers[0], dict):
        buffers[0]["byteLength"] = len(new_binary)
    return runtime_document, new_binary


def _resize_image_bytes(data: bytes, mime_type: str, max_texture_size: int) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) <= max_texture_size:
            return data
        image.thumbnail((max_texture_size, max_texture_size), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        if mime_type.lower() in {"image/jpeg", "image/jpg"}:
            if image.mode not in {"RGB", "L"}:
                image = image.convert("RGB")
            image.save(out, format="JPEG", quality=85, optimize=True)
        else:
            if image.mode not in {"RGBA", "RGB", "L"}:
                image = image.convert("RGBA")
            image.save(out, format="PNG", optimize=True)
        return out.getvalue()


def _mime_from_image_bytes(data: bytes, fallback: str) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return fallback


def _mime_from_suffix(suffix: str) -> str:
    return "image/jpeg" if suffix.lower() in {".jpg", ".jpeg"} else "image/png"


def _build_glb(document: dict, binary: bytes) -> bytes:
    json_payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    json_chunk = _pad4(json_payload, b" ")
    bin_chunk = _pad4(binary, b"\x00")
    total_length = 12 + 8 + len(json_chunk)
    chunks = [
        struct.pack("<II", len(json_chunk), _JSON_CHUNK),
        json_chunk,
    ]
    if bin_chunk:
        total_length += 8 + len(bin_chunk)
        chunks.extend([struct.pack("<II", len(bin_chunk), _BIN_CHUNK), bin_chunk])
    return b"".join([struct.pack("<III", _GLB_MAGIC, _GLB_VERSION, total_length), *chunks])


def _pad4(data: bytes, pad_byte: bytes) -> bytes:
    return data + pad_byte * ((4 - len(data) % 4) % 4)


def _align4(value: int) -> int:
    return value + ((4 - value % 4) % 4)
