from __future__ import annotations

import os
import sys
import importlib.util
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")))

_MODULE_PATH = Path(__file__).with_name("transform_grounding.py")
_SPEC = importlib.util.spec_from_file_location("transform_grounding_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

compute_ground_snap_position = _MODULE.compute_ground_snap_position
actor_world_aabb = _MODULE.actor_world_aabb
resolve_actor_overlaps = _MODULE.resolve_actor_overlaps
snap_actor_to_ground = _MODULE.snap_actor_to_ground


class FakeGeometry:
    def __init__(self, aabb):
        self._aabb = aabb

    def get_aabb(self):
        return list(self._aabb)


class FakeActor:
    _next_id = 0

    def __init__(self, position, scale, aabb, name=None):
        FakeActor._next_id += 1
        self.name = name or f"actor_{FakeActor._next_id}"
        self._position = list(position)
        self._scale = list(scale)
        self._geometry = FakeGeometry(aabb)

    def get_position(self):
        return list(self._position)

    def set_position(self, position):
        self._position = list(position)

    def get_scale(self):
        return list(self._scale)


def test_compute_ground_snap_after_scale_uses_local_aabb_bottom():
    actor = FakeActor(
        position=[0.0, 0.34, -8.0],
        scale=[1.5, 1.5, 1.5],
        aabb=[-0.5, -0.4, -0.5, 0.5, 0.6, 0.5],
    )
    corrected = compute_ground_snap_position(actor, ground_y=0.0, clearance=0.02)
    assert corrected is not None
    assert corrected[0] == 0.0
    assert corrected[2] == -8.0
    assert abs(corrected[1] - 0.62) < 1e-6
    print("[OK] ground snap computes Y from scaled local AABB bottom")


def test_snap_actor_to_ground_only_changes_y():
    actor = FakeActor(
        position=[2.0, 1.0, -3.0],
        scale=[2.0, 2.0, 2.0],
        aabb=[-1.0, -0.5, -1.0, 1.0, 0.5, 1.0],
    )
    final_pos = snap_actor_to_ground(actor, ground_y=0.5, clearance=0.05)
    assert final_pos == actor.get_position()
    assert final_pos is not None
    assert final_pos[0] == 2.0
    assert final_pos[2] == -3.0
    assert abs((final_pos[1] + (-0.5 * 2.0)) - 0.55) < 1e-6
    print("[OK] ground snap preserves X/Z and rests bottom on requested ground")


def test_actor_world_aabb_applies_position_and_scale():
    actor = FakeActor(
        position=[10.0, 2.0, -3.0],
        scale=[2.0, 3.0, 4.0],
        aabb=[-1.0, -0.5, -0.25, 1.0, 0.5, 0.25],
    )
    assert actor_world_aabb(actor) == [8.0, 0.5, -4.0, 12.0, 3.5, -2.0]
    print("[OK] world AABB converts local geometry bounds through transform")


def test_resolve_actor_overlaps_nudges_current_actor_only():
    moving = FakeActor(
        position=[0.0, 0.0, 0.0],
        scale=[1.0, 1.0, 1.0],
        aabb=[-1.0, 0.0, -1.0, 1.0, 1.0, 1.0],
    )
    fixed = FakeActor(
        position=[0.5, 0.0, 0.0],
        scale=[1.0, 1.0, 1.0],
        aabb=[-1.0, 0.0, -1.0, 1.0, 1.0, 1.0],
    )
    before_fixed = fixed.get_position()
    result = resolve_actor_overlaps(moving, [fixed], clearance=0.1)
    assert result["changed"] is True
    assert moving.get_position() != [0.0, 0.0, 0.0]
    assert fixed.get_position() == before_fixed
    moved_aabb = actor_world_aabb(moving)
    fixed_aabb = actor_world_aabb(fixed)
    assert min(moved_aabb[3], fixed_aabb[3]) - max(moved_aabb[0], fixed_aabb[0]) <= 0.0 or \
        min(moved_aabb[5], fixed_aabb[5]) - max(moved_aabb[2], fixed_aabb[2]) <= 0.0
    print("[OK] overlap resolver nudges only the current actor")


if __name__ == "__main__":
    test_compute_ground_snap_after_scale_uses_local_aabb_bottom()
    test_snap_actor_to_ground_only_changes_y()
    test_actor_world_aabb_applies_position_and_scale()
    test_resolve_actor_overlaps_nudges_current_actor_only()
    print("\n=== transform grounding ALL PASS ===")
