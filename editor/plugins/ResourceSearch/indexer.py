"""
资源索引模块 —— 内存倒排索引 + 项目元数据缓存

职责:
    1. 扫描项目目录 (assets/, Scene/, Actor/, 根目录 *.actor/*.scene) 构建索引
    2. 提供子串/编辑距离/类型/路径多维度匹配
    3. 缓存缩略图路径、文件大小、修改时间等元数据
    4. 监听 actor-change / scene-tree-changed 增量刷新
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# 支持扫描的资源扩展名(按类型分组)
_EXT_TYPE_MAP = {
    "model": {".obj", ".fbx", ".3ds", ".dae", ".gltf", ".glb", ".usd",
              ".usda", ".usdc", ".usdz", ".stl", ".ply"},
    "multimedia": {".mp4", ".avi", ".mov", ".webm", ".mkv", ".mp3", ".wav",
                   ".ogg", ".flac", ".png", ".jpg", ".jpeg", ".bmp", ".webp"},
    "scene": {".scene"},
    "actor": {".actor"},
    "terrain": {".terrain"},
    "script": {".py"},
}

# 类型 → 友好中文名
_TYPE_LABEL = {
    "model": "模型",
    "multimedia": "多媒体",
    "scene": "场景",
    "actor": "单位",
    "terrain": "地形",
    "script": "脚本",
    "other": "其他",
}

# 扫描根目录(项目根下)
# 兼容旧项目:仍优先扫描这些目录,但不再作为硬白名单
_SCAN_SUBDIRS = ("assets", "Scene", "Actor", "Scripts", "Terrain")

# 扫描忽略目录(全路径段匹配,大小写敏感)
_IGNORE_DIRS = {".git", "__pycache__", "node_modules", "dist", "build",
                "__MACOSX", ".vscode", ".idea", ".venv", "venv", "Backup",
                # 常见生成目录(Unity / UE / VS)
                "Library", "Temp", "tmp", "Logs", "log",
                "obj", "bin", "DerivedDataCache", "Intermediate", "Saved",
                ".cache", "Cache", "SavedGames", "Build"}


def _infer_type_by_ext(ext: str) -> str:
    ext = ext.lower()
    for type_name, exts in _EXT_TYPE_MAP.items():
        if ext in exts:
            return type_name
    return "other"


@dataclass
class ResourceItem:
    """单条资源索引项"""
    name: str              # 显示名(优先去掉扩展名)
    path: str              # 相对项目根的路径(正斜杠)
    full_path: str         # 绝对路径
    type: str              # model/actor/scene/multimedia/terrain/script/other
    ext: str               # 含点的扩展名,如 ".fbx"
    size: int              # 字节
    mtime: float           # 修改时间戳
    tags: List[str] = field(default_factory=list)  # 名称切词得到的标签
    pinyin: str = ""       # 中文名对应的拼音(便于拼音搜中文)
    has_preview: bool = False  # 是否同目录存在预览图

    def to_dict(self, score: float = 0.0) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "full_path": self.full_path,
            "type": self.type,
            "type_label": _TYPE_LABEL.get(self.type, "其他"),
            "ext": self.ext,
            "size": self.size,
            "mtime": self.mtime,
            "score": round(score, 4),
            "has_preview": self.has_preview,
        }


class ResourceIndex:
    """资源倒排索引(线程安全)"""

    # 文件名最大纳入索引的长度
    _MAX_NAME_LEN = 200
    # 递归扫描最大深度(避免异常嵌套导致失控)
    _MAX_SCAN_DEPTH = 10

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)
        self._items: Dict[str, ResourceItem] = {}  # key = rel path
        self._lock = threading.RLock()
        self._build_time: float = 0.0
        self._item_count: int = 0

    # ------------------------------------------------------------------ #
    #  构建 / 刷新
    # ------------------------------------------------------------------ #

    def rebuild(self) -> dict:
        """全量重建索引,返回统计信息

        扫描策略(2026-06 修复):
            不再依赖 _SCAN_SUBDIRS 硬白名单,改为从项目根开始递归扫描,
            仅跳过 _IGNORE_DIRS 中的目录。这样无论资源在 assets/、
            Models/、Prefabs/ 还是项目根下,都能被发现。
        """
        start = time.perf_counter()
        new_items: Dict[str, ResourceItem] = {}
        visited_dirs = 0

        try:
            visited_dirs = self._walk_project(self.project_root, new_items)
        except Exception as exc:
            logger.error("重建资源索引失败: %s", exc)
            return {"status": "error", "message": str(exc)}

        with self._lock:
            self._items = new_items
            self._build_time = time.perf_counter()
            self._item_count = len(new_items)

        elapsed = time.perf_counter() - start
        logger.info("资源索引已重建: %d 项, 扫描 %d 个目录, 耗时 %.3fs",
                    self._item_count, visited_dirs, elapsed)
        return {
            "status": "ok",
            "count": self._item_count,
            "scanned_dirs": visited_dirs,
            "elapsed_seconds": round(elapsed, 3),
        }

    def _walk_project(self, dir_abs: str, sink: Dict[str, ResourceItem],
                      current_depth: int = 0) -> int:
        """递归扫描整个项目根,返回访问过的目录数

        行为:
            1. 仅跳过 _IGNORE_DIRS 中列出的目录与以 . 开头的目录
            2. 文件级过滤仍由 _maybe_add_file 负责(仅索引已知扩展名)
            3. 达到 _MAX_SCAN_DEPTH 时停止下钻
        """
        if current_depth > self._MAX_SCAN_DEPTH:
            logger.debug("已达最大扫描深度 %d,停止: %s",
                         self._MAX_SCAN_DEPTH, dir_abs)
            return 0
        try:
            entries = os.scandir(dir_abs)
        except OSError as exc:
            logger.debug("无法读取目录 %s: %s", dir_abs, exc)
            return 0

        count = 1
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in _IGNORE_DIRS or entry.name.startswith("."):
                        continue
                    count += self._walk_project(entry.path, sink,
                                                current_depth + 1)
                else:
                    self._maybe_add_file(entry.path, self.project_root, sink)
            except OSError as exc:
                logger.debug("跳过 %s: %s", entry.path, exc)
                continue
        return count

    def _walk(self, dir_abs: str, sink: Dict[str, ResourceItem]):
        """兼容旧接口:递归扫描指定目录

        实际生产路径已改走 _walk_project;保留此方法以防外部代码引用。
        """
        self._walk_project(dir_abs, sink, current_depth=0)

    def _maybe_add_file(self, full_path: str, root: str,
                        sink: Dict[str, ResourceItem]):
        try:
            stat = os.stat(full_path)
        except OSError:
            return
        _, ext = os.path.splitext(full_path)
        type_name = _infer_type_by_ext(ext)
        if type_name == "other":
            return  # 不索引未知类型,减少噪音

        rel = os.path.relpath(full_path, root).replace("\\", "/")
        name = os.path.splitext(os.path.basename(full_path))[0]
        if len(name) > self._MAX_NAME_LEN:
            name = name[: self._MAX_NAME_LEN]

        tags = self._tokenize(name)
        pinyin = self._to_pinyin(name)
        has_preview = self._check_preview(full_path)

        sink[rel] = ResourceItem(
            name=name,
            path=rel,
            full_path=full_path,
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
        for cand in ("preview.png", "preview.jpg", "thumbnail.png",
                     "thumb.png", "preview_0.png"):
            if os.path.isfile(os.path.join(d, cand)):
                return True
        return False

    # ------------------------------------------------------------------ #
    #  搜索
    # ------------------------------------------------------------------ #

    def fuzzy(self, query: str, top_k: int = 20,
              type_filter: Optional[str] = None) -> List[dict]:
        """
        模糊搜索:综合 子串 + 编辑距离 + 拼音 三种匹配

        排序键:  (score desc, name asc)
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

            score = self._score_item(it, q, q_py)
            if score > 0:
                scored.append((score, it))

        scored.sort(key=lambda x: (-x[0], x[1].name.lower()))
        return [it.to_dict(score=s) for s, it in scored[:max(1, top_k)]]

    def _score_item(self, it: ResourceItem, q: str, q_py: str) -> float:
        """计算单条资源对 query 的得分,0 表示不命中"""
        name_lower = it.name.lower()
        # 1) 完全包含
        if q in name_lower:
            base = 1.0
            # 前缀匹配加权
            if name_lower.startswith(q):
                base = 1.0
            return base
        # 2) 标签命中
        for tag in it.tags:
            if q == tag.lower():
                return 0.9
        # 3) 拼音匹配
        if q_py and it.pinyin and (q_py in it.pinyin or it.pinyin.startswith(q_py)):
            return 0.85
        # 4) 编辑距离 (仅对较短 query)
        if len(q) <= 8 and self._edit_distance_leq(q, name_lower, 2):
            return 0.5
        return 0.0

    def _recent(self, top_k: int, type_filter: Optional[str]) -> List[dict]:
        with self._lock:
            snapshot = list(self._items.values())
        if type_filter:
            snapshot = [it for it in snapshot if it.type == type_filter]
        snapshot.sort(key=lambda it: -it.mtime)
        return [it.to_dict(score=0.0) for it in snapshot[:max(1, top_k)]]

    def list_types(self) -> List[dict]:
        """返回项目内出现的所有资源类型 + 计数"""
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
        with self._lock:
            return {
                "count": self._item_count,
                "build_time": self._build_time,
                "project_root": self.project_root,
            }

    # ------------------------------------------------------------------ #
    #  静态工具
    # ------------------------------------------------------------------ #

    _PUNCT_RE = re.compile(r"[\s_\-./\\()\[\]【】()（）,，。!?!?]+")
    _NON_WORD_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")

    @classmethod
    def _tokenize(cls, text: str) -> List[str]:
        if not text:
            return []
        # 简单分词:数字/英文/中文分别成段
        # 1) 拆分连续大写驼峰
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        # 2) 按非字母数字中文拆分
        parts = cls._PUNCT_RE.split(parts)
        # 3) 切中文
        result: List[str] = []
        for p in parts:
            if not p:
                continue
            # 把连续中文按 2 字一组切
            for i in range(0, len(p)):
                ch = p[i]
                if "\u4e00" <= ch <= "\u9fff":
                    if i + 1 < len(p) and "\u4e00" <= p[i + 1] <= "\u9fff":
                        result.append(p[i:i + 2])
                    else:
                        result.append(ch)
                else:
                    result.append(p[i:])
        return [t for t in result if t]

    _PINYIN_MAP: Dict[str, str] = {}  # 缓存以减少外部依赖

    @classmethod
    def _to_pinyin(cls, text: str) -> str:
        """拼音转换:无 pypinyin 时退化为字符 normalize"""
        if not text:
            return ""
        # 优先使用 pypinyin(若已安装)
        try:
            from pypinyin import lazy_pinyin  # type: ignore
            return "".join(lazy_pinyin(text))
        except ImportError:
            pass
        # 退化:用 unicodedata 归一化
        import unicodedata
        normalized = unicodedata.normalize("NFKD", text)
        return "".join(c for c in normalized if not unicodedata.combining(c))

    @staticmethod
    def _edit_distance_leq(a: str, b: str, max_d: int) -> bool:
        """快速判断 a 与 b 的编辑距离是否 ≤ max_d(剪枝优化)"""
        if abs(len(a) - len(b)) > max_d:
            return False
        # 滚动数组 Levenshtein
        la, lb = len(a), len(b)
        prev = list(range(lb + 1))
        cur = [0] * (lb + 1)
        for i in range(1, la + 1):
            cur[0] = i
            row_min = cur[0]
            for j in range(1, lb + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                cur[j] = min(
                    prev[j] + 1,        # 删除
                    cur[j - 1] + 1,      # 插入
                    prev[j - 1] + cost,  # 替换
                )
                if cur[j] < row_min:
                    row_min = cur[j]
            if row_min > max_d:
                return False
            prev, cur = cur, prev
        return prev[lb] <= max_d
