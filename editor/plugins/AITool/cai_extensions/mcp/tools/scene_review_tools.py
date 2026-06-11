"""场景合理性审查工具

在完成多视图拍摄（scene_multi_view_capture）后，将拍摄结果送入多模态大模型
进行场景合理性分析，从四个维度给出结构化评审报告：
  - 物体布局（悬空、穿插、遮挡）
  - 物理合理性（重力支撑、尺寸比例）
  - 风格一致性（材质、光照、整体风格）
  - 整体美观性（构图、密度、空间利用）
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import List

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from Quasar.ai_tools.response_adapter import (
    build_part,
    build_success_result,
    build_error_result,
)

logger = logging.getLogger(__name__)

_MAX_IMAGES_DEFAULT = 12  # 默认最大送审图片数，防止 token 超限


# ===========================================================================
# Input Schema
# ===========================================================================

class SceneRationalityReviewInput(BaseModel):
    output_dir: str = Field(
        description=(
            "scene_multi_view_capture 的输出目录路径，"
            "工具将从中读取 PNG 截图送入审查"
        ),
    )
    scene_description: str = Field(
        default="",
        description="场景的预期设计描述，帮助模型理解场景意图（可选）",
    )
    max_images: int = Field(
        default=_MAX_IMAGES_DEFAULT,
        description=(
            f"送入模型的最大图片数量，默认 {_MAX_IMAGES_DEFAULT}。"
            "数量过多会导致 token 超限，建议不超过 20"
        ),
    )


# ===========================================================================
# Helpers
# ===========================================================================

def _collect_png_files(output_dir: str, max_images: int) -> List[str]:
    """从目录中收集 PNG 文件，按名称排序后均匀间隔采样到 max_images 张。"""
    if not os.path.isdir(output_dir):
        return []
    all_pngs = sorted(
        p for p in os.listdir(output_dir) if p.lower().endswith(".png")
    )
    if not all_pngs:
        return []
    if len(all_pngs) <= max_images:
        return [os.path.join(output_dir, p) for p in all_pngs]
    # 均匀步长采样
    step = len(all_pngs) / max_images
    sampled = [all_pngs[int(i * step)] for i in range(max_images)]
    return [os.path.join(output_dir, p) for p in sampled]


def _parse_json_reply(raw: str) -> dict:
    """尝试从模型回复中提取 JSON，兼容裸 JSON 和代码块包裹两种格式。"""
    raw = raw.strip()
    # 去掉 ```json ... ``` 代码块
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 容错：在回复中搜索第一个完整 JSON 对象
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"raw": raw}


# ===========================================================================
# Tool builder
# ===========================================================================

def _build_scene_rationality_review_tool() -> StructuredTool:

    def _scene_rationality_review(
        *,
        output_dir: str,
        scene_description: str = "",
        max_images: int = _MAX_IMAGES_DEFAULT,
    ) -> str:
        try:
            from Quasar.ai_models.base_pool import MediaCategory, OmniRequest, get_pool_registry

            # --- 收集截图 ---
            png_files = _collect_png_files(output_dir, max_images)
            if not png_files:
                return build_error_result(
                    error_message=f"目录中未找到 PNG 截图：{output_dir}"
                ).to_envelope(interface_type="scene")

            # --- 构建 Prompt ---
            desc_hint = (
                f"场景预期描述：【{scene_description.strip()}】\n"
                if scene_description.strip()
                else ""
            )
            prompt_text = (
                f"{desc_hint}"
                f"以下是一个3D场景的多角度拍摄截图（共 {len(png_files)} 张视角）。\n"
                "你是专业的室内设计评审师。请从以下 4 个维度评估场景合理性：\n"
                "1. **布局合理性** (layout): 家具位置是否符合使用习惯，动线是否合理\n"
                "2. **物理合理性** (physics): 物体是否悬空、重叠、超出边界\n"
                "3. **风格一致性** (style): 家具风格、材质、光照是否协调\n"
                "4. **美观度** (aesthetics): 整体视觉效果、构图、空间利用\n\n"
                "请严格以如下 JSON 格式输出分析结果（不要包含任何额外文字）：\n"
                "{\n"
                '  "overall": "PASS" | "NEEDS_IMPROVEMENT",\n'
                '  "score": <0-100的整数>,\n'
                '  "problem_actors": [\n'
                '    {"actor": "场景中的物体名称",\n'
                '     "issue": "too_far | too_close | overlap | floating | wrong_scale | misaligned",\n'
                '     "reason": "问题描述(中文, 一句话)"}\n'
                "  ],\n"
                '  "corrections": [\n'
                '    {"object_id": "需要修正的物体名称",\n'
                '     "position": [x, y, z],\n'
                '     "rotation": [rx, ry, rz],\n'
                '     "scale": [sx, sy, sz],\n'
                '     "reason": "修正原因(中文)"}\n'
                "  ],\n"
                '  "issues": ["发现的问题1", "发现的问题2"],\n'
                '  "suggestions": ["改进建议1", "改进建议2"],\n'
                '  "details": {\n'
                '    "layout": "布局合理性评价",\n'
                '    "physics": "物理合理性评价",\n'
                '    "style": "风格一致性评价",\n'
                '    "aesthetics": "整体美观性评价"\n'
                "  }\n"
                "}\n\n"
                "【重要规则】\n"
                "- problem_actors 的 actor 字段必须使用场景中的实际物体名称（一字不差）\n"
                "- overall=PASS 时 problem_actors 和 corrections 为空数组 []\n"
                "- overall=NEEDS_IMPROVEMENT 时:\n"
                "  * problem_actors 必须至少包含 1 个物体\n"
                "  * **corrections 必须填充, 每个 problem_actor 对应一个 correction**\n"
                "  * correction.position 是修正后的最终绝对坐标 [x, y, z]\n"
                "    - 落地物体 Y=0, 挂墙物体 Y=1.6~2.0\n"
                "    - X 和 Z 必须在房间边界内\n"
                "    - 修正距离关系: 茶几在沙发前方 0.5-0.8m, 落地灯在沙发侧 0.3m\n"
                "  * 示例: 窗帘当前在 [0.9, 0, 2.95] 悬空 → correction: [0.9, 2.0, 1.45] (贴后墙, 挂墙高度)\n"
                "  * **相对大小**: 判断物体之间的比例是否和谐\n"
                "    - 台灯不应比茶几高, 靠垫不超过沙发扶手, 落地灯约为沙发高度的 1.5-2 倍\n"
                "    - 如果比例失调, 在 correction.scale 中输出修正后的 scale\n"
                "  * **corrections 示例** (NEEDS_IMPROVEMENT 时必须输出):\n"
                "    - 台灯与咖啡桌同高 → {\"object_id\":\"台灯\",\"scale\":[0.35,0.35,0.35],\"reason\":\"缩小到桌面台灯比例\"}\n"
                "    - 落地灯离沙发太远 → {\"object_id\":\"落地灯\",\"position\":[-0.5,0,1.0],\"reason\":\"移到沙发右侧0.3m\"}\n"
                "    - 地毯未居中 → {\"object_id\":\"地毯\",\"position\":[-0.3,0.01,0.3],\"reason\":\"居中到沙发茶几下方\"}\n"
                "- score ≥ 80 时 overall=PASS, < 80 时 overall=NEEDS_IMPROVEMENT"
            )

            logger.info(
                "[scene_review] 共 %d 张图片送入场景合理性审查...", len(png_files)
            )

            # --- 通过 Omni 池调用 VLM（与 helpers.analyze_images_with_vlm 一致）---
            pool_registry = get_pool_registry()
            request = OmniRequest(
                session_id=f"scene-review-{int(time.time())}",
                prompt=prompt_text,
                image_urls=png_files,
            )
            task = pool_registry.create_task(MediaCategory.OMNI, request)
            if task is None:
                return build_error_result(
                    error_message="Omni 池无可用账号，无法进行场景审查"
                ).to_envelope(interface_type="scene")

            result = task()
            raw_reply = result.metadata.get("analysis_result", "").strip()
            if not raw_reply:
                return build_error_result(
                    error_message="VLM 返回内容为空"
                ).to_envelope(interface_type="scene")

            review_json = _parse_json_reply(raw_reply)

            result_data = {
                "status": "success",
                "output_dir": output_dir,
                "images_reviewed": len(png_files),
                "review": review_json,
            }
            part = build_part(
                content_type="text",
                content_text=json.dumps(result_data, ensure_ascii=False, indent=2),
            )
            return build_success_result(parts=[part]).to_envelope(
                interface_type="scene"
            )

        except Exception as e:
            logger.error(
                "[scene_review] 场景合理性审查失败: %s", e, exc_info=True
            )
            return build_error_result(error_message=str(e)).to_envelope(
                interface_type="scene"
            )

    return StructuredTool(
        name="scene_rationality_review",
        description=(
            "对多视图拍摄结果进行场景合理性分析。"
            "传入 scene_multi_view_capture 的输出目录，工具将均匀采样截图，"
            "通过多模态大模型从布局、物理合理性、风格一致性、整体美观四个维度进行审查，"
            "返回整体评级（PASS / NEEDS_IMPROVEMENT / FAIL）、问题列表和改进建议 JSON。"
            "适合在场景搭建完成后执行质量检验。"
        ),
        args_schema=SceneRationalityReviewInput,
        func=_scene_rationality_review,
    )


# ===========================================================================
# Loader
# ===========================================================================

def load_scene_review_tools() -> List[StructuredTool]:
    return [_build_scene_rationality_review_tool()]


__all__ = ["load_scene_review_tools"]
