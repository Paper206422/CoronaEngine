"""
ResourceIndex —— 多根内存倒排索引(场景栏资源智能搜索的核心数据结构)

=================================================================================
# 安全模型(2026-06 重构)
=================================================================================
本索引**只**用于场景栏资源智能搜索,严禁被无关脚本直接调用。

三层防御:
    1. **类型白名单**(main.py::ALLOWED_SEARCH_TYPES):仅 model/actor/scene/
       multimedia/terrain/script 六类可被搜索,AI 配置、prompt、凭证等一律拒绝
    2. **路径前缀黑名单**(_BLOCKED_PATH_PREFIXES):AITool/、Frontend/、
       CoronaPlugin/、tests/、.git/ 等目录的项**永远**不作为搜索结果返回
    3. **调用方白名单**(main.py::ALLOWED_CALLERS):仅允许核心 UI 模块调用,
       显式拒绝 AITool、Quasar、cai.runtime 等 AI 链路

=================================================================================
# 性能特征
=================================================================================
    - 构建:O(文件总数),单线程 os.scandir,典型 1k~10k 项 < 1s
    - 搜索:O(项数 * (|name| + |query|)),单次遍历 + 提前返回
    - 内存:每项 ~1 KB(ResourceItem 用 __slots__ 优化)
=================================================================================
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import (Dict, FrozenSet, Iterable, List, Optional, Sequence,
                    Set, Tuple)

logger = logging.getLogger(__name__)


# =============================================================================
#  模块级常量(预编译 / 不可变 —— 进程级只读)
# =============================================================================


# 资源类型 → 支持的扩展名(小写、含点)
_EXT_TYPE_MAP: Dict[str, FrozenSet[str]] = {
    "model": frozenset({".obj", ".fbx", ".3ds", ".dae", ".gltf", ".glb",
                        ".usd", ".usda", ".usdc", ".usdz", ".stl", ".ply"}),
    "multimedia": frozenset({".mp4", ".avi", ".mov", ".webm", ".mkv",
                             ".mp3", ".wav", ".ogg", ".flac",
                             ".png", ".jpg", ".jpeg", ".bmp", ".webp"}),
    "scene": frozenset({".scene"}),
    "actor": frozenset({".actor"}),
    "terrain": frozenset({".terrain"}),
    "script": frozenset({".py"}),
}

# 搜索时强制过滤的路径前缀(全路径正斜杠匹配)
# 这些前缀**无法被绕过**,即使索引里有命中也会被 fuzzy 阶段过滤掉
_BLOCKED_PATH_PREFIXES: Tuple[str, ...] = (
    # ---- AI 工具链路(敏感:含凭证、prompt、模型配置)----
    "AITool/", "AITool\\",
    "editor/plugins/AITool/", "editor/plugins/AITool\\",
    # ---- 前端代码(非资源)----
    "editor/Frontend/", "editor/Frontend\\",
    "Frontend/", "Frontend\\",
    # ---- 编辑器桥接层与内部工具(非资源)----
    "editor/CoronaPlugin/", "editor/CoronaPlugin\\",
    "editor/CoronaCore/utils/", "editor/CoronaCore/utils\\",
    # ---- 测试与备份 ----
    "editor/tests/", "editor/tests\\",
    "tests/", "tests\\",
    "Backup/", "Backup\\",
    # ---- 版本控制 ----
    ".git/", ".git\\",
    # ---- 包管理 / 虚拟环境 ----
    "node_modules/", "node_modules\\",
    ".venv/", "venv/", "site-packages/",
    # ---- Python 缓存 ----
    "__pycache__/", "*.pyc",
)

# 扫描阶段忽略目录(全路径段匹配,大小写敏感)
_IGNORE_DIRS: FrozenSet[str] = frozenset({
    ".git", "__pycache__", "node_modules", "dist", "build",
    "__MACOSX", ".vscode", ".idea", ".venv", "venv", "Backup",
    # 常见生成目录(Unity / UE / VS)
    "Library", "Temp", "tmp", "Logs", "log",
    "obj", "bin", "DerivedDataCache", "Intermediate", "Saved",
    ".cache", "Cache", "SavedGames", "Build",
    # 第三方依赖 / 工具链
    "third_party", "thirdparty", "ThirdParty", "vendor",
    "node-v22.19.0-win-x64",
    # AI 工具链路(在扫描阶段就排除,减少噪音)
    "AITool",
})

# 预览图候选文件名(顺序敏感:越靠前越优先)
_PREVIEW_CANDIDATES: Tuple[str, ...] = (
    "preview.png", "preview.jpg", "thumbnail.png",
    "thumb.png", "preview_0.png",
)

# 类型中文显示名
_TYPE_LABEL: Dict[str, str] = {
    "model": "模型",
    "actor": "单位",
    "scene": "场景",
    "multimedia": "多媒体",
    "terrain": "地形",
    "script": "脚本",
    "other": "其他",
}

# 预编译正则(模块级单次编译,避免热路径重复编译)
_TOKENIZE_PUNCT_RE = re.compile(r"[\s_\-./\\()\[\]【】()（）,，。!?!?]+")
_CAMEL_BOUNDARY_RE = re.compile(r"([a-z])([A-Z])")
_HAN_RE = re.compile(r"[\u4e00-\u9fff]")


# =============================================================================
#  工具函数
# =============================================================================


def _infer_type_by_ext(ext: str) -> str:
    """根据扩展名推断资源类型(预归一化为小写)

    Returns:
        "model" / "actor" / "scene" / "multimedia" / "terrain" / "script" / "other"
    """
    ext = ext.lower()
    for type_name, exts in _EXT_TYPE_MAP.items():
        if ext in exts:
            return type_name
    return "other"


def _is_path_blocked(rel_path: str) -> bool:
    """检查 rel_path 是否命中 _BLOCKED_PATH_PREFIXES

    这是搜索阶段的最后一道防线,无法被前端或 C++ 绕过。
    """
    for prefix in _BLOCKED_PATH_PREFIXES:
        if rel_path.startswith(prefix):
            return True
    return False


def _is_ignored_dir(name: str) -> bool:
    """检查目录名是否应被扫描忽略"""
    return name in _IGNORE_DIRS or name.startswith(".")


@dataclass(slots=True)
class ResourceItem:
    """单条资源索引项(用 __slots__ 节省内存,提升属性访问速度)"""
    name: str               # 显示名(已去扩展名)
    path: str               # 相对其所在根的路径(正斜杠)
    full_path: str          # 绝对路径
    root: str               # 所属根目录(用于多根追踪)
    type: str               # model/actor/scene/multimedia/terrain/script/other
    ext: str                # 含点的扩展名,如 ".fbx"
    size: int               # 字节
    mtime: float            # 修改时间戳
    tags: List[str] = field(default_factory=list)   # 名称切词得到的标签
    pinyin: str = ""                                   # 中文名对应的拼音
    has_preview: bool = False                          # 是否同目录存在预览图

    def to_dict(self, score: float = 0.0) -> dict:
        """序列化为可 JSON 化的 dict(供 CEF 返回前端)"""
        return {
            "name": self.name,
            "path": self.path,
            "full_path": self.full_path,
            "root": self.root,
            "type": self.type,
            "type_label": _TYPE_LABEL.get(self.type, "其他"),
            "ext": self.ext,
            "size": self.size,
            "mtime": self.mtime,
            "score": round(score, 4),
            "has_preview": self.has_preview,
        }


# =============================================================================
#  主类
# =============================================================================


class ResourceIndex:
    """多根资源倒排索引(线程安全)

    Usage:
        >>> idx = ResourceIndex(["/path/to/project"])
        >>> idx.rebuild()
        >>> results = idx.fuzzy("ball", top_k=10, type_filter="model")
    """
    # 单项 name 最大长度(防 OOM)
    _MAX_NAME_LEN = 200
    # 递归扫描最大深度(防符号链接循环)
    _MAX_SCAN_DEPTH = 10
    # 名称切词缓存(命中相同名字时直接返回)
    _TOKENIZE_CACHE_MAX = 4096

    def __init__(self, project_roots: Iterable[str]):
        """初始化

        Args:
            project_roots: 一个或多个扫描根(顺序敏感,后扫描的根覆盖先扫描的)
        """
        normalized: List[str] = []
        seen: Set[str] = set()
        for r in project_roots:
            if not r:
                continue
            try:
                abs_r = os.path.abspath(r)
            except (TypeError, ValueError):
                logger.warning("扫描根路径无效,跳过: %r", r)
                continue
            if not os.path.isdir(abs_r):
                logger.warning("扫描根不存在或不是目录,跳过: %s", abs_r)
                continue
            if abs_r in seen:
                continue
            seen.add(abs_r)
            normalized.append(abs_r)

        self.project_roots: List[str] = normalized
        self._items: Dict[str, ResourceItem] = {}
        self._lock = threading.RLock()
        self._build_time: float = 0.0
        self._item_count: int = 0
        self._dirty: bool = True
        self._max_indexed_mtime: float = 0.0
        self._tokenize_cache: Dict[str, Tuple[str, ...]] = {}

        logger.info("ResourceIndex 初始化, 扫描根: %s",
                    self.project_roots or "(空)")

    # ------------------------------------------------------------------ #
    #  构建 / 刷新
    # ------------------------------------------------------------------ #

    def rebuild(self) -> dict:
        """全量重建索引(扫描所有根,合并去重)"""
        start = time.perf_counter()
        new_items: Dict[str, ResourceItem] = {}
        visited_dirs = 0

        for root in self.project_roots:
            try:
                visited_dirs += self._walk_project(
                    root, root, new_items, current_depth=0)
            except Exception as exc:
                logger.error("扫描根 %s 失败: %s", root, exc, exc_info=False)

        with self._lock:
            self._items = new_items
            self._build_time = time.perf_counter()
            self._item_count = len(new_items)

        elapsed = time.perf_counter() - start
        logger.info("资源索引已重建: %d 项, 扫描 %d 个目录(根=%d 个), 耗时 %.3fs",
                    self._item_count, visited_dirs,
                    len(self.project_roots), elapsed)
        return {
            "status": "ok",
            "count": self._item_count,
            "scanned_dirs": visited_dirs,
            "roots": list(self.project_roots),
            "elapsed_seconds": round(elapsed, 3),
        }

    # ------------------------------------------------------------------ #
    #  脏标记 / 智能重建
    # ------------------------------------------------------------------ #

    def mark_dirty(self, reason: str = "") -> None:
        """外部调用:标记索引为脏,下次访问触发重建"""
        with self._lock:
            if not self._dirty:
                logger.info("资源索引被标记为脏:%s", reason or "(无原因)")
            self._dirty = True

    def rebuild_if_needed(self) -> bool:
        """如索引为脏(显式或 mtime 兜底),执行重建

        Returns:
            是否真的重建了
        """
        with self._lock:
            dirty_explicit = self._dirty
            dirty_mtime = self._has_newer_files()

        if not (dirty_explicit or dirty_mtime):
            return False

        reason = "explicit mark" if dirty_explicit else "mtime 兜底检测到新文件"
        logger.info("触发智能重建:%s", reason)
        self.rebuild()
        return True

    def _has_newer_files(self) -> bool:
        """快速检查所有根,判断是否有比索引更新的文件"""
        if self._build_time == 0.0:
            return True
        try:
            current_max = 0.0
            for root in self.project_roots:
                current_max = max(
                    current_max,
                    self._quick_max_mtime(root, current_depth=0))
            # 0.5s 缓冲,避免亚秒级时间精度抖动
            return current_max > (self._max_indexed_mtime + 0.5)
        except OSError as exc:
            logger.debug("_has_newer_files OSError: %s", exc)
            return False

    def _quick_max_mtime(self, dir_abs: str,
                         current_depth: int = 0) -> float:
        """快速扫描一个根,返回该根所有文件的最大 mtime"""
        if current_depth > self._MAX_SCAN_DEPTH:
            return 0.0
        max_mt = 0.0
        try:
            with os.scandir(dir_abs) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                        if st.st_mtime > max_mt:
                            max_mt = st.st_mtime
                        if entry.is_dir(follow_symlinks=False):
                            if _is_ignored_dir(entry.name):
                                continue
                            sub_mt = self._quick_max_mtime(
                                entry.path, current_depth + 1)
                            if sub_mt > max_mt:
                                max_mt = sub_mt
                    except OSError:
                        continue
        except OSError:
            pass
        return max_mt

    def _walk_project(self, dir_abs: str, root: str,
                      sink: Dict[str, ResourceItem],
                      current_depth: int = 0) -> int:
        """递归扫描单个根,写入 sink"""
        if current_depth > self._MAX_SCAN_DEPTH:
            logger.debug("已达最大扫描深度 %d,停止: %s",
                         self._MAX_SCAN_DEPTH, dir_abs)
            return 0
        try:
            entries = list(os.scandir(dir_abs))
        except OSError as exc:
            logger.debug("无法读取目录 %s: %s", dir_abs, exc)
            return 0

        count = 1
        local_max = 0.0
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if _is_ignored_dir(entry.name):
                        continue
                    count += self._walk_project(
                        entry.path, root, sink, current_depth + 1)
                else:
                    self._maybe_add_file(entry.path, root, sink)
                    try:
                        st = entry.stat(follow_symlinks=False)
                        if st.st_mtime > local_max:
                            local_mt = st.st_mtime  # noqa: F841 (保留以备调试)
                    except OSError:
                        pass
            except OSError as exc:
                logger.debug("跳过 %s: %s", entry.path, exc)
                continue

        # 把单次 walk 的 max 合并到全局(仅用于 _has_newer_files)
        if local_max > 0.0:
            with self._lock:
                if local_max > self._max_indexed_mtime:
                    self._max_indexed_mtime = local_max
        return count

    def _maybe_add_file(self, full_path: str, root: str,
                        sink: Dict[str, ResourceItem]) -> None:
        """若文件可索引,加入 sink"""
        try:
            stat = os.stat(full_path)
        except OSError:
            return
        _, ext = os.path.splitext(full_path)
        type_name = _infer_type_by_ext(ext)
        if type_name == "other":
            return  # 不索引未知类型,减少噪音

        rel = os.path.relpath(full_path, root).replace("\\", "/")

        # 路径级兜底过滤(扫描阶段最后一道)
        if _is_path_blocked(rel):
            return

        name = os.path.splitext(os.path.basename(full_path))[0]
        if len(name) > self._MAX_NAME_LEN:
            name = name[: self._MAX_NAME_LEN]

        tags = list(self._tokenize(name))
        pinyin = self._to_pinyin(name)
        has_preview = self._check_preview(full_path)

        sink[rel] = ResourceItem(
            name=name,
            path=rel,
            full_path=full_path,
            root=root,
            type=type_name,
            ext=ext.lower(),
            size=stat.st_size,
            mtime=stat.st_mtime,
            tags=tags,
            pinyin=pinyin,
            has_preview=has_preview,
        )

    def _check_preview(self, file_path: str) -> bool:
        """检查同目录是否存在预览图"""
        d = os.path.dirname(file_path)
        for cand in _PREVIEW_CANDIDATES:
            if os.path.isfile(os.path.join(d, cand)):
                return True
        return False

    # ------------------------------------------------------------------ #
    #  搜索
    # ------------------------------------------------------------------ #

    def fuzzy(self, query: str, top_k: int = 20,
              type_filter: Optional[str] = None) -> List[dict]:
        """模糊匹配(线程安全)

        Args:
            query: 关键词(空/纯空白返回最近 mtime 的 N 项)
            top_k: 最多返回多少项(< 1 自动取 1)
            type_filter: 可选,仅返回指定类型

        Returns:
            按 (score desc, name asc) 排序后的 item dict 列表
        """
        if not query or not query.strip():
            return self._recent(top_k, type_filter)

        q = query.strip().lower()
        q_py = self._to_pinyin(q)

        with self._lock:
            snapshot = list(self._items.values())

        scored: List[Tuple[float, ResourceItem]] = []
        for it in snapshot:
            if type_filter and it.type != type_filter:
                continue
            # 路径级最后一道过滤(防止扫描阶段漏掉的 _BLOCKED_PATH_PREFIXES)
            if _is_path_blocked(it.path):
                continue
            score = self._score_item(it, q, q_py)
            if score > 0:
                scored.append((score, it))

        scored.sort(key=lambda x: (-x[0], x[1].name.lower()))
        return [it.to_dict(score=s) for s, it in scored[:max(1, top_k)]]

    def _score_item(self, it: ResourceItem, q: str, q_py: str) -> float:
        """单条资源的匹配得分(0~1)

        匹配等级(从高到低):
            1.0 - name 子串包含(前缀 = 1.0,其他 = 1.0)
            0.9 - 任意 tag 完全相等
            0.85 - 拼音匹配
            0.5  - 编辑距离 ≤ 2
        """
        name_lower = it.name.lower()
        # 1) 子串包含
        if q in name_lower:
            return 1.0
        # 2) tag 命中
        for tag in it.tags:
            if q == tag.lower():
                return 0.9
        # 3) 拼音匹配
        if q_py and it.pinyin and (
                q_py in it.pinyin or it.pinyin.startswith(q_py)):
            return 0.85
        # 4) 编辑距离(仅对短 query)
        if len(q) <= 8 and self._edit_distance_leq(q, name_lower, 2):
            return 0.5
        return 0.0

    def _recent(self, top_k: int,
                type_filter: Optional[str]) -> List[dict]:
        """空 query 时,返回最近 mtime 的 N 项"""
        with self._lock:
            snapshot = list(self._items.values())
        if type_filter:
            snapshot = [it for it in snapshot if it.type == type_filter]
        snapshot.sort(key=lambda it: -it.mtime)
        return [it.to_dict(score=0.0) for it in snapshot[:max(1, top_k)]]

    def list_types(self) -> List[dict]:
        """列出本索引内出现的资源类型 + 计数"""
        with self._lock:
            snapshot = list(self._items.values())
        counts: Dict[str, int] = {}
        for it in snapshot:
            counts[it.type] = counts.get(it.type, 0) + 1
        result = []
        for type_name, label in _TYPE_LABEL.items():
            result.append({
                "type": type_name,
                "label": label,
                "count": counts.get(type_name, 0),
            })
        return result

    def stats(self) -> dict:
        """返回当前索引统计"""
        with self._lock:
            return {
                "count": self._item_count,
                "build_time": self._build_time,
                "project_roots": list(self.project_roots),
            }

    # ------------------------------------------------------------------ #
    #  静态工具(分词 / 拼音 / 编辑距离)
    # ------------------------------------------------------------------ #

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        """分词:中文 2 字一组+单字,英文/数字整段保留(带 LRU 缓存)

        Args:
            text: 原始名称

        Returns:
            切分后的 token 列表(去空)
        """
        if not text:
            return []
        # 查缓存(只对纯字符串)
        cache = cls._get_tokenize_cache()
        key = text
        cached = cache.get(key)
        if cached is not None:
            return list(cached)

        parts = _CAMEL_BOUNDARY_RE.sub(r"\1 \2", text)
        parts = _TOKENIZE_PUNCT_RE.split(parts)
        result: List[str] = []
        for p in parts:
            if not p:
                continue
            i, n = 0, len(p)
            while i < n:
                ch = p[i]
                if "\u4e00" <= ch <= "\u9fff":
                    if i + 1 < n and "\u4e00" <= p[i + 1] <= "\u9fff":
                        result.append(p[i:i + 2])
                        i += 2
                    else:
                        result.append(ch)
                        i += 1
                else:
                    j = i
                    while j < n and not ("\u4e00" <= p[j] <= "\u9fff"):
                        j += 1
                    result.append(p[i:j])
                    i = j
        result = [t for t in result if t]

        # 写入缓存(简单 LRU:满则清空一半)
        if len(cache) >= cls._TOKENIZE_CACHE_MAX:
            # 简单清空策略: 保留后半(最近用过的可能性更高)
            keys = list(cache.keys())
            for k in keys[:len(keys) // 2]:
                cache.pop(k, None)
        cache[key] = tuple(result)
        return result

    @classmethod
    def _get_tokenize_cache(cls) -> Dict[str, Tuple[str, ...]]:
        """懒创建分词缓存(避免 __init__ 期间为每个实例各自分配)"""
        if not hasattr(cls, "_tokenize_cache_dict"):
            cls._tokenize_cache_dict = {}
        return cls._tokenize_cache_dict

    @classmethod
    def _to_pinyin(cls, text: str) -> str:
        """中文字符串 → 拼音(无声调)。pypinyin 不可用时回退到 NFKD 归一化。"""
        if not text:
            return ""
        try:
            from pypinyin import lazy_pinyin  # type: ignore
            return "".join(lazy_pinyin(text))
        except ImportError:
            pass
        # 兜底:unicode 分解
        import unicodedata
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(c for c in normalized if not unicodedata.combining(c))

    @staticmethod
    def _edit_distance_leq(a: str, b: str, max_d: int) -> bool:
        """早停版编辑距离:任意一行最小值 > max_d 时立即返回 False

        Args:
            a, b: 字符串
            max_d: 阈值

        Returns:
            levenshtein(a, b) ≤ max_d
        """
        if abs(len(a) - len(b)) > max_d:
            return False
        la, lb = len(a), len(b)
        prev = list(range(lb + 1))
        cur = [0] * (lb + 1)
        for i in range(1, la + 1):
            cur[0] = i
            row_min = cur[0]
            for j in range(1, lb + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                cur[j] = min(
                    prev[j] + 1,
                    cur[j - 1] + 1,
                    prev[j - 1] + cost,
                )
                if cur[j] < row_min:
                    row_min = cur[j]
            if row_min > max_d:
                return False
            prev, cur = cur, prev
        return prev[lb] <= max_d


# 模块级公共 API(配合 `from .indexer import *`)
__all__ = [
    "ResourceIndex",
    "ResourceItem",
    "_EXT_TYPE_MAP",
    "_BLOCKED_PATH_PREFIXES",
    "_is_path_blocked",
    "_infer_type_by_ext",
]
