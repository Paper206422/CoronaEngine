from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_BOUNDARY_ALIASES = {
    "_terrain_boundary",
    "__terrain_boundary",
    "__terrain_fence",
    "terrain_boundary",
    "terrain boundary",
    "\u5730\u5f62\u8fb9\u754c",
    "\u8fb9\u754c",
    "\u6805\u680f",
    "\u56f4\u680f",
    "\u6728\u6805\u680f",
}

_TERRAIN_ALIASES = {
    "__room_terrain",
    "__terrain",
    "terrain",
    "ground",
    "\u5730\u5f62",
    "\u5730\u9762",
    "\u5730\u8868",
}


@dataclass
class TerrainComponentProfile:
    scene_key: str
    terrain_spec: dict[str, Any] = field(default_factory=dict)
    boundary_spec: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "scene_key": self.scene_key,
            "terrain_spec": dict(self.terrain_spec),
            "boundary_spec": dict(self.boundary_spec),
        }


class TerrainComponentResolver:
    """Resolve scene-level terrain/boundary semantics without hard-wiring one demo."""

    def derive(self, text: str = "", *, scene_type: str = "") -> TerrainComponentProfile:
        raw = str(text or "")
        lower = raw.lower()
        is_market = "\u96c6\u5e02" in raw or "market" in lower
        is_night = "\u591c" in raw or "night" in lower
        is_fantasy_like = any(word in raw for word in ("\u5e7b\u60f3", "\u795e\u79d8", "\u706f\u7b3c", "\u706f\u5149", "\u6e29\u6696")) or "fantasy" in lower
        if (is_market and (is_night or is_fantasy_like)) or "fantasy night market" in lower:
            return TerrainComponentProfile(
                scene_key="fantasy_night_market",
                terrain_spec={
                    "type": "outdoor_market_ground",
                    "surface": "stone_path_with_soft_grass_edges",
                    "walkable": True,
                    "detail_pattern": "paving_grid",
                },
                boundary_spec={
                    "type": "low_decorative_boundary",
                    "kind": "fence",
                    "material": "wood",
                    "style": "vine_wood_lantern",
                    "height": 0.55,
                    "coverage": "partial",
                    "shape": "open_front_market_path",
                    "avoid": ["tall ranch fence", "grassland yurt fence"],
                },
            )
        if any(word in raw for word in ("\u8499\u53e4\u5305", "\u8349\u539f", "yurt", "grassland")):
            return TerrainComponentProfile(
                scene_key="grassland_yurt",
                terrain_spec={
                    "type": "rolling_grassland",
                    "surface": "grass",
                    "walkable": True,
                },
                boundary_spec={
                    "type": "camp_boundary",
                    "kind": "fence",
                    "material": "wood",
                    "style": "low grassland camp fence",
                    "height": 1.1,
                    "coverage": "ring",
                },
            )
        if "\u5ba4\u5185" in raw and "\u5ba4\u5916" not in raw and scene_type == "indoor":
            return TerrainComponentProfile(
                scene_key="indoor_room",
                terrain_spec={"type": "interior_floor", "surface": "neutral", "walkable": True},
                boundary_spec={"type": "room_walls", "coverage": "enclosure"},
            )
        return TerrainComponentProfile(
            scene_key=scene_type or "mixed",
            terrain_spec={"type": "neutral_ground", "surface": "neutral", "walkable": True},
            boundary_spec={"type": "contextual_boundary", "coverage": "optional"},
        )

    @staticmethod
    def canonical_actor_id(value: str) -> str:
        key = str(value or "").strip().lower()
        if key in _BOUNDARY_ALIASES:
            return "__terrain_boundary"
        if key in _TERRAIN_ALIASES:
            return "__room_terrain"
        return str(value or "").strip()


def canonical_actor_id(value: str) -> str:
    return TerrainComponentResolver.canonical_actor_id(value)


__all__ = ["TerrainComponentProfile", "TerrainComponentResolver", "canonical_actor_id"]
