"""
ResourceSearch 插件 —— 场景栏资源智能搜索的 Python 后端入口

=================================================================================
# 安全模型(2026-06 重构)
=================================================================================
本插件**只**服务于场景栏资源智能搜索,严禁被 AI 工具链 / 无关脚本调用。

三层防御:
    1. **类型白名单**(ALLOWED_SEARCH_TYPES):仅 model/actor/scene/multimedia/
       terrain/script 六类可被搜索
    2. **路径前缀黑名单**(indexer._BLOCKED_PATH_PREFIXES):AITool/、Frontend/、
       CoronaPlugin/、tests/、.git/ 等目录**永远**不作为搜索结果返回
    3. **调用方白名单**(ALLOWED_CALLERS):仅核心 UI 模块可调,
       显式拒绝 AITool、Quasar、cai.runtime 等 AI 链路

调用方必须通过 CEF 调用,并在 args 末尾传 `caller` 参数(见 bridge.js)。
=================================================================================
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from CoronaPlugin.core.corona_plugin_base import PluginBase
from utils.settings import settings_manager

from .image_search import DEFAULT_THRESHOLD, ImageIndex, _is_pil_available
from .indexer import ResourceIndex

logger = logging.getLogger(__name__)


# =============================================================================
#  模块级常量(安全策略)
# =============================================================================


# 调用方白名单:仅允许核心 UI / 编辑器模块调用搜索功能
ALLOWED_CALLERS: FrozenSet[str] = frozenset({
    "SceneBar",                # 场景栏资源搜索 UI
    "ProjectFileManager",      # 文件管理器
    "ProjectLauncher",         # 项目启动器
    "SceneTools",              # 场景编辑工具
    "SceneDatas",              # 场景数据工具
    "ResourceSearch",          # 内部交叉调用
    "MainView",                # 主视图
    "ProjectSettings",         # 项目设置
})

# 调用方黑名单:显式拒绝(防御纵深)
DENIED_CALLERS: FrozenSet[str] = frozenset({
    "AITool",                  # AI 工具链
    "AIExecutor",              # AI 执行器
    "Quasar",                  # AI 框架
    "cai.runtime",             # CAI 运行时
    "cai.app",                 # CAI 应用层
    "anonymous",               # 未声明调用方
})

# 可被搜索的资源类型白名单(对应 indexer._EXT_TYPE_MAP 的 key)
ALLOWED_SEARCH_TYPES: FrozenSet[str] = frozenset({
    "model",        # 3D 模型 (.obj, .fbx, .gltf, ...)
    "actor",        # 场景单位 (.actor)
    "scene",        # 场景定义 (.scene)
    "multimedia",   # 多媒体资源 (图片, 视频, 音频)
    "terrain",      # 地形 (.terrain)
    "script",       # 业务脚本 (.py)
})


# =============================================================================
#  模块级单例
# =============================================================================


_index_lock = threading.Lock()
_text_index: Optional[ResourceIndex] = None
_image_index: Optional[ImageIndex] = None
_last_resource_items: List[Dict[str, Any]] = []
_index_roots_signature: Optional[Tuple[str, ...]] = None


def _get_text_index() -> ResourceIndex:
    """获取文本索引(惰性构建;活动项目根变化时自动重建)

    Returns:
        进程内单例 ResourceIndex
    """
    global _text_index, _index_roots_signature
    roots = _resolve_search_roots()
    sig = tuple(roots)

    with _index_lock:
        if _text_index is None:
            logger.info("[ResourceSearch] 首次构建文本索引,根=%s", roots)
            _text_index = ResourceIndex(roots)
            _text_index.rebuild()
            _index_roots_signature = sig
        elif _index_roots_signature != sig:
            logger.info("[ResourceSearch] 索引根签名变化(%s → %s),重建",
                        _index_roots_signature, sig)
            _text_index = ResourceIndex(roots)
            _text_index.rebuild()
            _index_roots_signature = sig
    return _text_index


def _get_image_index() -> ImageIndex:
    """获取图像索引(惰性构建)"""
    global _image_index
    if _image_index is None:
        with _index_lock:
            if _image_index is None:
                _image_index = ImageIndex()
                if _text_index is not None:
                    _image_index.build(_last_resource_items)
    return _image_index


def _refresh_cached_items() -> None:
    """将文本索引的当前 items 缓存,以便以图搜索回填元数据"""
    global _last_resource_items
    if _text_index is None:
        _last_resource_items = []
        return
    with _text_index._lock:
        _last_resource_items = [
            it.to_dict(score=0.0) for it in _text_index._items.values()
        ]


# =============================================================================
#  鉴权工具
# =============================================================================


def _check_caller(caller: str) -> Optional[Dict[str, Any]]:
    """校验调用方权限

    Args:
        caller: 调用方名称(CEF 透传)

    Returns:
        None 表示通过;否则返回错误响应 dict(已带 status/error/code)
    """
    if not caller or not isinstance(caller, str):
        caller = "anonymous"

    # 黑名单:硬拒绝 + 警告日志
    if caller in DENIED_CALLERS:
        logger.warning("[fuzzy_search] 拒绝调用: caller=%r 在黑名单内", caller)
        return {
            "status": "error",
            "code": "permission_denied",
            "message": f"Caller '{caller}' is denied",
            "items": [],
            "total": 0,
        }

    # 白名单:必须命中
    if caller not in ALLOWED_CALLERS:
        logger.warning("[fuzzy_search] 拒绝调用: caller=%r 不在白名单", caller)
        return {
            "status": "error",
            "code": "permission_denied",
            "message": (f"Caller '{caller}' is not allowed to use search. "
                        f"Allowed: {sorted(ALLOWED_CALLERS)}"),
            "items": [],
            "total": 0,
        }
    return None


def _check_type(type_filter: Optional[str]) -> Optional[Dict[str, Any]]:
    """校验 type_filter 是否在白名单内"""
    if type_filter is None:
        return None
    if type_filter not in ALLOWED_SEARCH_TYPES:
        logger.warning("[fuzzy_search] 拒绝类型: type_filter=%r 不在白名单",
                       type_filter)
        return {
            "status": "error",
            "code": "invalid_type",
            "message": (f"type_filter '{type_filter}' is not in allowed types. "
                        f"Allowed: {sorted(ALLOWED_SEARCH_TYPES)}"),
            "items": [],
            "total": 0,
        }
    return None


# =============================================================================
#  多根解析
# =============================================================================


def _detect_engine_repo_root() -> Optional[str]:
    """检测 CoronaEngine 引擎仓库的根目录(assets/ 所在)

    解析策略:
        1. 从本文件 __file__ 向上找 `editor/` 目录,其父级即为引擎仓库根
        2. 否则,从 CWD 向上找 `assets/` 目录
    """
    try:
        cur = os.path.abspath(__file__)
        for _ in range(8):
            if os.path.basename(cur).lower() == "editor":
                candidate = os.path.dirname(cur)
                if os.path.isdir(os.path.join(candidate, "assets")):
                    return candidate
                return None
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    except Exception as exc:
        logger.debug("_detect_engine_repo_root 异常: %s", exc)

    # 兜底:从 CWD 向上找 assets/
    try:
        cur = os.path.abspath(os.getcwd())
        for _ in range(8):
            if os.path.isdir(os.path.join(cur, "assets")):
                return cur
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    except Exception as exc:
        logger.debug("_detect_engine_repo_root(CWD) 异常: %s", exc)
    return None


def _resolve_search_roots() -> List[str]:
    """解析资源索引要扫描的工程根目录列表(多根,顺序敏感)

    解析顺序(后扫描的根覆盖先扫描的根):
        1. settings_manager.active_project_path(若已打开项目)
        2. 引擎仓库根(包含 stock assets/、Scene/、scripts/ 等)

    Returns:
        扫描根绝对路径列表(去重、去不存在)
    """
    roots: List[str] = []
    seen: set = set()

    def _add(p: Optional[str]) -> None:
        if not p:
            return
        try:
            abs_p = os.path.abspath(p)
        except (TypeError, ValueError):
            return
        if not os.path.isdir(abs_p):
            return
        if abs_p in seen:
            return
        seen.add(abs_p)
        roots.append(abs_p)

    active = settings_manager.active_project_path
    _add(active)

    engine_repo = _detect_engine_repo_root()
    _add(engine_repo)

    if not roots:
        logger.warning("[ResourceSearch] 未能解析到任何有效扫描根,使用 CWD")
        roots.append(os.getcwd())

    logger.debug("[ResourceSearch] 解析到扫描根: %s", roots)
    return roots


# =============================================================================
#  插件主类
# =============================================================================


@PluginBase.register_web("ResourceSearch")
class ResourceSearch(PluginBase):
    """场景栏资源智能搜索(模型/单位/场景/多媒体/地形/脚本)

    所有 CEF 接口方法都是 @staticmethod,可由前端/其他插件直接调用。
    """

    # ==================================================================
    #  对外接口
    # ==================================================================

    @staticmethod
    def fuzzy_search(query: str, top_k: int = 20,
                     type_filter: Optional[str] = None,
                     caller: str = "anonymous") -> Dict[str, Any]:
        """模糊文本搜索(模型/单位/场景/多媒体/地形/脚本)

        三层防御:
            1. caller 必须在 ALLOWED_CALLERS 白名单内
            2. type_filter 必须在 ALLOWED_SEARCH_TYPES 白名单内
            3. 路径命中 _BLOCKED_PATH_PREFIXES 的项会被过滤掉

        Args:
            query: 搜索关键词
            top_k: 最多返回多少项(< 1 自动取 1)
            type_filter: 可选,仅返回指定类型(model/actor/scene/multimedia/terrain/script)
            caller: 调用方标识,必须在 ALLOWED_CALLERS 内

        Returns:
            标准响应 dict: {status, items, total, elapsed_ms, roots, rebuilt, query}
        """
        t_start = time.perf_counter()
        try:
            # ---- 1. 鉴权 ----
            err = _check_caller(caller)
            if err is not None:
                return err
            err = _check_type(type_filter)
            if err is not None:
                return err

            # ---- 2. 参数验证 ----
            if query is None:
                return _err("invalid_param", "query 不能为空")

            idx = _get_text_index()
            roots = list(idx.project_roots)
            logger.info("[fuzzy_search] caller=%s query=%r top_k=%s "
                        "type_filter=%s roots=%s",
                        caller, query, top_k, type_filter, roots)

            # ---- 3. 索引自检(脏标记 + mtime 兜底) ----
            rebuilt = idx.rebuild_if_needed()
            if rebuilt:
                logger.info("[fuzzy_search] 索引已自动重建,项数=%d",
                            idx._item_count)

            # ---- 4. 模糊匹配 ----
            t_match = time.perf_counter()
            items = idx.fuzzy(query, top_k=top_k, type_filter=type_filter)
            match_ms = (time.perf_counter() - t_match) * 1000.0

            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            logger.info("[fuzzy_search] 命中 %d 项, 匹配耗时 %.2fms, "
                        "总耗时 %.2fms",
                        len(items), match_ms, elapsed_ms)

            return {
                "status": "success",
                "items": items,
                "total": len(items),
                "elapsed_ms": round(elapsed_ms, 2),
                "query": query,
                "roots": roots,
                "rebuilt": rebuilt,
            }
        except Exception as exc:
            logger.exception("fuzzy_search 失败")
            return _err("internal_error", str(exc), t_start)

    @staticmethod
    def image_search(image_b64: str, top_k: int = 20,
                     threshold: int = DEFAULT_THRESHOLD,
                     caller: str = "anonymous") -> Dict[str, Any]:
        """以图搜索(纯本地 pHash,无网络依赖)

        Args:
            image_b64: base64 编码的图片(支持 data URI 前缀)
            top_k: 最多返回多少项
            threshold: 汉明距离阈值(0~64,越小越严格)
            caller: 调用方标识
        """
        t_start = time.perf_counter()
        try:
            err = _check_caller(caller)
            if err is not None:
                return err
            if not _is_pil_available():
                return _err("pil_unavailable",
                            "Pillow 未安装,无法执行以图搜索", t_start)
            if not image_b64 or not str(image_b64).strip():
                return _err("invalid_param", "image_b64 不能为空", t_start)
            try:
                threshold_clamped = max(0, int(threshold))
            except (TypeError, ValueError):
                threshold_clamped = DEFAULT_THRESHOLD

            from .image_search import _decode_base64_image
            if _decode_base64_image(image_b64) is None:
                return _err("invalid_image", "图片数据无效或无法解码", t_start)

            _refresh_cached_items()
            img_idx = _get_image_index()
            items = img_idx.search(
                image_data=image_b64,
                top_k=top_k,
                threshold=threshold_clamped,
                resource_items=_last_resource_items,
            )
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            return {
                "status": "success",
                "items": items,
                "total": len(items),
                "elapsed_ms": round(elapsed_ms, 2),
                "threshold": threshold_clamped,
            }
        except Exception as exc:
            logger.exception("image_search 失败")
            return _err("internal_error", str(exc), t_start)

    @staticmethod
    def list_types(caller: str = "anonymous") -> Dict[str, Any]:
        """列出项目内出现的资源类型 + 计数"""
        try:
            err = _check_caller(caller)
            if err is not None:
                return err
            idx = _get_text_index()
            return {"status": "success", "types": idx.list_types()}
        except Exception as exc:
            logger.exception("list_types 失败")
            return _err("internal_error", str(exc))

    @staticmethod
    def rebuild_index(caller: str = "anonymous") -> Dict[str, Any]:
        """全量重建文本 + 图像索引(多根)"""
        try:
            err = _check_caller(caller)
            if err is not None:
                return err
            global _text_index, _image_index, _index_roots_signature
            roots = _resolve_search_roots()
            with _index_lock:
                _text_index = ResourceIndex(roots)
                stats = _text_index.rebuild()
                _index_roots_signature = tuple(roots)
                _refresh_cached_items()
                if _is_pil_available():
                    if _image_index is None:
                        _image_index = ImageIndex()
                    img_stats = _image_index.build(_last_resource_items)
                else:
                    img_stats = {"status": "skipped",
                                 "message": "Pillow 不可用"}
            return {
                "status": "success",
                "text": stats,
                "image": img_stats,
                "roots": roots,
            }
        except Exception as exc:
            logger.exception("rebuild_index 失败")
            return _err("internal_error", str(exc))

    @staticmethod
    def get_stats(caller: str = "anonymous") -> Dict[str, Any]:
        """返回当前索引统计信息"""
        try:
            err = _check_caller(caller)
            if err is not None:
                return err
            idx = _get_text_index()
            img_idx = _get_image_index() if _is_pil_available() else None
            return {
                "status": "success",
                "text": idx.stats(),
                "image": img_idx.stats() if img_idx else {"image_count": 0},
                "roots": list(idx.project_roots),
                "active_project": settings_manager.active_project_path,
                "allowed_callers": sorted(ALLOWED_CALLERS),
                "allowed_types": sorted(ALLOWED_SEARCH_TYPES),
            }
        except Exception as exc:
            logger.exception("get_stats 失败")
            return _err("internal_error", str(exc))

    @staticmethod
    def focus_actor(scene_name: str, actor_name: str,
                    caller: str = "anonymous") -> Dict[str, Any]:
        """桥接 SceneTools.focus_actor,供搜索结果"定位"按钮使用。"""
        try:
            err = _check_caller(caller)
            if err is not None:
                return err
            from plugins.SceneTools.main import SceneTools  # 延迟导入
            return SceneTools.focus_actor(scene_name, actor_name)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.exception("focus_actor 失败")
            return _err("internal_error", str(exc))

    @staticmethod
    def mark_index_dirty(reason: str = "external",
                         caller: str = "anonymous") -> Dict[str, Any]:
        """外部(资源导入/删除/重命名后)显式标记索引为脏"""
        try:
            err = _check_caller(caller)
            if err is not None:
                return err
            idx = _get_text_index()
            idx.mark_dirty(reason)
            return {"status": "success", "dirty": True, "reason": reason}
        except Exception as exc:
            logger.exception("mark_index_dirty 失败")
            return _err("internal_error", str(exc))

    # ==================================================================
    #  内部工具
    # ==================================================================

    @staticmethod
    def _get_pil_status() -> Dict[str, Any]:
        """查询 PIL 可用性 + 解析到的根(供上层诊断)"""
        return {
            "pil_available": _is_pil_available(),
            "roots": _resolve_search_roots(),
        }


# =============================================================================
#  内部工具
# =============================================================================


def _err(code: str, message: str,
         t_start: Optional[float] = None) -> Dict[str, Any]:
    """构造统一格式的错误响应 dict"""
    payload: Dict[str, Any] = {
        "status": "error",
        "code": code,
        "message": message,
        "items": [],
        "total": 0,
    }
    if t_start is not None:
        payload["elapsed_ms"] = round(
            (time.perf_counter() - t_start) * 1000.0, 2)
    return payload


# 模块级公共 API
__all__ = [
    "ResourceSearch",
    "ALLOWED_CALLERS",
    "DENIED_CALLERS",
    "ALLOWED_SEARCH_TYPES",
]
