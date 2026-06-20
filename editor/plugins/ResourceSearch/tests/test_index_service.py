import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from plugins.ResourceSearch.index_service import ResourceIndexService
from plugins.ResourceSearch.indexer import ResourceIndex


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ResourceIndexSnapshotTests(unittest.TestCase):
    def test_fingerprint_check_does_not_construct_an_index(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "Asset.fbx").write_bytes(b"mesh")

            with patch.object(
                ResourceIndex,
                "__init__",
                side_effect=AssertionError("unexpected ResourceIndex construction"),
            ):
                fingerprint = ResourceIndex.filesystem_fingerprint([str(root)])

            self.assertTrue(fingerprint)

    def test_runtime_editor_and_cache_directories_are_not_indexed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "assets").mkdir()
            (root / "assets" / "Visible.fbx").write_bytes(b"mesh")
            (root / "CabbageEditor").mkdir()
            (root / "CabbageEditor" / "internal.py").write_text(
                "secret = True",
                encoding="utf-8",
            )
            (root / "cache").mkdir()
            (root / "cache" / "Generated.obj").write_bytes(b"cache")

            index = ResourceIndex([str(root)])
            stats = index.rebuild()

            self.assertEqual(1, stats["count"])
            self.assertEqual(
                ["Visible"],
                [item["name"] for item in index.fuzzy("", top_k=10)],
            )

    def test_snapshot_round_trip_preserves_search_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "BlueBall.fbx").write_bytes(b"mesh")

            original = ResourceIndex([str(root)])
            original.rebuild()
            restored = ResourceIndex.from_snapshot(
                [str(root)],
                original.to_snapshot(),
            )

            results = restored.fuzzy("blue", top_k=10)
            self.assertEqual(["BlueBall"], [item["name"] for item in results])
            self.assertEqual(original.fingerprint(), restored.fingerprint())

    def test_snapshot_rejects_paths_outside_roots(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = {
                "roots": [str(root)],
                "fingerprint": "",
                "items": [{
                    "name": "escape",
                    "path": "../escape.fbx",
                    "root": str(root),
                    "type": "model",
                    "ext": ".fbx",
                }],
            }

            with self.assertRaises(ValueError):
                ResourceIndex.from_snapshot([str(root)], payload)


class ResourceIndexServiceTests(unittest.TestCase):
    def test_cold_build_is_persisted_and_next_service_loads_immediately(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            cache = base / "cache"
            root.mkdir()
            (root / "Ball.fbx").write_bytes(b"mesh")

            first = ResourceIndexService(
                lambda: [str(root)],
                cache_dir=cache,
                poll_interval=60.0,
            )
            try:
                status = first.prepare()
                self.assertFalse(status["ready"])
                self.assertTrue(first.wait_until_ready())
                self.assertTrue(list(cache.glob("*.json")))
            finally:
                first.shutdown()

            second = ResourceIndexService(
                lambda: [str(root)],
                cache_dir=cache,
                poll_interval=60.0,
            )
            try:
                status = second.prepare()
                self.assertTrue(status["ready"])
                self.assertEqual(
                    "Ball",
                    second.current_index().fuzzy("ball", top_k=1)[0]["name"],
                )
            finally:
                second.shutdown()

    def test_refresh_keeps_published_index_searchable_until_atomic_swap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            root.mkdir()
            (root / "OldAsset.fbx").write_bytes(b"old")
            service = ResourceIndexService(
                lambda: [str(root)],
                cache_dir=base / "cache",
                poll_interval=60.0,
            )
            try:
                service.prepare()
                self.assertTrue(service.wait_until_ready())
                (root / "NewAsset.fbx").write_bytes(b"new")

                entered = threading.Event()
                release = threading.Event()
                original_rebuild = ResourceIndex.rebuild

                def blocked_rebuild(index):
                    entered.set()
                    release.wait(2.0)
                    return original_rebuild(index)

                with patch.object(ResourceIndex, "rebuild", blocked_rebuild):
                    service.request_refresh(force=True)
                    self.assertTrue(entered.wait(2.0))
                    current = service.current_index()
                    self.assertEqual(
                        ["OldAsset"],
                        [item["name"] for item in current.fuzzy("old", top_k=5)],
                    )
                    release.set()
                    self.assertTrue(service.wait_until_ready())

                names = [
                    item["name"]
                    for item in service.current_index().fuzzy("asset", top_k=5)
                ]
                self.assertEqual(["NewAsset", "OldAsset"], names)
            finally:
                release.set()
                service.shutdown()

    def test_polling_detects_deletion_and_root_switch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            first_root = base / "first"
            second_root = base / "second"
            first_root.mkdir()
            second_root.mkdir()
            removed = first_root / "Removed.fbx"
            removed.write_bytes(b"old")
            (second_root / "Second.fbx").write_bytes(b"new")
            active_roots = [str(first_root)]

            service = ResourceIndexService(
                lambda: list(active_roots),
                cache_dir=base / "cache",
                poll_interval=0.05,
            )
            try:
                service.prepare()
                self.assertTrue(service.wait_until_ready())
                removed.unlink()
                self.assertTrue(wait_for(
                    lambda: (
                        service.status()["state"] == "ready"
                        and not service.current_index().fuzzy("removed", top_k=5)
                    )
                ))

                active_roots[:] = [str(second_root)]
                service.request_refresh()
                self.assertTrue(service.wait_until_ready())
                self.assertEqual(
                    ["Second"],
                    [
                        item["name"]
                        for item in service.current_index().fuzzy("second", top_k=5)
                    ],
                )
            finally:
                service.shutdown()

    def test_disable_auto_rebuild_env_uses_cache_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            root = base / "project"
            root.mkdir()
            (root / "Asset.fbx").write_bytes(b"mesh")

            service = ResourceIndexService(
                lambda: [str(root)],
                cache_dir=base / "cache",
                poll_interval=60.0,
            )
            try:
                with patch.dict("os.environ", {"CORONA_RESOURCESEARCH_DISABLE_AUTO_REBUILD": "1"}):
                    status = service.prepare()
                    self.assertFalse(status["ready"])
                    self.assertEqual("idle", status["state"])
                    self.assertTrue(status["auto_rebuild_disabled"])

                    with patch.object(
                        ResourceIndex,
                        "rebuild",
                        side_effect=AssertionError("unexpected rebuild"),
                    ):
                        refresh_status = service.request_refresh(force=True)
                    self.assertFalse(refresh_status["ready"])
                    self.assertEqual("idle", refresh_status["state"])
            finally:
                service.shutdown()


if __name__ == "__main__":
    unittest.main()
