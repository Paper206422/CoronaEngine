from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, List

logger = logging.getLogger(__name__)


MODEL = "model"
SUBSTRATE = "scene_substrate"
LAYOUT = "layout_structure"


_SUBSTRATE_TERMS = (
    "草原", "天空", "森林", "树林", "地形", "地面", "地板", "木地板", "石板地面",
    "墙面", "墙壁", "天花板", "夜空", "云", "河流", "湖面", "海面", "雪地",
    "沙地", "道路", "路面", "庭院", "户外庭院", "雾", "光照", "灯光氛围",
)
_LAYOUT_TERMS = (
    "入口", "出口", "通道", "动线", "主路", "主街", "区域", "边界", "围合",
    "室内展示区", "户外庭院", "入口过渡", "连接动线",
)
_CONCRETE_SUFFIXES = (
    "床", "柜", "桌", "椅", "灯", "雕像", "玩偶", "摊位", "牌", "架", "门",
    "拱门", "长椅", "地毯", "沙发", "植物", "绿植", "狗", "猫", "小狗",
)
_COMPOUND_ASSET_MARKERS = (
    "灯笼", "路灯", "台灯", "吊灯", "小夜灯", "地毯", "地垫", "墙灯", "壁灯", "招牌",
)


@dataclass
class RoutedSceneElement:
    name: str
    category: str
    target_pipeline: str
    confidence: float
    reason: str = ""
    item: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "target_pipeline": self.target_pipeline,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def _name_of(item: dict[str, Any] | str) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("item_name") or "").strip()
    return str(item or "").strip()


def _is_compound_asset(name: str) -> bool:
    if any(marker in name for marker in _COMPOUND_ASSET_MARKERS):
        return True
    return any(name.endswith(suffix) and len(name) > len(suffix) for suffix in _CONCRETE_SUFFIXES)


def _rule_route(name: str) -> RoutedSceneElement:
    clean = name.strip()
    if not clean:
        return RoutedSceneElement(clean, "empty", SUBSTRATE, 1.0, "empty name")
    if _is_compound_asset(clean):
        return RoutedSceneElement(clean, "asset", MODEL, 0.92, "compound concrete asset")
    if any(term == clean or term in clean for term in _SUBSTRATE_TERMS):
        return RoutedSceneElement(clean, "environment", SUBSTRATE, 0.98, "scene substrate/environment")
    if any(term == clean or term in clean for term in _LAYOUT_TERMS):
        return RoutedSceneElement(clean, "layout", LAYOUT, 0.92, "layout/structure element")
    return RoutedSceneElement(clean, "asset", MODEL, 0.75, "concrete object fallback")


def _json_from_llm_text(raw: str) -> list[dict[str, Any]]:
    text = str(raw or "").strip()
    if "```" in text:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
    data = json.loads(text)
    return data if isinstance(data, list) else []


def _classify_via_llm(prompt_text: str, items: list[dict[str, Any]]) -> list[RoutedSceneElement]:
    try:
        from Quasar.ai_models.base_pool.registry import get_chat_model
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SceneElementClassifier] LLM unavailable: %s", exc)
        return []

    names = [_name_of(item) for item in items if _name_of(item)]
    if not names:
        return []
    system = (
        "你是场景生成元素分类器。把元素分为三类："
        "asset/model=需要生成或检索3D物体；"
        "environment/scene_substrate=地形、地面、天空、森林、墙面、光照等场景基底；"
        "layout/layout_structure=入口、动线、区域、边界等布局结构。"
        "注意：草原、天空、森林、地面、墙面、天花板不能作为普通物体模型生成；"
        "但台灯、灯笼、地毯、雕像、床、桌椅、摊位等具体物体应归为 asset。"
        "只输出 JSON 数组，每项包含 name, category, target_pipeline, confidence, reason。"
    )
    payload = {"scene_text": str(prompt_text or "")[:1600], "items": names}
    try:
        llm = get_chat_model(temperature=0, request_timeout=25.0)
        resp = llm.invoke([
            SystemMessage(content=system),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
        ])
        rows = _json_from_llm_text(resp.content if hasattr(resp, "content") else str(resp))
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SceneElementClassifier] LLM classification failed: %s", exc)
        return []
    out: list[RoutedSceneElement] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        pipeline = str(row.get("target_pipeline") or MODEL).strip()
        category = str(row.get("category") or "asset").strip()
        try:
            confidence = float(row.get("confidence", 0.7))
        except Exception:
            confidence = 0.7
        out.append(RoutedSceneElement(
            name=name,
            category=category,
            target_pipeline=pipeline,
            confidence=max(0.0, min(1.0, confidence)),
            reason=str(row.get("reason") or "llm"),
        ))
    return out


def _merge_llm_with_guardrail(
    prompt_text: str,
    items: list[dict[str, Any]],
    llm_routes: Iterable[RoutedSceneElement],
) -> list[RoutedSceneElement]:
    by_name = {route.name: route for route in llm_routes}
    merged: list[RoutedSceneElement] = []
    for item in items:
        name = _name_of(item)
        if not name:
            continue
        route = by_name.get(name) or _rule_route(name)
        guard = _rule_route(name)
        if guard.target_pipeline != MODEL:
            route = guard
        elif route.target_pipeline != MODEL and guard.target_pipeline == MODEL:
            route = guard
        route.item = item
        merged.append(route)
    return merged


def route_model_items(prompt_text: str, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[RoutedSceneElement]]:
    llm_routes = _classify_via_llm(prompt_text, items)
    routed = _merge_llm_with_guardrail(prompt_text, items, llm_routes)
    model_items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for route in routed:
        if route.target_pipeline != MODEL:
            continue
        item = dict(route.item or {})
        name = _name_of(item)
        if not name or name in seen:
            continue
        seen.add(name)
        item.setdefault("name", name)
        model_items.append(item)
    return model_items, routed


def summarize_classification(routes: Iterable[RoutedSceneElement]) -> str:
    model_names: list[str] = []
    substrate_names: list[str] = []
    layout_names: list[str] = []
    for route in routes:
        if route.target_pipeline == MODEL:
            model_names.append(route.name)
        elif route.target_pipeline == LAYOUT:
            layout_names.append(route.name)
        else:
            substrate_names.append(route.name)
    parts: list[str] = []
    if model_names:
        parts.append("准备生成模型：" + "、".join(model_names))
    if substrate_names:
        parts.append("环境/地形：" + "、".join(substrate_names) + " 将作为场景基底处理，不单独生成模型")
    if layout_names:
        parts.append("布局结构：" + "、".join(layout_names) + " 会进入摆放/结构规划")
    return "；".join(parts)
