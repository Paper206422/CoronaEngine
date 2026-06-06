"""分层审查节点 — 每层独立 VLM review + 差量修正路由。

tier_review:
  PASS → 下一层
  FAIL (且未超重试上限) → 返回该层 tier_place, 仅传 problem_actors
  FAIL (且超上限) → 记录警告, 继续下一层
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from Quasar.ai_workflow.streaming import stream_output_node

from ..scene_composition_workflow.formatters import NO_OUTPUT
from ..scene_composition_workflow.helpers import get_tool, parse_review_result

logger = logging.getLogger(__name__)

MAX_TIER_RETRIES = 2
DEFAULT_VIEW_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]
DEFAULT_ELEVATION = 35.0


# ---------------------------------------------------------------------------
# 截图 (复用 capture_screenshots 逻辑, 但只拍一次, 各层共享)
# ---------------------------------------------------------------------------

def _calc_camera_pose(
    center: List[float], distance: float,
    azimuth_deg: float, elevation_deg: float,
) -> Dict[str, List[float]]:
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    cos_el = math.cos(el)
    pos = [
        center[0] + distance * cos_el * math.sin(az),
        center[1] + distance * math.sin(el),
        center[2] + distance * cos_el * math.cos(az),
    ]
    fwd = [center[0] - pos[0], center[1] - pos[1], center[2] - pos[2]]
    length = math.sqrt(sum(f * f for f in fwd))
    fwd = [f / length for f in fwd] if length > 1e-6 else [0.0, 0.0, -1.0]
    return {"position": pos, "forward": fwd, "up": [0.0, 1.0, 0.0]}


def _capture_if_needed(state: Dict[str, Any]) -> Optional[str]:
    """拍摄场景全貌截图 (如果尚未拍摄), 返回截图目录。"""
    intermediate = state.get("intermediate", {})
    existing = intermediate.get("review_screenshot_dir")
    if existing and os.path.isdir(existing):
        pngs = [p for p in os.listdir(existing) if p.endswith(".png")]
        if pngs:
            logger.debug("tier_review: 复用已有截图 %s (%d 张)", existing, len(pngs))
            return existing

    scene_json_path = intermediate.get("scene_json_path", "")
    if not scene_json_path:
        return None

    metadata = state.get("metadata", {})
    room_size = metadata.get("room_size", [5, 3, 3])
    x_half, z_half = room_size[0] / 2, (room_size[1] / 2) if len(room_size) > 1 else 2.5
    distance = max(x_half, z_half) * 2.0 * 1.15
    center = [0.0, room_size[2] / 4.0 if len(room_size) > 2 else 0.5, 0.0]

    output_dir = str(Path(scene_json_path).parent / "review_screenshots")
    os.makedirs(output_dir, exist_ok=True)

    move_tool = get_tool("camera_move")
    shot_tool = get_tool("camera_screenshot")
    if move_tool is None or shot_tool is None:
        logger.warning("tier_review: 拍摄工具缺失")
        return None

    saved = []
    for az in DEFAULT_VIEW_ANGLES:
        pose = _calc_camera_pose(center, distance, az, DEFAULT_ELEVATION)
        try:
            move_tool.invoke({
                "position": pose["position"],
                "forward": pose["forward"],
                "up": pose["up"],
            })
            time.sleep(0.15)
            filepath = os.path.join(output_dir, f"scene_az{az:03d}.png")
            shot_tool.invoke({"output_path": filepath, "output_mode": "base_color"})
            saved.append(filepath)
        except Exception as e:
            logger.warning("tier_review: az=%d 截图异常: %s", az, e)

    logger.info("tier_review: 截图 %d/%d → %s", len(saved), len(DEFAULT_VIEW_ANGLES), output_dir)
    return output_dir if saved else None


# ---------------------------------------------------------------------------
# 差量修正路由辅助
# ---------------------------------------------------------------------------

def _check_retry_exceeded(state: Dict[str, Any], tier: int) -> bool:
    key = f"tier{tier}_retry_count"
    count = state.get("intermediate", {}).get(key, 0)
    return count >= MAX_TIER_RETRIES


def _next_tier_count(state: Dict[str, Any], tier: int) -> int:
    key = f"tier{tier}_retry_count"
    return state.get("intermediate", {}).get(key, 0) + 1


# ---------------------------------------------------------------------------
# Tier 审查节点
# ---------------------------------------------------------------------------

def _run_review(state: Dict[str, Any], tier: int, description: str) -> Dict[str, Any]:
    """通用 tier review 逻辑。"""
    intermediate = state.get("intermediate", {})
    screenshot_dir = _capture_if_needed(state)

    review_tool = get_tool("scene_rationality_review")
    if review_tool is None or not screenshot_dir:
        logger.warning("tier%d_review: 无法审查 (tool=%s, dir=%s), 跳过",
                       tier, review_tool is not None, screenshot_dir)
        return {
            "intermediate": {
                f"tier{tier}_review_result": {"overall": "SKIPPED"},
                f"tier{tier}_review_decision": "pass",
                "review_screenshot_dir": screenshot_dir,
            },
        }

    try:
        raw = review_tool.invoke({
            "output_dir": screenshot_dir,
            "scene_description": description,
            "max_images": 8,
        })
        parsed = parse_review_result(raw)
    except Exception as e:
        logger.warning("tier%d_review: VLM 调用异常: %s", tier, e)
        parsed = {"overall": "ERROR", "issues": [str(e)]}

    if parsed.get("error"):
        logger.warning("tier%d_review: 审查返回错误: %s", tier, parsed["error"])
        return {
            "intermediate": {
                f"tier{tier}_review_result": parsed,
                f"tier{tier}_review_decision": "pass",
                "review_screenshot_dir": screenshot_dir,
            },
        }

    overall = parsed.get("overall", "PASS")
    problem_actors = parsed.get("problem_actors", [])
    retry_exceeded = _check_retry_exceeded(state, tier)
    new_count = _next_tier_count(state, tier)

    if overall in ("PASS", "SKIPPED"):
        decision = "pass"
    elif retry_exceeded:
        logger.warning("tier%d_review: 重试 %d 次仍不通过, 强制继续", tier, new_count - 1)
        decision = "pass"
    else:
        decision = "fail"

    # 构建差量反馈文本
    feedback_lines = []
    retry_actor_names = []
    for pa in problem_actors:
        name = pa.get("actor", "")
        issue = pa.get("issue", "")
        reason = pa.get("reason", "")
        feedback_lines.append(f"- {name}: {issue} ({reason})")
        retry_actor_names.append(name)

    feedback_text = "\n".join(feedback_lines) if feedback_lines else "VLM 指出布局需要调整"

    logger.info("tier%d_review: overall=%s decision=%s retry=%d/%d problems=%d",
                tier, overall, decision, new_count - 1, MAX_TIER_RETRIES,
                len(problem_actors))

    return {
        "intermediate": {
            f"tier{tier}_review_result": parsed,
            f"tier{tier}_review_decision": decision,
            f"tier{tier}_retry_count": new_count,
            f"tier{tier}_retry_actors": retry_actor_names if decision == "fail" else None,
            f"tier{tier}_feedback": feedback_text if decision == "fail" else "",
            "review_screenshot_dir": screenshot_dir,
        },
    }


@stream_output_node("integrated", NO_OUTPUT)
def tier1_review_node(state: Dict[str, Any]) -> Dict[str, Any]:
    tier1_items = state.get("intermediate", {}).get("tier1_items", [])
    if not tier1_items:
        return {"intermediate": {"tier1_review_decision": "pass"}}
    names = ", ".join(it.get("name", it.get("object_id", "?")) for it in tier1_items[:5])
    return _run_review(state, 1, f"Tier1 大件布局审查: {names}")


@stream_output_node("integrated", NO_OUTPUT)
def tier2_review_node(state: Dict[str, Any]) -> Dict[str, Any]:
    tier2_items = state.get("intermediate", {}).get("tier2_items", [])
    if not tier2_items:
        return {"intermediate": {"tier2_review_decision": "pass"}}
    names = ", ".join(it.get("name", it.get("object_id", "?")) for it in tier2_items[:5])
    return _run_review(state, 2, f"Tier2 从属物体审查 (相对大件): {names}")


@stream_output_node("integrated", NO_OUTPUT)
def tier3_review_node(state: Dict[str, Any]) -> Dict[str, Any]:
    tier3_items = state.get("intermediate", {}).get("tier3_items", [])
    if not tier3_items:
        return {"intermediate": {"tier3_review_decision": "pass"}}
    names = ", ".join(it.get("name", it.get("object_id", "?")) for it in tier3_items[:5])
    return _run_review(state, 3, f"Tier3 装饰物终审: {names}")
