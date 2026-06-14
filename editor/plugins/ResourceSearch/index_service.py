"""Persistent, non-blocking lifecycle management for ResourceIndex."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from .indexer import ResourceIndex

logger = logging.getLogger(__name__)

_SNAPSHOT_VERSION = 2


def default_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "CoronaEngine" / "ResourceSearch"
    return Path.home() / ".cache" / "CoronaEngine" / "ResourceSearch"


class ResourceIndexService:
    """Keeps searches responsive while indexes are loaded and refreshed."""

    def __init__(
        self,
        roots_provider: Callable[[], Iterable[str]],
        cache_dir: Optional[Path] = None,
        poll_interval: float = 300.0,
    ):
        self._roots_provider = roots_provider
        self._cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self._poll_interval = poll_interval
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._index: Optional[ResourceIndex] = None
        self._signature: Optional[Tuple[str, ...]] = None
        self._state = "idle"
        self._error = ""
        self._generation = 0
        self._request_serial = 0
        self._force_rebuild = False
        self._needs_validation = False

    def prepare(self) -> dict:
        self._ensure_current_roots()
        self._start_worker()
        self._wake.set()
        return self.status()

    def current_index(self) -> Optional[ResourceIndex]:
        self.prepare()
        with self._lock:
            return self._index

    def request_refresh(self, force: bool = False) -> dict:
        self._ensure_current_roots()
        self._start_worker()
        with self._lock:
            self._request_serial += 1
            self._force_rebuild = self._force_rebuild or force
            if self._index is None:
                self._state = "indexing"
            else:
                self._state = "refreshing"
        self._wake.set()
        return self.status()

    def status(self) -> dict:
        with self._lock:
            index = self._index
            return {
                "state": self._state,
                "ready": index is not None,
                "refreshing": self._state in {"indexing", "refreshing"},
                "count": index.stats()["count"] if index else 0,
                "roots": list(self._signature or ()),
                "generation": self._generation,
                "error": self._error,
            }

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status()["ready"] and not self.status()["refreshing"]:
                return True
            time.sleep(0.01)
        return False

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)

    def _start_worker(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker,
                name="ResourceSearchIndex",
                daemon=True,
            )
            self._thread.start()

    def _ensure_current_roots(self) -> None:
        roots = tuple(self._normalize_roots(self._roots_provider()))
        with self._lock:
            if roots == self._signature:
                return

        loaded = self._load_snapshot(roots)
        with self._lock:
            if roots == self._signature:
                return
            self._signature = roots
            self._index = loaded
            self._generation += 1
            self._error = ""
            self._force_rebuild = loaded is None
            self._needs_validation = loaded is not None
            self._state = "refreshing" if loaded else "indexing"
        logger.debug(
            "[ResourceSearch] 根切换: roots=%s cache=%s",
            roots,
            "hit" if loaded else "miss",
        )
        if loaded is not None:
            logger.info(
                "[ResourceSearch] 索引就绪: items=%d source=cache roots=%d",
                loaded.stats()["count"],
                len(roots),
            )

    @staticmethod
    def _normalize_roots(roots: Iterable[str]) -> list[str]:
        result = []
        seen = set()
        for root in roots:
            absolute = os.path.abspath(root)
            key = os.path.normcase(absolute)
            if key in seen or not os.path.isdir(absolute):
                continue
            seen.add(key)
            result.append(absolute)
        return result

    def _worker(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(self._poll_interval)
            self._wake.clear()
            if self._stop.is_set():
                return
            with self._lock:
                request_serial = self._request_serial
            try:
                self._refresh_once()
            except Exception as exc:
                logger.exception("[ResourceSearch] 后台刷新失败")
                with self._lock:
                    self._error = str(exc)
                    self._state = "ready" if self._index else "error"
            finally:
                with self._lock:
                    request_arrived = request_serial != self._request_serial
                if request_arrived:
                    self._wake.set()

    def _refresh_once(self) -> None:
        self._ensure_current_roots()
        with self._lock:
            signature = self._signature or ()
            current = self._index
            force = self._force_rebuild
            validate = self._needs_validation
            self._force_rebuild = False
            self._needs_validation = False

        if current is not None and not force:
            fingerprint = ResourceIndex.filesystem_fingerprint(signature)
            if fingerprint == current.fingerprint():
                with self._lock:
                    if signature == self._signature:
                        self._state = "ready"
                        self._error = ""
                return
            if not validate:
                logger.debug("[ResourceSearch] 文件指纹变化,后台重建")

        fresh = ResourceIndex(signature)
        stats = fresh.rebuild()
        self._save_snapshot(signature, fresh)
        with self._lock:
            if signature != self._signature:
                return
            self._index = fresh
            self._generation += 1
            self._state = "ready"
            self._error = ""
        logger.info(
            "[ResourceSearch] 索引就绪: items=%d dirs=%d elapsed=%.3fs "
            "source=rebuild roots=%d",
            stats["count"],
            stats["scanned_dirs"],
            stats["elapsed_seconds"],
            len(stats["roots"]),
        )

    def _cache_path(self, roots: Tuple[str, ...]) -> Path:
        encoded = json.dumps(
            [os.path.normcase(root) for root in roots],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        key = hashlib.sha256(encoded).hexdigest()
        return self._cache_dir / f"{key}.json"

    def _load_snapshot(self, roots: Tuple[str, ...]) -> Optional[ResourceIndex]:
        path = self._cache_path(roots)
        try:
            with path.open("r", encoding="utf-8") as stream:
                envelope = json.load(stream)
            if envelope.get("version") != _SNAPSHOT_VERSION:
                return None
            return ResourceIndex.from_snapshot(roots, envelope["index"])
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.warning("[ResourceSearch] 忽略无效索引快照 %s: %s", path, exc)
            return None

    def _save_snapshot(
        self,
        roots: Tuple[str, ...],
        index: ResourceIndex,
    ) -> None:
        path = self._cache_path(roots)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(
            f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        envelope = {
            "version": _SNAPSHOT_VERSION,
            "created_at": time.time(),
            "index": index.to_snapshot(),
        }
        try:
            with temp.open("w", encoding="utf-8") as stream:
                json.dump(envelope, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
