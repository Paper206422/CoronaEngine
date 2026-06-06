"""
Terrain Generator — Pure Python Perlin-noise terrain pipeline.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


def _fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _lerp(a: np.ndarray, b: np.ndarray, t: np.ndarray) -> np.ndarray:
    return a + t * (b - a)


def _make_permutation(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    p = np.arange(256, dtype=np.int32)
    rng.shuffle(p)
    return np.tile(p, 2)


def _gradient(h: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    h_masked = h & 3
    u = np.where(h_masked < 2, x, y)
    v = np.where(h_masked < 2, y, x)
    return np.where((h_masked & 1) == 0, u, -u) + np.where((h_masked & 2) == 0, v, -v)


def perlin_noise_2d(x: np.ndarray, y: np.ndarray, perm: np.ndarray) -> np.ndarray:
    xi = np.floor(x).astype(np.int32)
    yi = np.floor(y).astype(np.int32)
    xf = x - xi
    yf = y - yi
    u = _fade(xf)
    v = _fade(yf)
    xi_mod = xi & 255
    yi_mod = yi & 255
    aa = perm[perm[xi_mod] + yi_mod]
    ab = perm[perm[xi_mod] + yi_mod + 1]
    ba = perm[perm[xi_mod + 1] + yi_mod]
    bb = perm[perm[xi_mod + 1] + yi_mod + 1]
    x1 = _lerp(_gradient(aa, xf, yf), _gradient(ba, xf - 1.0, yf), u)
    x2 = _lerp(_gradient(ab, xf, yf - 1.0), _gradient(bb, xf - 1.0, yf - 1.0), u)
    return _lerp(x1, x2, v)


def fbm_noise(x: np.ndarray, y: np.ndarray, octaves: int = 4, lacunarity: float = 2.0,
              persistence: float = 0.5, seed: int = 0) -> np.ndarray:
    perm = _make_permutation(seed)
    value = np.zeros_like(x)
    amplitude = 1.0
    frequency = 1.0
    max_value = 0.0
    for _ in range(octaves):
        value += amplitude * perlin_noise_2d(x * frequency, y * frequency, perm)
        max_value += amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return value / max_value


def generate_heightfield(config: Dict[str, Any], resolution: int,
                         world_size: Tuple[float, float] = (2048.0, 2048.0)) -> np.ndarray:
    terrain_cfg = config.get("terrain", {})
    noise_layers = terrain_cfg.get("noise_layers", [])
    seed = terrain_cfg.get("seed", 0)
    wx, wz = world_size
    xs = np.linspace(0, wx, resolution, dtype=np.float32)
    zs = np.linspace(0, wz, resolution, dtype=np.float32)
    x_grid, z_grid = np.meshgrid(xs, zs)
    height = np.zeros_like(x_grid, dtype=np.float32)
    for i, layer in enumerate(noise_layers):
        freq = layer.get("frequency", 0.005)
        amp = layer.get("amplitude", 100.0)
        octaves = layer.get("octaves", 4)
        lac = layer.get("lacunarity", 2.0)
        pers = layer.get("persistence", 0.5)
        layer_seed = seed + i * 1000
        noise = fbm_noise(x_grid * freq, z_grid * freq, octaves=octaves,
                          lacunarity=lac, persistence=pers, seed=layer_seed)
        height += noise * amp
    h_min = float(np.min(height))
    h_max = float(np.max(height))
    height_01 = (height - h_min) / (h_max - h_min + 1e-8)
    hr = terrain_cfg.get("height_range", [0, 500])
    logger.info("[terrain] heightfield: min=%.1f max=%.1f (target %s-%sm)",
                hr[0] + height_01.min() * (hr[1] - hr[0]),
                hr[0] + height_01.max() * (hr[1] - hr[0]), hr[0], hr[1])
    return height_01.astype(np.float32)


def compute_slope(heightfield: np.ndarray, world_size: Tuple[float, float] = (2048.0, 2048.0)) -> np.ndarray:
    res = heightfield.shape[0]
    cell_size = world_size[0] / (res - 1)
    dz_dx = np.zeros_like(heightfield)
    dz_dy = np.zeros_like(heightfield)
    dz_dx[:, 1:-1] = (heightfield[:, 2:] - heightfield[:, :-2]) / (2.0 * cell_size)
    dz_dy[1:-1, :] = (heightfield[2:, :] - heightfield[:-2, :]) / (2.0 * cell_size)
    dz_dx[:, 0] = (heightfield[:, 1] - heightfield[:, 0]) / cell_size
    dz_dx[:, -1] = (heightfield[:, -1] - heightfield[:, -2]) / cell_size
    dz_dy[0, :] = (heightfield[1, :] - heightfield[0, :]) / cell_size
    dz_dy[-1, :] = (heightfield[-1, :] - heightfield[-2, :]) / cell_size
    slope_rad = np.arctan(np.sqrt(dz_dx ** 2 + dz_dy ** 2))
    return np.degrees(slope_rad).astype(np.float32)


def generate_splatmap(heightfield: np.ndarray, slope: np.ndarray,
                      config: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
    ground_layers = config.get("ground", [])
    res = heightfield.shape[0]
    num_layers = len(ground_layers)
    if num_layers == 0:
        idx = np.zeros((res, res), dtype=np.uint8)
        return idx, np.stack([idx * 128] * 3, axis=-1).astype(np.uint8)
    scores = np.zeros((res, res, num_layers), dtype=np.float32)
    for i, layer in enumerate(ground_layers):
        weight = layer.get("weight", 100 / num_layers)
        hz = layer.get("height_zone", [0.0, 1.0])
        sr = layer.get("slope_range", [0, 90])
        h_lo, h_hi = hz[0], hz[1]
        in_zone = (heightfield >= h_lo) & (heightfield <= h_hi)
        h_score = np.where(in_zone, 1.0, 0.0)
        zone_half = (h_hi - h_lo) * 0.1
        below = (heightfield >= h_lo - zone_half) & (heightfield < h_lo)
        above = (heightfield > h_hi) & (heightfield <= h_hi + zone_half)
        h_score = np.where(below, (heightfield - (h_lo - zone_half)) / zone_half, h_score)
        h_score = np.where(above, (h_hi + zone_half - heightfield) / zone_half, h_score)
        s_lo, s_hi = sr[0], sr[1]
        s_score = np.where((slope >= s_lo) & (slope <= s_hi), 1.0, 0.0)
        scores[:, :, i] = h_score * s_score * weight
    splatmap_idx = np.argmax(scores, axis=2).astype(np.uint8)
    splatmap_rgb = np.zeros((res, res, 3), dtype=np.uint8)
    for i, layer in enumerate(ground_layers):
        color = layer.get("color", [128, 128, 128])
        mask = splatmap_idx == i
        for c in range(3):
            splatmap_rgb[:, :, c][mask] = color[c]
    logger.info("[terrain] splatmap: %d unique materials across %d layers",
                len(np.unique(splatmap_idx)), num_layers)
    return splatmap_idx, splatmap_rgb


def scatter_vegetation(heightfield: np.ndarray, splatmap_idx: np.ndarray, slope: np.ndarray,
                       config: Dict[str, Any],
                       world_size: Tuple[float, float] = (2048.0, 2048.0)) -> List[Dict[str, Any]]:
    veg_layers = config.get("vegetation", [])
    ground_layers = config.get("ground", [])
    material_names = [g.get("name", "") for g in ground_layers]
    res = heightfield.shape[0]
    wx, wz = world_size
    cell_size = wx / (res - 1)
    all_points: List[Dict[str, Any]] = []
    for veg in veg_layers:
        name = veg.get("name", "veg")
        density = veg.get("density", 0.5)
        slope_max = veg.get("slope_max", 90)
        material_mask = veg.get("material_mask", [])
        if density <= 0:
            continue
        step = max(1, int(np.sqrt(1.0 / max(density, 0.001))))
        rng = np.random.default_rng(hash(name) % (2 ** 31))
        points = []
        for i in range(0, res, step):
            for j in range(0, res, step):
                di = min(i + rng.uniform(0, step), res - 1)
                dj = min(j + rng.uniform(0, step), res - 1)
                ii, jj = int(di), int(dj)
                if slope[ii, jj] > slope_max:
                    continue
                mat_idx = int(splatmap_idx[ii, jj])
                mat_name = material_names[mat_idx] if mat_idx < len(material_names) else ""
                if material_mask and mat_name not in material_mask:
                    continue
                if rng.random() > density * (step * cell_size) ** 2:
                    continue
                world_x = jj * cell_size
                world_z = ii * cell_size
                world_y = heightfield[ii, jj]
                points.append({"name": name, "x": float(world_x), "y": float(world_y),
                               "z": float(world_z), "material": mat_name})
        all_points.extend(points)
        logger.info("[terrain] veg scatter: %s → %d points (density %.3f)", name, len(points), density)
    logger.info("[terrain] veg scatter: %d points for %d types", len(all_points), len(veg_layers))
    return all_points


def export_obj(heightfield: np.ndarray, splatmap_idx: np.ndarray, output_dir: str,
               config: Dict[str, Any], world_size: Tuple[float, float] = (2048.0, 2048.0)) -> str:
    res = heightfield.shape[0]
    wx, wz = world_size
    cell_size_x = wx / (res - 1)
    cell_size_z = wz / (res - 1)
    hr = config.get("terrain", {}).get("height_range", [0, 500])
    h_min, h_max = hr[0], hr[1]
    heights = heightfield * (h_max - h_min) + h_min
    os.makedirs(output_dir, exist_ok=True)
    obj_path = os.path.join(output_dir, "terrain.obj")
    mtl_path = os.path.join(output_dir, "terrain.mtl")
    with open(mtl_path, "w", encoding="utf-8") as f:
        f.write("newmtl TerrainMat\nKa 0.3 0.3 0.3\nKd 0.8 0.8 0.8\nKs 0.1 0.1 0.1\nNs 10.0\n")
    verts = [(j * cell_size_x, heights[i, j], i * cell_size_z) for i in range(res) for j in range(res)]
    faces = []
    for i in range(res - 1):
        for j in range(res - 1):
            v00 = i * res + j + 1
            v10 = i * res + j + 2
            v01 = (i + 1) * res + j + 1
            v11 = (i + 1) * res + j + 2
            faces.append((v00, v10, v11))
            faces.append((v00, v11, v01))
    with open(obj_path, "w", encoding="utf-8") as f:
        f.write(f"# CoronaEngine Terrain Mesh\n# resolution {res}x{res}, world {wx}x{wz}m\n")
        f.write(f"# height range {h_min}-{h_max}m\n\nmtllib terrain.mtl\nusemtl TerrainMat\n")
        for v in verts:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        for _ in range(len(faces)):
            f.write("vn 0.0000 1.0000 0.0000\n")
        for idx, face in enumerate(faces):
            n = idx + 1
            f.write(f"f {face[0]}//{n} {face[1]}//{n} {face[2]}//{n}\n")
    n_verts = len(verts)
    n_faces = len(faces)
    logger.info("[terrain] OBJ exported: %d verts, %d faces -> %s", n_verts, n_faces, obj_path)
    return obj_path


def export_visualizations(heightfield: np.ndarray, splatmap_rgb: np.ndarray,
                          veg_points: List[Dict[str, Any]], output_dir: str,
                          config: Dict[str, Any],
                          world_size: Tuple[float, float] = (2048.0, 2048.0)) -> Dict[str, str]:
    from PIL import Image
    os.makedirs(output_dir, exist_ok=True)
    hr = config.get("terrain", {}).get("height_range", [0, 500])
    hm_normalized = ((heightfield * (hr[1] - hr[0]) + hr[0]) * 10).astype(np.uint16)
    hm_path = os.path.join(output_dir, "heightmap.png")
    Image.fromarray(hm_normalized, mode="I;16").save(hm_path)
    sm_path = os.path.join(output_dir, "splatmap.png")
    Image.fromarray(splatmap_rgb).save(sm_path)
    res = heightfield.shape[0]
    veg_img = np.zeros((res, res, 3), dtype=np.uint8)
    veg_img[:, :, 1] = 60
    veg_colors: Dict[str, Tuple[int, int, int]] = {}
    wx, wz = world_size
    if veg_points:
        for vp in veg_points:
            name = vp.get("name", "")
            if name not in veg_colors:
                rng = np.random.default_rng(hash(name) % (2 ** 31))
                veg_colors[name] = (int(rng.integers(50, 256)), int(rng.integers(50, 256)),
                                    int(rng.integers(50, 256)))
            px = int(vp["x"] / wx * (res - 1))
            pz = int(vp["z"] / wz * (res - 1))
            px, pz = max(0, min(res - 1, px)), max(0, min(res - 1, pz))
            veg_img[pz, px] = veg_colors[name]
    veg_path = os.path.join(output_dir, "veg_scatter.png")
    Image.fromarray(veg_img).save(veg_path)
    cfg_path = os.path.join(output_dir, "terrain_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    return {"heightmap": hm_path, "splatmap": sm_path, "veg_scatter": veg_path,
            "obj": os.path.join(output_dir, "terrain.obj"), "config": cfg_path}


# ---------------------------------------------------------------------------
# Indoor floor style presets
# ---------------------------------------------------------------------------
INDOOR_FLOOR_STYLES: Dict[str, Dict[str, Any]] = {
    "wood_warm": {
        "label": "暖木",
        "floor": {"Ka": [0.20, 0.15, 0.10], "Kd": [0.60, 0.45, 0.30], "Ks": [0.05, 0.05, 0.05], "Ns": 5.0},
        "wall":  {"Ka": [0.15, 0.12, 0.08], "Kd": [0.50, 0.38, 0.25], "Ks": [0.05, 0.05, 0.05], "Ns": 5.0},
        "wall_height": 0.35, "default_size": 10.0,
        "keywords": ["卧室", "书房", "温馨", "木", "wood", "bedroom", "study", "cozy", "warm", "日式"],
    },
    "wood_dark": {
        "label": "深木",
        "floor": {"Ka": [0.08, 0.06, 0.04], "Kd": [0.35, 0.22, 0.13], "Ks": [0.03, 0.03, 0.03], "Ns": 8.0},
        "wall":  {"Ka": [0.06, 0.04, 0.03], "Kd": [0.28, 0.18, 0.10], "Ks": [0.03, 0.03, 0.03], "Ns": 8.0},
        "wall_height": 0.4, "default_size": 12.0,
        "keywords": ["古典", "传统", "dark", "traditional", "classic", "图书馆", "library", "中式", "厚重"],
    },
    "modern": {
        "label": "现代白",
        "floor": {"Ka": [0.30, 0.30, 0.30], "Kd": [0.85, 0.85, 0.85], "Ks": [0.10, 0.10, 0.10], "Ns": 20.0},
        "wall":  {"Ka": [0.35, 0.35, 0.35], "Kd": [0.90, 0.90, 0.90], "Ks": [0.10, 0.10, 0.10], "Ns": 20.0},
        "wall_height": 0.3, "default_size": 10.0,
        "keywords": ["现代", "modern", "白", "简约", "minimal", "干净", "公寓", "apartment", "客厅", "living"],
    },
    "tile": {
        "label": "瓷砖",
        "floor": {"Ka": [0.25, 0.24, 0.22], "Kd": [0.75, 0.72, 0.68], "Ks": [0.15, 0.15, 0.15], "Ns": 30.0},
        "wall":  {"Ka": [0.28, 0.27, 0.25], "Kd": [0.80, 0.78, 0.74], "Ks": [0.10, 0.10, 0.10], "Ns": 25.0},
        "wall_height": 0.25, "default_size": 8.0,
        "keywords": ["厨房", "卫生间", "浴室", "tile", "kitchen", "bath", "瓷砖", "大理石", "marble"],
    },
    "concrete": {
        "label": "工业水泥",
        "floor": {"Ka": [0.12, 0.12, 0.12], "Kd": [0.45, 0.45, 0.45], "Ks": [0.02, 0.02, 0.02], "Ns": 3.0},
        "wall":  {"Ka": [0.10, 0.10, 0.10], "Kd": [0.38, 0.38, 0.38], "Ks": [0.02, 0.02, 0.02], "Ns": 3.0},
        "wall_height": 0.4, "default_size": 14.0,
        "keywords": ["工业", "industrial", "loft", "水泥", "concrete", "酒吧", "咖啡馆", "bar", "cafe", "仓库"],
    },
}


def _resolve_indoor_floor_style(scene_prompt: str) -> str:
    """Match scene prompt keywords to an indoor floor style. Returns style key.

    Style/material keywords weighted higher than room-type keywords,
    so "现代卧室" → modern (not wood_warm).
    """
    prompt_lower = scene_prompt.lower()
    # High-weight: material/style descriptors
    _STYLE_KEYWORDS = {
        "modern": ["现代", "modern", "简约", "minimal", "白", "干净"],
        "concrete": ["工业", "industrial", "loft", "水泥", "concrete"],
        "tile": ["瓷砖", "tile", "大理石", "marble", "厨房", "kitchen", "卫生间", "浴室", "bath"],
        "wood_dark": ["古典", "传统", "dark", "traditional", "classic", "深色", "厚重", "图书馆", "library", "中式"],
    }
    for style_key, keywords in _STYLE_KEYWORDS.items():
        for kw in keywords:
            if kw in prompt_lower:
                return style_key
    return "wood_warm"  # default


def generate_indoor_floor(output_dir: str, size: float = 10.0, wall_height: float = 0.5,
                          wall_thickness: float = 0.2, style: str = "wood_warm") -> Dict[str, Any]:
    """Convenience wrapper: generate a room box with default bbox from size parameter.
    Used by classifier.py (initial pass before objects are known).
    """
    half = size / 2.0
    return generate_room_box(
        output_dir,
        min_x=-half, max_x=half,
        min_y=-0.5, max_y=wall_height,
        min_z=-half, max_z=half,
        style=style,
    )


def generate_room_box(output_dir: str,
                      min_x: float, max_x: float,
                      min_y: float, max_y: float,
                      min_z: float, max_z: float,
                      style: str = "wood_warm") -> Dict[str, Any]:
    """Generate a simple room box from a bounding box.

    Bottom face = floor (FloorMat), 4 sides = walls (WallMat), top = ceiling (WallMat).
    This is the simplest possible room representation.
    """
    style_def = INDOOR_FLOOR_STYLES.get(style, INDOOR_FLOOR_STYLES["wood_warm"])
    floor_mat = style_def["floor"]

    os.makedirs(output_dir, exist_ok=True)
    obj_path = os.path.join(output_dir, "terrain.obj")
    mtl_path = os.path.join(output_dir, "terrain.mtl")

    # MTL — floor only, no walls
    with open(mtl_path, "w", encoding="utf-8") as f:
        f.write(f"newmtl FloorMat\n")
        f.write(f"Ka {floor_mat['Ka'][0]:.2f} {floor_mat['Ka'][1]:.2f} {floor_mat['Ka'][2]:.2f}\n")
        f.write(f"Kd {floor_mat['Kd'][0]:.2f} {floor_mat['Kd'][1]:.2f} {floor_mat['Kd'][2]:.2f}\n")
        f.write(f"Ks {floor_mat['Ks'][0]:.2f} {floor_mat['Ks'][1]:.2f} {floor_mat['Ks'][2]:.2f}\n")
        f.write(f"Ns {floor_mat['Ns']:.1f}\n")

    verts = []
    norms = []
    floor_faces = []

    def quad(vlist, nlist, flist, corners, nx, ny, nz):
        """Emit a quad (2 triangles CCW) with normal."""
        i = len(vlist) + 1
        vlist.extend(corners)
        nlist.extend([(nx, ny, nz)] * 4)
        flist.extend([i, i+1, i+2, i, i+2, i+3])

    # Floor as a 0.1m thick slab — never gets culled, always visible
    thick = 0.1
    y_top = min_y + thick
    y_bot = min_y

    # Top face (y=min_y+0.1, normal up — visible from above)
    quad(verts, norms, floor_faces,
         [(min_x, y_top, min_z), (max_x, y_top, min_z), (max_x, y_top, max_z), (min_x, y_top, max_z)],
         0, 1, 0)
    # Bottom face (y=min_y, normal down)
    quad(verts, norms, floor_faces,
         [(min_x, y_bot, max_z), (max_x, y_bot, max_z), (max_x, y_bot, min_z), (min_x, y_bot, min_z)],
         0, -1, 0)
    # 4 thin side edges
    quad(verts, norms, floor_faces,
         [(min_x, y_bot, min_z), (max_x, y_bot, min_z), (max_x, y_top, min_z), (min_x, y_top, min_z)],
         0, 0, -1)
    quad(verts, norms, floor_faces,
         [(max_x, y_bot, max_z), (min_x, y_bot, max_z), (min_x, y_top, max_z), (max_x, y_top, max_z)],
         0, 0, 1)
    quad(verts, norms, floor_faces,
         [(max_x, y_bot, min_z), (max_x, y_bot, max_z), (max_x, y_top, max_z), (max_x, y_top, min_z)],
         1, 0, 0)
    quad(verts, norms, floor_faces,
         [(min_x, y_bot, max_z), (min_x, y_bot, min_z), (min_x, y_top, min_z), (min_x, y_top, max_z)],
         -1, 0, 0)

    # Write OBJ — floor only
    with open(obj_path, "w", encoding="utf-8") as f:
        f.write(f"# Indoor Floor [{min_x:.1f},{max_x:.1f}] x [{min_z:.1f},{max_z:.1f}]\n")
        f.write("mtllib terrain.mtl\n\n")
        for v in verts:
            f.write(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
        for n in norms:
            f.write(f"vn {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}\n")
        f.write("usemtl FloorMat\n")
        for i in range(0, len(floor_faces), 3):
            a, b, c = floor_faces[i], floor_faces[i+1], floor_faces[i+2]
            f.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")

    n_faces = len(floor_faces) // 3
    sx, sz = max_x - min_x, max_z - min_z
    logger.info("[terrain] floor plane: %.1fx%.1fm style=%s, %d verts, %d faces → %s",
                sx, sz, style_def.get("label", style), len(verts), n_faces, obj_path)

    files = export_indoor_visualizations(output_dir, max(sx, sz), 0.01)

    return {
        "ok": True,
        "stats": {
            "resolution": 2,
            "height_range": [min_y, max_y],
            "faces": n_faces,
            "veg_count": 0, "water_count": 0,
            "generation_time_s": 0.01,
        },
        "files": files,
        "scene_name": "room_box",
    }


def export_indoor_visualizations(output_dir: str, size: float, wall_height: float) -> Dict[str, str]:
    """Export a simple top-down view of the indoor floor layout."""
    from PIL import Image
    img = np.zeros((256, 256, 3), dtype=np.uint8)
    # Floor: warm brown center
    img[20:236, 20:236] = [180, 140, 100]
    # Walls: darker border
    img[10:20, 10:246] = [120, 90, 60]
    img[236:246, 10:246] = [120, 90, 60]
    img[10:246, 10:20] = [120, 90, 60]
    img[10:246, 236:246] = [120, 90, 60]
    hm_path = os.path.join(output_dir, "heightmap.png")
    Image.fromarray(img).save(hm_path)
    sm_path = os.path.join(output_dir, "splatmap.png")
    Image.fromarray(img).save(sm_path)
    veg_path = os.path.join(output_dir, "veg_scatter.png")
    veg_img = np.zeros((256, 256, 3), dtype=np.uint8)
    veg_img[:, :, 1] = 40
    Image.fromarray(veg_img).save(veg_path)
    import json
    cfg_path = os.path.join(output_dir, "terrain_config.json")
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump({"type": "indoor_floor", "size": size, "wall_height": wall_height}, f)
    return {
        "heightmap": hm_path, "splatmap": sm_path, "veg_scatter": veg_path,
        "obj": os.path.join(output_dir, "terrain.obj"), "config": cfg_path,
    }


def generate_water_bodies(heightfield: np.ndarray, config: Dict[str, Any]) -> List[Dict[str, Any]]:
    return []


def generate_terrain(config: Dict[str, Any], output_dir: str, resolution: int = 256,
                     world_size: Tuple[float, float] = (2048.0, 2048.0)) -> Dict[str, Any]:
    t0 = time.time()
    heightfield = generate_heightfield(config, resolution, world_size)
    slope = compute_slope(heightfield, world_size)
    splatmap_idx, splatmap_rgb = generate_splatmap(heightfield, slope, config)
    veg_points = scatter_vegetation(heightfield, splatmap_idx, slope, config, world_size)
    water_bodies = generate_water_bodies(heightfield, config)
    export_obj(heightfield, splatmap_idx, output_dir, config, world_size)
    files = export_visualizations(heightfield, splatmap_rgb, veg_points, output_dir, config, world_size)
    total_time = time.time() - t0
    stats = {
        "resolution": resolution,
        "height_range": config.get("terrain", {}).get("height_range", [0, 500]),
        "faces": ((resolution - 1) ** 2) * 2,
        "veg_count": len(veg_points),
        "water_count": len(water_bodies),
        "generation_time_s": round(total_time, 2),
    }
    logger.info("[terrain] complete in %.2fs: %d faces, %d veg points",
                total_time, stats["faces"], stats["veg_count"])
    return {"ok": True, "stats": stats, "files": files, "scene_name": config.get("scene_name", "terrain")}
