"""M2-F5 decompose snapshot checker.

Usage:
    python docs/probes/m2_f5_snapshot_check.py <snapshot.json> [scene_kind]

scene_kind:
    grass_yurt | church | observatory | outdoor_market | auto

This script is read-only. It checks the JSON saved by
SceneComposer._save_zone_decompose_snapshot and prints PASS/WARN/FAIL lines for
the fields that M2-F5 must inspect before visual review.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List


def _load(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _zones(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    zones = payload.get("normalized_zones")
    return zones if isinstance(zones, list) else []


def _aspects(zone: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for aspect in zone.get("aspects") or []:
        if not isinstance(aspect, dict):
            continue
        cap = str(aspect.get("capability") or "")
        params = aspect.get("params") if isinstance(aspect.get("params"), dict) else {}
        if cap and cap not in result:
            result[cap] = params
    return result


def _all_aspects(zones: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    for zone in zones:
        for cap, params in _aspects(zone).items():
            result.setdefault(cap, []).append(params)
    return result


def _say(level: str, msg: str) -> None:
    print(f"[{level}] {msg}")


def _has_cap(zones: List[Dict[str, Any]], cap: str) -> bool:
    return any(cap in _aspects(zone) for zone in zones)


def _first_params(zones: List[Dict[str, Any]], cap: str) -> Dict[str, Any]:
    for zone in zones:
        params = _aspects(zone).get(cap)
        if params is not None:
            return params
    return {}


def _infer_scene_kind(payload: Dict[str, Any], zones: List[Dict[str, Any]]) -> str:
    text = (payload.get("prompt") or "").lower()
    names = " ".join(str(z.get("name") or "") for z in zones).lower()
    joined = text + " " + names
    if any(k in joined for k in ("教堂", "church", "chapel")):
        return "church"
    if any(k in joined for k in ("火山", "观测站", "volcano", "observatory")):
        return "observatory"
    if any(k in joined for k in ("集市", "market", "广场", "营地")) and not any(
        (z.get("enclosure") or "") == "shell" for z in zones
    ):
        return "outdoor_market"
    if any(k in joined for k in ("蒙古包", "草原", "yurt", "grassland")):
        return "grass_yurt"
    return "auto"


def _check_common(payload: Dict[str, Any], zones: List[Dict[str, Any]]) -> None:
    _say("INFO", f"snapshot={payload.get('_path', '<memory>')}")
    _say("INFO", f"zones={len(zones)}")
    if not zones:
        _say("FAIL", "normalized_zones is empty")
    for zone in zones:
        caps = sorted(_aspects(zone).keys())
        _say(
            "INFO",
            f"zone {zone.get('zone_id')} {zone.get('name')} enclosure={zone.get('enclosure')} aspects={caps}",
        )


def _check_grass_yurt(zones: List[Dict[str, Any]]) -> None:
    profile = _first_params(zones, "ground_profile")
    boundary = _first_params(zones, "boundary")
    surface = _first_params(zones, "interior_surface")
    if profile.get("type") == "rolling" and profile.get("material") == "grass":
        _say("PASS", "grass/yurt ground_profile is rolling grass")
    else:
        _say("WARN", f"expected rolling grass ground_profile, got {profile}")
    _say("PASS" if _has_cap(zones, "ground_cover") else "FAIL", "ground_cover aspect present")
    _say("PASS" if boundary else "FAIL", f"boundary aspect present: {boundary}")
    shape = str(surface.get("floor_shape") or "disc")
    _say("PASS" if shape == "disc" else "WARN", f"interior floor shape should preserve disc, got {shape}")


def _check_church(zones: List[Dict[str, Any]]) -> None:
    surface = _first_params(zones, "interior_surface")
    if _has_cap(zones, "ground_cover"):
        _say("FAIL", "church should not have ground_cover")
    else:
        _say("PASS", "church has no ground_cover")
    if _has_cap(zones, "boundary"):
        _say("FAIL", "church should not have boundary")
    else:
        _say("PASS", "church has no boundary")
    _say(
        "PASS" if surface.get("floor_material") == "stone" else "WARN",
        f"church floor_material expected stone, got {surface.get('floor_material')}",
    )
    _say(
        "PASS" if surface.get("floor_shape") == "quad" else "FAIL",
        f"church floor_shape must be quad, got {surface.get('floor_shape')}",
    )
    text = json.dumps(zones, ensure_ascii=False)
    if any(bad in text for bad in ("curtain", "felt", "毡帘", "毡布")):
        _say("FAIL", "church snapshot contains yurt-like entrance bias")
    else:
        _say("PASS", "church snapshot has no yurt-like entrance bias")


def _check_observatory(zones: List[Dict[str, Any]]) -> None:
    profile = _first_params(zones, "ground_profile")
    unsupported = _all_aspects(zones).get("unsupported", [])
    material = str(profile.get("material") or "")
    if material in ("stone", "neutral", "dirt"):
        _say("PASS", f"observatory material is non-grass: {material}")
    else:
        _say("WARN", f"observatory material should be stone/neutral/dirt, got {material}")
    if unsupported:
        _say("PASS", f"unsupported recorded: {unsupported}")
    else:
        _say("WARN", "no unsupported aspect recorded; OK only if prompt needed no unsupported capability")
    if material == "grass" or _has_cap(zones, "ground_cover"):
        _say("FAIL", "observatory appears to fallback to grass/cover")


def _check_outdoor_market(zones: List[Dict[str, Any]]) -> None:
    has_shell = any((z.get("enclosure") or "") == "shell" for z in zones)
    _say("PASS" if not has_shell else "FAIL", "pure outdoor market should not create enterable shell")
    boundary = _first_params(zones, "boundary")
    _say("PASS" if boundary else "FAIL", f"boundary aspect present: {boundary}")
    if boundary:
        if boundary.get("radius") is not None:
            _say("PASS", f"boundary radius explicitly set: {boundary.get('radius')}")
        elif boundary.get("margin") is not None:
            _say("PASS", f"boundary margin explicitly set: {boundary.get('margin')}")
        else:
            _say("WARN", "boundary has no radius/margin; runtime will use default margin=1.0")


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip())
        return 2
    path = argv[1]
    kind = argv[2] if len(argv) > 2 else "auto"
    payload = _load(path)
    payload["_path"] = os.path.abspath(path)
    zones = _zones(payload)
    if kind == "auto":
        kind = _infer_scene_kind(payload, zones)
    _check_common(payload, zones)
    _say("INFO", f"scene_kind={kind}")
    if kind == "grass_yurt":
        _check_grass_yurt(zones)
    elif kind == "church":
        _check_church(zones)
    elif kind == "observatory":
        _check_observatory(zones)
    elif kind == "outdoor_market":
        _check_outdoor_market(zones)
    else:
        _say("WARN", "unknown scene_kind; only common checks were run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
