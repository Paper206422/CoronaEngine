"""Asset Metadata Builder — trimesh 读 glb/obj 获取真实 bbox, 绕过引擎 AABB。

引擎导入后 AABB 可能不可用 (get_world_aabb 返回 null), 此模块在导入前
直接用 trimesh 解析模型文件, 提取本地坐标系的包围盒和推荐放置类型。

用法:
  meta = build_asset_metadata("path/to/model.glb")
  # → {"size": [w,h,d], "bbox_min": [...], "bbox_max": [...], "placement_type": "..."}
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 模型名→放置类型 关键词映射 (优先于 bbox 推断)
_NAME_TO_PLACEMENT = {
    "台灯": "on_surface", "床头灯": "on_surface", "桌灯": "on_surface",
    "落地灯": "near_anchor", "立灯": "near_anchor",
    "地毯": "floor_surface", "地垫": "floor_surface", "毯": "floor_surface",
    "挂画": "wall_hung", "壁画": "wall_hung", "画": "wall_hung",
    "窗帘": "wall_hung", "卷帘": "wall_hung",
    "花瓶": "on_surface", "摆件": "on_surface",
    "沙发": "large_anchor", "床": "large_anchor", "桌": "large_anchor",
    "柜": "large_anchor", "架": "large_anchor", "几": "large_anchor",
}


def _infer_placement_type(name: str, bmin: List[float], bmax: List[float]) -> str:
    """从模型名(优先) + bbox(兜底)推断放置类型。

    Hunyuan3D 可能生成异常尺度(台灯 0.96m 高), 纯 bbox 会误判。
    """
    name_lower = name.lower()
    for kw, ptype in _NAME_TO_PLACEMENT.items():
        if kw in name_lower:
            return ptype

    # bbox fallback
    sx, sy, sz = bmax[0] - bmin[0], bmax[1] - bmin[1], bmax[2] - bmin[2]

    # 薄而宽 → floor_surface (地毯)
    if sy < 0.15 and max(sx, sz) > 1.5:
        return "floor_surface"
    # 高而窄 → near_anchor (落地灯)
    if sy > 2.5 * max(sx, sz):
        return "near_anchor"
    # 小而矮 → on_surface
    if sy < 0.8 and max(sx, sz) < 0.8:
        return "on_surface"
    # 挂在墙上 (高而扁)
    if sy > 0.8 and min(sx, sz) < 0.15:
        return "wall_hung"

    return "large_anchor"


def build_asset_metadata(model_path: str) -> Optional[Dict[str, Any]]:
    """trimesh 读 glb/obj, 返回 bbox + 推荐 placement_type。

    返回: {"size": [w,h,d], "bbox_min": [x,y,z], "bbox_max": [x,y,z],
           "placement_type": str, "face_count": int} 或 None
    """
    if not model_path or not os.path.isfile(model_path):
        logger.warning("[metadata] 文件不存在: %s", model_path)
        return None

    try:
        import trimesh
    except ImportError:
        logger.warning("[metadata] trimesh 未安装, 无法解析 bbox: %s", model_path)
        return None

    try:
        mesh = trimesh.load(model_path, force="mesh")
        if isinstance(mesh, trimesh.Scene):
            # 合并场景中所有 mesh
            meshes = [g for g in mesh.geometry.values() if hasattr(g, "vertices")]
            if not meshes:
                logger.warning("[metadata] 场景无几何体: %s", model_path)
                return None
            combined = trimesh.util.concatenate(meshes)
            vertices = combined.vertices
            faces = combined.faces
        else:
            vertices = mesh.vertices
            faces = mesh.faces

        bmin = vertices.min(axis=0)
        bmax = vertices.max(axis=0)
        size = bmax - bmin

        name = os.path.splitext(os.path.basename(model_path))[0]
        placement_type = _infer_placement_type(name, list(bmin), list(bmax))

        meta = {
            "file": model_path,
            "name": name,
            "size": [round(float(size[i]), 4) for i in range(3)],
            "bbox_min": [round(float(bmin[i]), 4) for i in range(3)],
            "bbox_max": [round(float(bmax[i]), 4) for i in range(3)],
            "placement_type": placement_type,
            "face_count": len(faces) if faces is not None else 0,
        }
        logger.info("[metadata] %s → size=%s type=%s", name, meta["size"], placement_type)
        return meta

    except Exception as e:
        logger.warning("[metadata] 解析失败 %s: %s", model_path, e)
        return None


def build_asset_metadata_batch(
    model_paths: List[str],
    cache_dir: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """批量解析模型, 结果写入 asset_metadata.json 缓存。

    返回 {model_name: metadata, ...}
    """
    result = {}
    for mp in model_paths:
        meta = build_asset_metadata(mp)
        if meta:
            result[meta["name"]] = meta

    if cache_dir and result:
        os.makedirs(cache_dir, exist_ok=True)
        cache_path = os.path.join(cache_dir, "asset_metadata.json")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            logger.info("[metadata] 缓存已写入: %s (%d 个模型)", cache_path, len(result))
        except Exception as e:
            logger.warning("[metadata] 缓存写入失败: %s", e)

    return result


def load_asset_metadata_cache(cache_dir: str) -> Dict[str, Dict[str, Any]]:
    """从缓存读取 metadata。"""
    cache_path = os.path.join(cache_dir, "asset_metadata.json")
    if not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[metadata] 缓存读取失败: %s", e)
        return {}
