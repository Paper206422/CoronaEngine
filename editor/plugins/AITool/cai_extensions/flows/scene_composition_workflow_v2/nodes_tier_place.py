"""分层放置节点 — tier1 (大件 LLM), tier2 (从属锚点), tier3 (装饰)。

tier1: LLM 计算大件绝对坐标 → place_scene_from_items
tier2: LLM 描述空间关系 → place_object_near 锚点放置
tier3: 装饰物混合放置 (绝对+锚点)

每层支持差量重算: 仅重算问题 actors, 已确定 actors 作为约束。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Set

from Quasar.ai_workflow.streaming import stream_output_node

from ..scene_composition_workflow.formatters import NO_OUTPUT
from ..scene_composition_workflow.helpers import get_tool, parse_placement_result

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 分层分类: 根据物体语义决定属于哪一层
# ---------------------------------------------------------------------------

TIER1_KEYWORDS = {
    "bed", "sofa", "couch", "table", "desk", "wardrobe", "cabinet", "closet",
    "bookshelf", "shelf", "dresser", "tv_stand", "tv stand", "fridge",
    "床", "沙发", "桌子", "书桌", "衣柜", "柜子", "书架", "电视柜", "冰箱",
}

TIER2_KEYWORDS = {
    "chair", "nightstand", "lamp", "stool", "ottoman", "side_table", "side table",
    "床头柜", "椅子", "台灯", "凳子", "边桌",
}

# 其余不在前两层的均归入 tier3 (装饰)


def _classify_item(item: Dict[str, Any]) -> int:
    """根据物体名称/object_id 判断属于哪一层。"""
    name = str(item.get("name", "") or "").lower()
    object_id = str(item.get("object_id", "") or "").lower()
    combined = f"{name} {object_id}"

    for kw in TIER2_KEYWORDS:
        if kw in combined:
            return 2
    for kw in TIER1_KEYWORDS:
        if kw in combined:
            return 1
    return 3


# ---------------------------------------------------------------------------
# Tier 1: 大件 LLM 布局
# ---------------------------------------------------------------------------

TIER1_SYSTEM_PROMPT = """你是一个专业的室内设计师。请为以下大型家具确定精确位置。

坐标系: X+右, Y+上(地面Y=0), Z+屏幕内侧。旋转单位: 度(绕Y轴可改朝向)。

规则:
1. 靠墙物体贴近墙壁 (距墙 0.1-0.3m)
2. 物体之间保持合理间距 (≥0.3m)
3. 遵守房间边界
4. 只输出 JSON 数组, 不要其他文字"""

TIER1_RETRY_PROMPT = """你是一个室内设计师。请修正以下有问题的物体位置。

【已确定物体 (不可修改)】:
{locked_actors}

【问题反馈】:
{feedback}

【房间尺寸】: {room_size}

请只对问题物体输出新的 JSON 数组 (格式同初始布局)。"""


def _build_tier1_user_prompt(
    items: List[Dict[str, Any]],
    room_size: List[float],
    prompt: str,
) -> str:
    item_lines = [
        f"  - object_id: {it.get('object_id', '')}, 名称: {it.get('name', '未知')}"
        for it in items
    ]
    x_half, z_half = room_size[0] / 2, room_size[1] / 2
    return (
        f"## 设计方案\n{prompt}\n\n"
        f"## 房间: {room_size[0]}×{room_size[1]}m, "
        f"X=[{-x_half:.1f}, {x_half:.1f}], Z=[{-z_half:.1f}, {z_half:.1f}]\n\n"
        f"## 物体 ({len(items)} 个)\n" + "\n".join(item_lines)
    )


def _call_llm_layout(
    items: List[Dict[str, Any]],
    room_size: List[float],
    prompt: str,
    system_prompt: str = TIER1_SYSTEM_PROMPT,
    timeout: float = 90.0,
    locked_actors: Optional[List[Dict[str, Any]]] = None,
    feedback: str = "",
) -> Optional[List[Dict[str, Any]]]:
    """调用 LLM 生成布局, 返回 JSON 列表。"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    from langchain_core.messages import HumanMessage, SystemMessage

    if locked_actors and feedback:
        user_prompt = TIER1_RETRY_PROMPT.format(
            locked_actors=json.dumps(locked_actors, ensure_ascii=False, indent=2),
            feedback=feedback,
            room_size=f"{room_size[0]}×{room_size[1]}m",
        )
    else:
        user_prompt = _build_tier1_user_prompt(items, room_size, prompt)

    def _do_llm_call():
        from Quasar.ai_models.base_pool.registry import get_chat_model
        llm = get_chat_model(temperature=0.3, request_timeout=60.0)
        return llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_do_llm_call)
    try:
        response = future.result(timeout=timeout)
    except FuturesTimeoutError:
        executor.shutdown(wait=False, cancel_futures=True)
        logger.warning("tier_place: LLM 超时 (%.0fs)", timeout)
        return None
    except Exception as e:
        executor.shutdown(wait=False)
        logger.warning("tier_place: LLM 失败: %s", e)
        return None
    else:
        executor.shutdown(wait=False)

    text = (response.content if hasattr(response, "content") else str(response)).strip()
    if "```" in text:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            text = text[start: end + 1]
    try:
        layouts = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("tier_place: JSON 解析失败")
        return None
    if not isinstance(layouts, list):
        return None
    return layouts


# ---------------------------------------------------------------------------
# Tier 2/3: 锚点放置 (place_object_near)
# ---------------------------------------------------------------------------

TIER2_ANCHOR_PROMPT = """你是室内设计师。以下物体需要相对大件放置。请为每个物体指定锚点。

当前场景已放置物体:
{locked_actors}

待放置物体:
{items}

为每个物体输出空间关系 (JSON 数组):
[
  {{"object_id": "nightstand_01", "reference_actor": "bed_01", "relation": "right", "gap_m": 0.3}},
  ...
]

relation: left | right | front | behind | above | below
gap_m: 间距 (米)"""


def _call_llm_anchor(
    items: List[Dict[str, Any]],
    locked_actors_text: str,
    timeout: float = 60.0,
) -> Optional[List[Dict[str, Any]]]:
    """调用 LLM 生成锚点关系。"""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
    from langchain_core.messages import HumanMessage, SystemMessage

    items_text = "\n".join(
        f"  - object_id: {it.get('object_id', '')}, 名称: {it.get('name', '未知')}"
        for it in items
    )
    prompt = TIER2_ANCHOR_PROMPT.format(
        locked_actors=locked_actors_text,
        items=items_text,
    )

    def _do_call():
        from Quasar.ai_models.base_pool.registry import get_chat_model
        llm = get_chat_model(temperature=0.1, request_timeout=30.0)
        return llm.invoke([
            SystemMessage(content="你是室内设计师。只输出 JSON 数组。"),
            HumanMessage(content=prompt),
        ])

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_do_call)
    try:
        response = future.result(timeout=timeout)
    except FuturesTimeoutError:
        executor.shutdown(wait=False, cancel_futures=True)
        return None
    except Exception as e:
        executor.shutdown(wait=False)
        logger.warning("tier_anchor: LLM 失败: %s", e)
        return None
    else:
        executor.shutdown(wait=False)

    text = (response.content if hasattr(response, "content") else str(response)).strip()
    if "```" in text:
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            text = text[start: end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# 放置节点
# ---------------------------------------------------------------------------

def _format_locked_actors(state: Dict[str, Any]) -> str:
    """格式化已锁定的 actor 列表为 LLM 可读文本。"""
    intermediate = state.get("intermediate", {})
    locked = intermediate.get("locked_actors", [])
    if not locked:
        snap = intermediate.get("scene_actors", [])
        if snap:
            locked = [{"name": a.get("name", ""), "position": a.get("geometry", {}).get("pos", [0,0,0])}
                       for a in snap]
    if not locked:
        return "无"
    lines = []
    for a in locked:
        name = a.get("name", a.get("actor_name", "?"))
        pos = a.get("position", a.get("pos", [0, 0, 0]))
        lines.append(f"  - {name}: pos={pos}")
    return "\n".join(lines) if lines else "无"


@stream_output_node("integrated", NO_OUTPUT)
def tier1_place_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Tier 1: 大件 LLM 绝对坐标布局。"""
    intermediate = state.get("intermediate", {})
    all_items = intermediate.get("placement_items", [])
    tier1_items = [it for it in all_items if _classify_item(it) == 1]

    if not tier1_items:
        logger.info("tier1_place: 无大件物体, 跳过")
        return {"intermediate": {"tier1_items": [], "locked_actors": []}}

    metadata = state.get("metadata", {})
    room_size = metadata.get("room_size", [5, 3, 3])
    prompt = state.get("prompt", "")

    # 差量重算: 只处理 problem_actors
    problem_actors = intermediate.get("tier1_retry_actors")
    if problem_actors:
        logger.info("tier1_place: 差量重算 %d 个 actors", len(problem_actors))
        locked = intermediate.get("locked_actors", [])
        feedback = intermediate.get("tier1_feedback", "")
        items_to_place = [it for it in tier1_items
                          if it.get("object_id") in problem_actors]
        layouts = _call_llm_layout(
            items_to_place, room_size, prompt,
            locked_actors=locked, feedback=feedback,
        )
    else:
        logger.info("tier1_place: 初始布局 %d 个大件", len(tier1_items))
        layouts = _call_llm_layout(tier1_items, room_size, prompt)

    if not layouts:
        return {"error": "tier1 LLM 布局失败"}

    # 应用布局到 items
    layout_map = {str(l["object_id"]): l for l in layouts}
    for item in tier1_items:
        oid = str(item.get("object_id", ""))
        layout = layout_map.get(oid)
        if layout:
            for key in ("pos", "rot", "scale"):
                val = layout.get(key)
                if isinstance(val, list) and len(val) == 3:
                    item[key] = [float(v) for v in val]

    # 调用 place_scene_from_items
    tool = get_tool("place_scene_from_items")
    if tool is None:
        return {"error": "place_scene_from_items 工具未注册"}

    scene_name = metadata.get("scene_name", "composed_scene")
    scene_path = metadata.get("scene_path", f"Scene/{scene_name}/{scene_name}.scene")

    raw = tool.invoke({
        "scene_path": scene_path,
        "scene_name": scene_name,
        "room_size": room_size,
        "items": tier1_items,
    })
    parsed = parse_placement_result(raw)
    if parsed.get("error"):
        return {"error": f"tier1 场景布局失败: {parsed['error']}"}

    scene_json_path = parsed["scene_path"]
    actors = parsed.get("actors", [])

    # 导入引擎
    import_tool = get_tool("import_model")
    if import_tool:
        for actor in actors:
            name = actor.get("name", actor.get("source_name", ""))
            path = actor.get("path", "")
            geom = actor.get("geometry", {})
            try:
                import_tool.invoke({
                    "model_path": path,
                    "actor_name": name,
                    "position": geom.get("pos", [0, 0, 0]),
                    "rotation": geom.get("rot", [0, 0, 0]),
                    "scale": geom.get("scale", [1, 1, 1]),
                    "scene_name": scene_name,
                })
            except Exception as e:
                logger.warning("tier1 import %s 失败: %s", name, e)

    logger.info("tier1_place: 完成 %d 个大件 → %s", len(actors), scene_json_path)
    return {
        "intermediate": {
            "tier1_items": tier1_items,
            "locked_actors": actors,
            "scene_json_path": scene_json_path,
            "scene_actors": actors,
            "scene_name": scene_name,
            "current_tier": 1,
            "tier1_retry_count": intermediate.get("tier1_retry_count", 0),
        },
    }


@stream_output_node("integrated", NO_OUTPUT)
def tier2_place_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Tier 2: 从属物体锚点放置。"""
    intermediate = state.get("intermediate", {})
    all_items = intermediate.get("placement_items", [])
    tier2_items = [it for it in all_items if _classify_item(it) == 2]

    if not tier2_items:
        logger.info("tier2_place: 无从属物体, 跳过")
        return {"intermediate": {"tier2_items": []}}

    locked_text = _format_locked_actors(state)
    metadata = state.get("metadata", {})
    scene_name = metadata.get("scene_name", "composed_scene")

    anchor_tool = get_tool("place_object_near")
    if anchor_tool is None:
        logger.warning("tier2_place: place_object_near 不可用, 回退 tier1 方式")
        return tier1_place_node(state)

    # LLM 生成锚点关系
    anchors = _call_llm_anchor(tier2_items, locked_text)

    if anchors is None:
        logger.warning("tier2_place: LLM 锚点生成失败, 用默认 grid 放置")
        return {"error": "tier2 LLM 锚点生成失败"}

    placed = []
    failed = []
    for anchor in anchors:
        oid = anchor.get("object_id", "")
        ref = anchor.get("reference_actor", "")
        rel = anchor.get("relation", "right")
        gap = float(anchor.get("gap_m", 0.3))

        item = next((it for it in tier2_items
                     if str(it.get("object_id", "")) == oid), None)
        if item is None:
            logger.warning("tier2: 锚点 %s 找不到对应 item, 跳过", oid)
            continue

        model_path = item.get("local_path", "")
        if not model_path:
            failed.append({"object_id": oid, "error": "无 local_path"})
            continue

        try:
            raw = anchor_tool.invoke({
                "object_id": oid,
                "model_path": model_path,
                "reference_actor": ref,
                "relation": rel,
                "gap_m": gap,
                "scene_name": scene_name,
            })
            # 解析结果确认成功
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {}
            else:
                parsed = raw if isinstance(raw, dict) else {}
            if parsed.get("error_code") == 0:
                placed.append(anchor)
            else:
                failed.append({"object_id": oid, "error": str(parsed)})
        except Exception as e:
            logger.warning("tier2: %s 锚点放置失败: %s", oid, e)
            failed.append({"object_id": oid, "error": str(e)})

    logger.info("tier2_place: 完成 %d/%d 个从属", len(placed), len(tier2_items))

    return {
        "intermediate": {
            "tier2_items": tier2_items,
            "tier2_anchors": anchors,
            "tier2_placed": placed,
            "tier2_failed": failed,
            "current_tier": 2,
            "tier2_retry_count": intermediate.get("tier2_retry_count", 0),
        },
    }


@stream_output_node("integrated", NO_OUTPUT)
def tier3_place_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Tier 3: 装饰物放置 (混合: 锚点优先, 回退绝对坐标)。"""
    intermediate = state.get("intermediate", {})
    all_items = intermediate.get("placement_items", [])
    tier3_items = [it for it in all_items if _classify_item(it) == 3]

    if not tier3_items:
        logger.info("tier3_place: 无装饰物, 跳过")
        return {"intermediate": {"tier3_items": []}}

    locked_text = _format_locked_actors(state)
    metadata = state.get("metadata", {})
    scene_name = metadata.get("scene_name", "composed_scene")

    # 尝试锚点放置
    anchor_tool = get_tool("place_object_near")
    placed = []
    failed = []

    for item in tier3_items:
        oid = str(item.get("object_id", ""))
        model_path = item.get("local_path", "")
        if not model_path:
            failed.append({"object_id": oid, "error": "无 local_path"})
            continue

        if anchor_tool:
            # 简单启发式: 地毯放房间中心, 挂画贴墙
            relation = "behind"
            ref_actor = _find_reference_for_decor(state, item)
            if ref_actor:
                try:
                    raw = anchor_tool.invoke({
                        "object_id": oid, "model_path": model_path,
                        "reference_actor": ref_actor, "relation": relation,
                        "gap_m": 0.5, "scene_name": scene_name,
                    })
                    placed.append({"object_id": oid, "actor_name": oid})
                    continue
                except Exception:
                    pass

        # 回退: 直接 import_model 到默认位置
        try:
            import_tool = get_tool("import_model")
            if import_tool:
                import_tool.invoke({
                    "model_path": model_path, "actor_name": oid,
                    "position": item.get("pos", [0, 0, 0]),
                    "rotation": item.get("rot", [0, 0, 0]),
                    "scale": item.get("scale", [1, 1, 1]),
                    "scene_name": scene_name,
                })
                placed.append({"object_id": oid, "actor_name": oid})
            else:
                failed.append({"object_id": oid, "error": "import_model 不可用"})
        except Exception as e:
            failed.append({"object_id": oid, "error": str(e)})

    logger.info("tier3_place: 完成 %d/%d 个装饰", len(placed), len(tier3_items))
    return {
        "intermediate": {
            "tier3_items": tier3_items,
            "tier3_placed": placed,
            "tier3_failed": failed,
            "current_tier": 3,
            "tier3_retry_count": intermediate.get("tier3_retry_count", 0),
        },
    }


def _find_reference_for_decor(state: Dict[str, Any], item: Dict[str, Any]) -> Optional[str]:
    """为装饰物找到合适的参考 actor。"""
    intermediate = state.get("intermediate", {})
    locked = intermediate.get("locked_actors", [])
    if not locked:
        return None
    # 找最大的已放置 actor (最可能是床/沙发等核心大件)
    return locked[0].get("name", locked[0].get("actor_name", "")) if locked else None
