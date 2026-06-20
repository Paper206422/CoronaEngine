import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


_SUPPORTED_MODEL_EXTENSIONS = {
    ".obj",
    ".fbx",
    ".gltf",
    ".glb",
    ".dae",
    ".ply",
    ".stl",
}


def _scene_data(document: dict) -> dict:
    if not isinstance(document, dict):
        return {}
    scene = document.get("scene")
    return scene if isinstance(scene, dict) else document


def _shape_name(shape: dict, index: int) -> str:
    raw = shape.get("name") or shape.get("names") or f"vision_shape_{index}"
    if isinstance(raw, list):
        raw = raw[0] if raw else f"vision_shape_{index}"
    name = str(raw).strip() or f"vision_shape_{index}"
    return name.replace(".", "_")


def _as_float3(value: Any, default: Optional[List[float]] = None) -> Optional[List[float]]:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return default
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError):
        return default


def _column_major_matrix(value: Any) -> Optional[List[List[float]]]:
    if not isinstance(value, list) or len(value) != 4:
        return None
    matrix = []
    try:
        for col in value:
            if not isinstance(col, list) or len(col) != 4:
                return None
            matrix.append([float(v) for v in col])
    except (TypeError, ValueError):
        return None
    return matrix


def _vision_to_corona_matrix(matrix: List[List[float]]) -> List[List[float]]:
    converted = []
    for col_index, column in enumerate(matrix):
        converted_column = []
        for row_index, value in enumerate(column):
            if row_index == 2:
                value = -value
            if col_index == 2:
                value = -value
            converted_column.append(value)
        converted.append(converted_column)
    return converted


def _column_length(column: List[float]) -> float:
    return math.sqrt(column[0] * column[0] + column[1] * column[1] + column[2] * column[2])


def _extract_transform(transform: Any) -> Dict[str, Any]:
    result = {
        "position": [0.0, 0.0, 0.0],
        "rotation": [0.0, 0.0, 0.0],
        "scale": [1.0, 1.0, 1.0],
        "approximation": "identity",
    }
    if not isinstance(transform, dict):
        return result

    transform_type = str(transform.get("type") or "matrix4x4")
    params = transform.get("param") if isinstance(transform.get("param"), dict) else transform

    if transform_type == "matrix4x4":
        matrix = _column_major_matrix(params.get("matrix4x4"))
        if matrix is None:
            return result
        corona_matrix = _vision_to_corona_matrix(matrix)
        result["position"] = [
            corona_matrix[3][0],
            corona_matrix[3][1],
            corona_matrix[3][2],
        ]
        result["scale"] = [
            _column_length(corona_matrix[0]),
            _column_length(corona_matrix[1]),
            _column_length(corona_matrix[2]),
        ]
        result["approximation"] = "matrix4x4_position_scale"
        return result

    if transform_type == "trs":
        position = _as_float3(params.get("t"), [0.0, 0.0, 0.0])
        scale = _as_float3(params.get("s"), [1.0, 1.0, 1.0])
        result["position"] = [position[0], position[1], -position[2]]
        result["scale"] = scale
        result["approximation"] = "trs_position_scale"
        return result

    if transform_type == "Euler":
        position = _as_float3(params.get("position"), [0.0, 0.0, 0.0])
        result["position"] = [position[0], position[1], -position[2]]
        result["rotation"] = [
            float(params.get("pitch", 0.0) or 0.0),
            float(params.get("yaw", 0.0) or 0.0),
            float(params.get("roll", 0.0) or 0.0),
        ]
        result["approximation"] = "euler"
        return result

    return result


def _number_value(slot: Any) -> Any:
    if isinstance(slot, (int, float, list)):
        return slot
    if not isinstance(slot, dict):
        return None
    node = slot.get("node")
    if isinstance(node, dict):
        params = node.get("param")
        if isinstance(params, dict) and "value" in params:
            return params.get("value")
    params = slot.get("param")
    if isinstance(params, dict) and "value" in params:
        return params.get("value")
    return None


def _material_optics(material: dict) -> Dict[str, Any]:
    if not isinstance(material, dict):
        return {}
    params = material.get("param") if isinstance(material.get("param"), dict) else {}
    optics: Dict[str, Any] = {}

    color = _as_float3(_number_value(params.get("color")))
    if color is not None:
        optics["diffuse"] = color
        optics["ambient"] = color

    scalar_fields = {
        "roughness": "roughness",
        "metallic": "metallic",
        "subsurface_weight": "subsurface",
        "anisotropic": "anisotropic",
        "sheen_weight": "sheen",
        "coat_weight": "clearcoat",
    }
    for vision_key, optics_key in scalar_fields.items():
        value = _number_value(params.get(vision_key))
        if isinstance(value, (int, float)):
            optics[optics_key] = float(value)

    coat_roughness = _number_value(params.get("coat_roughness"))
    if isinstance(coat_roughness, (int, float)):
        optics["clearcoat_gloss"] = max(0.0, min(1.0, 1.0 - float(coat_roughness)))

    return optics


def _material_table(scene: dict) -> Dict[str, Dict[str, Any]]:
    materials = scene.get("materials")
    if not isinstance(materials, list):
        return {}
    table = {}
    for material in materials:
        if isinstance(material, dict) and material.get("name"):
            table[str(material["name"])] = _material_optics(material)
    return table


def extract_vision_actor_imports(document: dict, source_path: str) -> Dict[str, Any]:
    scene = _scene_data(document)
    shapes = scene.get("shapes")
    if not isinstance(shapes, list):
        return {"actors": [], "unsupported_shapes": []}

    base_dir = Path(source_path).resolve().parent
    materials = _material_table(scene)
    actors = []
    unsupported = []

    for index, shape in enumerate(shapes):
        if not isinstance(shape, dict):
            continue
        shape_type = str(shape.get("type") or "")
        params = shape.get("param") if isinstance(shape.get("param"), dict) else {}
        identity = f"vision:{os.path.abspath(source_path)}#scene.shapes[{index}]"
        name = _shape_name(shape, index)

        if shape_type != "model":
            unsupported.append({
                "index": index,
                "name": name,
                "type": shape_type,
                "reason": "unsupported_shape_type",
            })
            continue

        fn = params.get("fn")
        if not isinstance(fn, str) or not fn.strip():
            unsupported.append({
                "index": index,
                "name": name,
                "type": shape_type,
                "reason": "missing_model_file",
            })
            continue

        model_path = (base_dir / fn).resolve()
        if model_path.suffix.lower() not in _SUPPORTED_MODEL_EXTENSIONS:
            unsupported.append({
                "index": index,
                "name": name,
                "type": shape_type,
                "path": str(model_path),
                "reason": "unsupported_model_extension",
            })
            continue
        if not model_path.is_file():
            unsupported.append({
                "index": index,
                "name": name,
                "type": shape_type,
                "path": str(model_path),
                "reason": "model_file_not_found",
            })
            continue

        transform = _extract_transform(params.get("transform"))
        actors.append({
            "name": name,
            "route": str(model_path),
            "actor_type": "model",
            "actor_guid": identity,
            "geometry": {
                "position": transform["position"],
                "rotation": transform["rotation"],
                "scale": transform["scale"],
            },
            "optics": materials.get(str(params.get("material") or ""), {}),
            "vision": {
                "source_path": os.path.abspath(source_path),
                "shape_index": index,
                "shape_type": shape_type,
                "shape_name": name,
                "transform_approximation": transform["approximation"],
            },
        })

    return {"actors": actors, "unsupported_shapes": unsupported}
