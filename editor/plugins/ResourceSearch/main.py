"""
ResourceSearch 插件 —— 场景栏资源智能搜索的 Python 后端入口

暴露给 CEF 的方法(全部 @staticmethod,语义对齐 SceneTools/SceneDatas):

    fuzzy_search(query, top_k=20, type_filter=None)
        -> { status, items, total, elapsed_ms }
    image_search(image_b64, top_k=20, threshold=10)
        -> { status, items, total, elapsed_ms }
    list_types()
        -> { status, types: [{type,label,count}] }
    rebuild_index()
        -> { status, count, elapsed_seconds }
    get_stats()
        -> { status, project_root, count, image_count, build_time }
    focus_actor(scene_name, actor_name)  (桥接 SceneTools)
        -> { status, center, distance }
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import List, Optional

from CoronaPlugin.core.corona_plugin_base import PluginBase
from utils.settings import settings_manager

from .image_search import DEFAULT_THRESHOLD, ImageIndex, _is_pil_available
from .indexer import ResourceIndex

logger = logging.getLogger(__name__)


# 模块级单例(线程安全惰性构建)
_index_lock = threading.Lock()
_text_index: Optional[ResourceIndex] = None
_image_index: Optional[ImageIndex] = None
_last_resource_items: List[dict] = []  # 缓存最近一次构建的资源项,供以图搜索回填


def _get_text_index() -> ResourceIndex:
    global _text_index
    if _text_index is None:
        with _index_lock:
            if _text_index is None:
                project = _resolve_project_root()
                _text_index = ResourceIndex(project)
                _text_index.rebuild()
    return _text_index


def _get_image_index() -> ImageIndex:
    global _image_index
    if _image_index is None:
        with _index_lock:
            if _image_index is None:
                _image_index = ImageIndex()
                # 用文本索引的 items 构建以图索引
                if _text_index is not None:
                    _image_index.build(_last_resource_items)
    return _image_index


def _resolve_project_root() -> str:
    project = settings_manager.active_project_path
    if not project:
        return os.getcwd()
    return project


def _refresh_cached_items():
    """将文本索引的当前 items 缓存,以便以图搜索回填元数据"""
    global _last_resource_items
    if _text_index is None:
        _last_resource_items = []
        return
    # 复用 _recent 拿全量 (top_k 设为 -1 不行,改为内部访问)
    with _text_index._lock:
        _last_resource_items = [
            it.to_dict(score=0.0) for it in _text_index._items.values()
        ]


@PluginBase.register_web("ResourceSearch")
class ResourceSearch(PluginBase):
    """场景栏资源智能搜索"""

    # ==================================================================
    #  对外接口
    # ==================================================================

    @staticmethod
    def fuzzy_search(query: str, top_k: int = 20,
                     type_filter: Optional[str] = None) -> dict:
        """模糊文本搜索"""
        try:
            idx = _get_text_index()
            start = time.perf_counter()
            items = idx.fuzzy(query, top_k=top_k, type_filter=type_filter)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return {
                "status": "success",
                "items": items,
                "total": len(items),
                "elapsed_ms": round(elapsed_ms, 2),
                "query": query,
            }
        except Exception as exc:
            logger.exception("fuzzy_search 失败")
            return {"status": "error", "message": str(exc), "items": [], "total": 0}

    @staticmethod
    def image_search(image_b64: str, top_k: int = 20,
                     threshold: int = DEFAULT_THRESHOLD) -> dict:
        """以图搜索(纯本地 pHash,无网络依赖)"""
        try:
            if not _is_pil_available():
                return {
                    "status": "error",
                    "message": "Pillow 未安装,无法执行以图搜索",
                    "items": [],
                    "total": 0,
                }
            if not image_b64 or not str(image_b64).strip():
                return {
                    "status": "error",
                    "message": "image_b64 不能为空",
                    "items": [],
                    "total": 0,
                }
            # 显式 clamp,避免下游 + 响应不一致
            try:
                threshold_clamped = max(0, int(threshold))
            except (TypeError, ValueError):
                threshold_clamped = DEFAULT_THRESHOLD

            _refresh_cached_items()
            img_idx = _get_image_index()
            start = time.perf_counter()
            items = img_idx.search(
                image_data=image_b64,
                top_k=top_k,
                threshold=threshold_clamped,
                resource_items=_last_resource_items,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            # 区分"输入图片无效(无法解码)"与"无命中"
            # 通过在 image_search 内再次尝试解码来判定
            from .image_search import _decode_base64_image
            if _decode_base64_image(image_b64) is None:
                return {
                    "status": "error",
                    "message": "图片数据无效或无法解码",
                    "items": [],
                    "total": 0,
                    "elapsed_ms": round(elapsed_ms, 2),
                    "threshold": threshold_clamped,
                }

            return {
                "status": "success",
                "items": items,
                "total": len(items),
                "elapsed_ms": round(elapsed_ms, 2),
                "threshold": threshold_clamped,
            }
        except Exception as exc:
            logger.exception("image_search 失败")
            return {"status": "error", "message": str(exc), "items": [], "total": 0}

    @staticmethod
    def list_types() -> dict:
        """列出项目内出现的资源类型 + 计数"""
        try:
            idx = _get_text_index()
            return {"status": "success", "types": idx.list_types()}
        except Exception as exc:
            logger.exception("list_types 失败")
            return {"status": "error", "message": str(exc), "types": []}

    @staticmethod
    def rebuild_index() -> dict:
        """全量重建文本 + 图像索引"""
        try:
            global _text_index, _image_index
            project = _resolve_project_root()
            with _index_lock:
                _text_index = ResourceIndex(project)
                stats = _text_index.rebuild()
                _refresh_cached_items()
                if _is_pil_available():
                    if _image_index is None:
                        _image_index = ImageIndex()
                    img_stats = _image_index.build(_last_resource_items)
                else:
                    img_stats = {"status": "skipped", "message": "Pillow 不可用"}
            return {
                "status": "success",
                "text": stats,
                "image": img_stats,
            }
        except Exception as exc:
            logger.exception("rebuild_index 失败")
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def get_stats() -> dict:
        """返回当前索引统计信息"""
        try:
            idx = _get_text_index()
            img_idx = _get_image_index() if _is_pil_available() else None
            return {
                "status": "success",
                "text": idx.stats(),
                "image": img_idx.stats() if img_idx else {"image_count": 0},
            }
        except Exception as exc:
            logger.exception("get_stats 失败")
            return {"status": "error", "message": str(exc)}

    @staticmethod
    def focus_actor(scene_name: str, actor_name: str) -> dict:
        """
        桥接 SceneTools.focus_actor,供搜索结果"定位"按钮使用。
        引入此代理以避免前端同时引用 SceneTools 产生耦合。
        """
        try:
            from plugins.SceneTools.main import SceneTools  # 延迟导入
            return SceneTools.focus_actor(scene_name, actor_name)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.exception("focus_actor 失败")
            return {"status": "error", "message": str(exc)}

    # ==================================================================
    #  内部工具
    # ==================================================================

    @staticmethod
    def _get_pil_status() -> dict:
        """查询 PIL 可用性(供上层诊断)"""
        return {
            "pil_available": _is_pil_available(),
            "project_root": _resolve_project_root(),
        }
