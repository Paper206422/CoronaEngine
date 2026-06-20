from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class SceneDesignContract:
    contract_id: str
    room_id: str
    plan_id: str
    status: Literal["active", "closed"] = "active"
    scene_type: str = "mixed"
    environment_type: str = "mixed"
    mood: list[str] = field(default_factory=list)
    style_keywords: list[str] = field(default_factory=list)
    avoid_keywords: list[str] = field(default_factory=list)
    palette: list[str] = field(default_factory=list)
    lighting: list[str] = field(default_factory=list)
    terrain_spec: dict[str, Any] = field(default_factory=dict)
    boundary_spec: dict[str, Any] = field(default_factory=dict)
    scale_rules: list[str] = field(default_factory=list)
    placement_rules: list[str] = field(default_factory=list)
    asset_style_prompt: str = ""
    version: int = 1
    accepted_interventions: list[dict[str, Any]] = field(default_factory=list)
    deferred_interventions: list[dict[str, Any]] = field(default_factory=list)
    rejected_interventions: list[dict[str, Any]] = field(default_factory=list)
    updated_by: str = ""
    updated_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "room_id": self.room_id,
            "plan_id": self.plan_id,
            "status": self.status,
            "scene_type": self.scene_type,
            "environment_type": self.environment_type,
            "mood": list(self.mood),
            "style_keywords": list(self.style_keywords),
            "avoid_keywords": list(self.avoid_keywords),
            "palette": list(self.palette),
            "lighting": list(self.lighting),
            "terrain_spec": dict(self.terrain_spec),
            "boundary_spec": dict(self.boundary_spec),
            "scale_rules": list(self.scale_rules),
            "placement_rules": list(self.placement_rules),
            "asset_style_prompt": self.asset_style_prompt,
            "version": self.version,
            "accepted_interventions": [dict(item) for item in self.accepted_interventions],
            "deferred_interventions": [dict(item) for item in self.deferred_interventions],
            "rejected_interventions": [dict(item) for item in self.rejected_interventions],
            "updated_by": self.updated_by,
            "updated_at": self.updated_at,
        }


def build_scene_design_contract(
    *,
    room_id: str,
    plan_id: str,
    scene_type: str,
    text: str,
) -> SceneDesignContract:
    raw = str(text or "")
    lower = raw.lower()
    contract = SceneDesignContract(
        contract_id=f"contract-{uuid.uuid4().hex[:12]}",
        room_id=str(room_id or "default"),
        plan_id=str(plan_id or ""),
        scene_type=str(scene_type or "mixed"),
        environment_type=_environment_type(scene_type, raw),
    )
    _apply_text(contract, raw)
    if "\u96c6\u5e02" in raw or "market" in lower:
        _add_once(contract.style_keywords, "market")
        _add_once(contract.placement_rules, "keep clear visitor paths between entrance, stalls, lighting, and rest area")
    if "\u591c" in raw or "night" in lower:
        _add_once(contract.mood, "night")
        _add_once(contract.lighting, "warm visible lantern lighting")
    if "\u5e7b\u60f3" in raw or "fantasy" in lower:
        _add_once(contract.style_keywords, "fantasy")
    if "\u6e29\u6696" in raw or "warm" in lower:
        _add_once(contract.mood, "warm")
        _add_once(contract.palette, "warm amber")
    contract.asset_style_prompt = _asset_style_prompt(contract)
    return contract


def update_contract_from_intervention(
    contract: SceneDesignContract,
    *,
    text: str,
    accepted: bool = True,
    deferred: bool = False,
    rejected: bool = False,
    actor_id: str = "",
    batch_id: str = "",
    updated_by: str = "",
) -> SceneDesignContract:
    item = {
        "text": str(text or ""),
        "actor_id": str(actor_id or ""),
        "batch_id": str(batch_id or ""),
        "updated_by": str(updated_by or ""),
        "timestamp": time.time(),
    }
    if rejected:
        contract.rejected_interventions.append(item)
    elif deferred:
        contract.deferred_interventions.append(item)
    else:
        contract.accepted_interventions.append(item)
    if accepted and not rejected:
        _apply_text(contract, str(text or ""))
    contract.version += 1
    contract.updated_by = str(updated_by or "")
    contract.updated_at = time.time()
    contract.asset_style_prompt = _asset_style_prompt(contract)
    return contract


def close_contract(contract: SceneDesignContract) -> SceneDesignContract:
    contract.status = "closed"
    contract.version += 1
    contract.updated_at = time.time()
    return contract


def _environment_type(scene_type: str, text: str) -> str:
    if any(word in text for word in ("\u5ba4\u5185\u5916", "\u5185\u5916", "\u6df7\u5408")):
        return "mixed"
    if any(word in text for word in ("\u5ba4\u5916", "\u6237\u5916", "\u5e7f\u573a", "\u96c6\u5e02")):
        return "outdoor"
    if any(word in text for word in ("\u5ba4\u5185", "\u623f\u95f4", "\u5927\u5385")):
        return "indoor"
    return str(scene_type or "mixed")


def _apply_text(contract: SceneDesignContract, text: str) -> None:
    raw = str(text or "")
    lower = raw.lower()
    if not raw:
        return
    for avoid in _extract_negative_preferences(raw):
        _add_once(contract.avoid_keywords, avoid)
    if "\u4e0d\u8981\u592a\u6050\u6016" in raw or "\u4e0d\u592a\u6050\u6016" in raw or "not too scary" in lower:
        _add_once(contract.avoid_keywords, "too horror")
        _add_once(contract.avoid_keywords, "dark horror")
        _add_once(contract.mood, "mysterious but friendly")
    if any(word in raw for word in ("\u7edf\u4e00", "\u4e00\u81f4", "\u98ce\u683c")):
        _add_once(contract.style_keywords, "style consistency")
    if any(word in raw for word in ("\u706f\u5149", "\u706f\u7b3c", "\u706f")):
        _add_once(contract.lighting, "coherent warm lights")
    if any(word in raw for word in ("\u4f11\u606f\u533a", "\u5ea7\u6905", "\u957f\u6905")):
        _add_once(contract.placement_rules, "keep rest area reachable and not blocking market path")
    if any(word in raw for word in ("\u8db3\u591f\u5927", "\u6bd4\u4f8b", "\u5927\u5c0f")):
        _add_once(contract.scale_rules, raw[:80])
    if any(word in raw for word in ("\u7a7f\u6a21", "\u6446\u653e", "\u7ec4\u88c5", "\u5730\u5f62", "\u63a5\u5730")):
        _add_once(contract.placement_rules, raw[:80])


def _extract_negative_preferences(text: str) -> list[str]:
    out: list[str] = []
    patterns = (
        r"\u4e0d\u8981(?P<value>[^，。；,.]{1,20})",
        r"\u522b(?P<value>[^，。；,.]{1,20})",
        r"\u4e0d\u5e0c\u671b(?P<value>[^，。；,.]{1,20})",
        r"\u4e0d\u80fd(?P<value>[^，。；,.]{1,20})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group("value").strip()
            if value:
                out.append(value)
    return out


def _asset_style_prompt(contract: SceneDesignContract) -> str:
    parts = []
    if contract.style_keywords:
        parts.append("style=" + ", ".join(contract.style_keywords[:6]))
    if contract.mood:
        parts.append("mood=" + ", ".join(contract.mood[:6]))
    if contract.palette:
        parts.append("palette=" + ", ".join(contract.palette[:4]))
    if contract.lighting:
        parts.append("lighting=" + ", ".join(contract.lighting[:4]))
    if contract.avoid_keywords:
        parts.append("avoid=" + ", ".join(contract.avoid_keywords[:6]))
    return "; ".join(parts)


def _add_once(items: list[str], value: str) -> None:
    value = str(value or "").strip()
    if value and value not in items:
        items.append(value)


__all__ = [
    "SceneDesignContract",
    "build_scene_design_contract",
    "close_contract",
    "update_contract_from_intervention",
]
