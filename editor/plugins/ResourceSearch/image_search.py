"""
以图搜索模块 —— 纯本地感知哈希 (pHash) + 汉明距离

设计动机:
    1. 不依赖 AItool(遵循约束)
    2. 不依赖网络/云端模型(零配置可用)
    3. 仅依赖 PIL + numpy(已在 requirements.txt)

算法:
    pHash (Perceptual Hash) = 8x8 DCT 系数均值二值化 → 64-bit 整数
    距离度量: 汉明距离(bit 不同数)
    阈值:     distance ≤ 10 视为命中 (约 84% 相似)
"""
from __future__ import annotations

import base64
import io
import logging
import os
import threading
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:  # pragma: no cover
    _HAS_PIL = False
    Image = None  # type: ignore

# 默认汉明距离阈值(0~64)
DEFAULT_THRESHOLD = 10

# 缩放后尺寸
_HASH_SIZE = 32
# DCT 保留的低频尺寸
_DCT_SIZE = 8


def _is_pil_available() -> bool:
    return _HAS_PIL


def _decode_base64_image(data: str) -> Optional["Image.Image"]:
    """从 base64 / data URI / 本地路径统一解码为 PIL.Image"""
    if not _HAS_PIL:
        raise RuntimeError("Pillow 未安装,无法执行以图搜索")
    if not data:
        return None
    # 1) 本地路径
    if os.path.isfile(data):
        try:
            return Image.open(data)
        except Exception as exc:
            logger.warning("打开图片失败: %s (%s)", data, exc)
            return None
    # 2) data URI / 纯 base64
    s = data.strip()
    if s.startswith("data:"):
        s = s.split(",", 1)[1]
    try:
        raw = base64.b64decode(s, validate=False)
        return Image.open(io.BytesIO(raw))
    except Exception as exc:
        logger.warning("base64 图片解码失败: %s", exc)
        return None


def compute_phash(image: "Image.Image") -> int:
    """
    计算 64-bit pHash

    简化算法(避免引入 scipy):用 32x32 灰度图 + 8x8 离散余弦变换的近似实现
    实际工程上不要求严格的 DCT 数学正确性,只要"视觉相似→hash 接近"即可
    """
    if not _HAS_PIL:
        raise RuntimeError("Pillow 未安装")

    # 1) 转灰度 + 缩放
    img = image.convert("L").resize((_HASH_SIZE, _HASH_SIZE), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float32)

    # 2) 计算 8x8 DCT-II (使用矩阵乘法近似)
    n = _DCT_SIZE
    # 用线性投影把 32x32 缩到 8x8 (DCT 之前的均值池)
    block = arr.reshape(4, 8, 4, 8).mean(axis=(0, 2))

    # 3) 构造 DCT 矩阵
    factor = np.pi / (2.0 * n)
    basis = np.zeros((n, n), dtype=np.float32)
    for i in range(n):
        for j in range(n):
            basis[i, j] = np.cos((2 * j + 1) * i * factor)
    basis *= np.sqrt(2.0 / n)
    basis[0, :] *= 1.0 / np.sqrt(2.0)

    dct = basis @ block @ basis.T

    # 4) 取左上 8x8(去掉 DC 分量)
    dct_low = dct[1:, 1:]

    # 5) 中值二值化
    med = float(np.median(dct_low))
    bits = (dct_low > med).flatten()

    # 6) 折叠为 64-bit 整数
    h = 0
    for b in bits:
        h = (h << 1) | (1 if b else 0)
    return h


def hamming_distance(a: int, b: int) -> int:
    """计算两个 64-bit 整数的汉明距离"""
    return bin(a ^ b).count("1")


class ImageIndex:
    """图像感知哈希索引"""

    def __init__(self):
        self._lock = threading.RLock()
        # key = 资源相对路径, value = (phash, type, mtime)
        self._items: Dict[str, Tuple[int, str, float]] = {}

    def build(self, resource_items: List[dict]) -> dict:
        """
        从资源索引项构造图像索引。
        仅处理带 has_preview 标记且能找到 preview 实际文件的项。
        """
        if not _HAS_PIL:
            return {
                "status": "skipped",
                "message": "Pillow 未安装,跳过以图索引构建",
            }

        with self._lock:
            self._items.clear()
            indexed = 0
            skipped = 0
            for item in resource_items:
                if not item.get("has_preview"):
                    skipped += 1
                    continue
                full_path = item.get("full_path", "")
                d = os.path.dirname(full_path)
                preview = self._find_preview(d)
                if not preview:
                    skipped += 1
                    continue
                try:
                    with Image.open(preview) as im:
                        h = compute_phash(im)
                except Exception as exc:
                    logger.debug("计算 phash 失败: %s (%s)", preview, exc)
                    skipped += 1
                    continue
                self._items[item["path"]] = (h, item.get("type", ""), item.get("mtime", 0.0))
                indexed += 1
        logger.debug("以图索引构建完成: indexed=%d, skipped=%d", indexed, skipped)
        return {"status": "ok", "indexed": indexed, "skipped": skipped}

    def _find_preview(self, dir_path: str) -> Optional[str]:
        if not dir_path:
            return None
        for cand in ("preview.png", "preview.jpg", "thumbnail.png",
                     "thumb.png", "preview_0.png"):
            p = os.path.join(dir_path, cand)
            if os.path.isfile(p):
                return p
        return None

    def search(self, image_data: str, top_k: int = 20,
               threshold: int = DEFAULT_THRESHOLD,
               resource_items: Optional[List[dict]] = None) -> List[dict]:
        """
        用一张图片查询相似的资源。

        参数:
            image_data: base64 / data URI / 本地路径
            top_k:      返回前 K 个
            threshold:  汉明距离阈值,越小越严格
            resource_items: 资源元数据列表(用于回填 type/name/score 等)
        """
        img = _decode_base64_image(image_data)
        if img is None:
            return []

        try:
            query_hash = compute_phash(img)
        except Exception as exc:
            logger.error("phash 计算失败: %s", exc)
            return []

        # resource_items 用作 name/lookup
        meta: Dict[str, dict] = {}
        if resource_items:
            for r in resource_items:
                meta[r.get("path", "")] = r

        results: List[dict] = []
        with self._lock:
            for path, (h, t, mtime) in self._items.items():
                dist = hamming_distance(query_hash, h)
                if dist > threshold:
                    continue
                base = meta.get(path, {})
                score = max(0.0, 1.0 - dist / 64.0)
                results.append({
                    "name": base.get("name", os.path.splitext(os.path.basename(path))[0]),
                    "path": path,
                    "type": base.get("type", t),
                    "type_label": base.get("type_label", "其他"),
                    "ext": base.get("ext", ""),
                    "size": base.get("size", 0),
                    "mtime": base.get("mtime", mtime),
                    "has_preview": True,
                    "distance": dist,
                    "score": round(score, 4),
                })

        results.sort(key=lambda r: (r["distance"], r["name"]))
        return results[:max(1, top_k)]

    def stats(self) -> dict:
        with self._lock:
            return {"image_count": len(self._items)}
