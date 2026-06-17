from __future__ import annotations

import concurrent.futures
import logging
import os
import time
from typing import Any, Dict, List

from Quasar.ai_tools.context import reset_current_session, set_current_session
from Quasar.ai_workflow.state import ModelRetrievalWorkflowState
from Quasar.ai_workflow.streaming import stream_output_node

from .formatters import NO_OUTPUT
from .helpers import normalize_object_id
from .test_cases import get_test_case

logger = logging.getLogger(__name__)


def _image_retry_max_workers(count: int) -> int:
    try:
        configured = int(os.getenv("CORONA_IMAGE_RETRY_MAX_WORKERS", "3") or "3")
    except ValueError:
        configured = 3
    return max(1, min(max(1, count), configured))


def _retry_failed_images(
    failed_elements: List[Dict[str, str]],
    session_id: str,
) -> Dict[str, str]:
    """对上游图片生成失败的元素进行一次补偿重试。"""
    from ..integrated_multi_scene_workflow.helpers import (
        extract_image_url,
        get_generate_image_tool,
    )

    image_tool = get_generate_image_tool()
    if not image_tool:
        logger.warning("[Workflow][dispatch] 图片生成工具不可用，无法补偿重试")
        return {}

    def _retry_one(elem: Dict[str, str]) -> tuple[str, str]:
        name = elem.get("item_name", "")
        prompt = elem.get("image_prompt", "")
        if not prompt:
            return name, ""
        token = set_current_session(session_id)
        try:
            raw_result = image_tool.invoke({"prompt": prompt})
            image_url = extract_image_url(raw_result)
            if image_url:
                logger.info("[Workflow][dispatch] %s 补偿图片生成成功", name)
                return name, image_url
            else:
                logger.warning("[Workflow][dispatch] %s 补偿图片生成结果为空", name)
        except Exception as e:
            logger.warning("[Workflow][dispatch] %s 补偿图片生成失败: %s", name, e)
        finally:
            reset_current_session(token)
        return name, ""

    recovered: Dict[str, str] = {}
    workers = _image_retry_max_workers(len(failed_elements))
    started_at = time.perf_counter()
    logger.info(
        "[Workflow][dispatch] 并发补偿图片: items=%s workers=%s",
        len(failed_elements),
        workers,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_retry_one, elem) for elem in failed_elements]
        for future in concurrent.futures.as_completed(futures):
            name, image_url = future.result()
            if name and image_url:
                recovered[name] = image_url

    logger.info(
        "[Workflow][dispatch] 图片补偿完成: recovered=%s/%s elapsed=%.2fs",
        len(recovered),
        len(failed_elements),
        time.perf_counter() - started_at,
    )

    return recovered


@stream_output_node("integrated", NO_OUTPUT)
def dispatch_node(state: ModelRetrievalWorkflowState) -> Dict[str, Any]:
    """从第一步的输出中组装每个物体的检索/生成任务。"""
    metadata = state.get("metadata", {})
    global_assets = state.get("global_assets", {}) or {}

    if metadata.get("workflow_test"):
        test_case_key = metadata.get("workflow_test_case", "default")
        test_data = get_test_case(test_case_key)
        test_assets = test_data.get("global_assets", {})
        if test_assets:
            logger.info(
                "[Workflow][dispatch][TEST] 工作流测试模式，使用预定义 global_assets: "
                "test_case=%s",
                test_case_key,
            )
            global_assets = test_assets

    multi_scene = global_assets.get("multi_scene", {}) or {}

    approved = multi_scene.get("approved_elements") or state.get(
        "approved_elements",
        [],
    )
    generated_images: Dict[str, str] = multi_scene.get("generated_images") or state.get(
        "generated_images",
        {},
    )

    if not approved:
        return {"error": "无可处理的设计元素（第一步输出为空）"}

    tasks: List[Dict[str, str]] = []
    failed_elements: List[Dict[str, str]] = []
    for idx, elem in enumerate(approved, start=1):
        name = elem.get("item_name", "")
        image_url = generated_images.get(name, "")
        if not image_url:
            failed_elements.append(elem)
            continue
        object_id = normalize_object_id(name, idx)
        tasks.append(
            {
                "item_name": name,
                "object_id": object_id,
                "image_url": image_url,
                "image_prompt": elem.get("image_prompt", ""),
            }
        )

    # 对图片生成失败的元素进行补偿重试
    if failed_elements:
        logger.info(
            "[Workflow][dispatch] %s 个元素无生成图片，尝试补偿重试",
            len(failed_elements),
        )
        session_id = str(state.get("session_id", "default") or "default")
        recovered = _retry_failed_images(failed_elements, session_id)
        for idx_offset, elem in enumerate(failed_elements, start=len(tasks) + 1):
            name = elem.get("item_name", "")
            image_url = recovered.get(name, "")
            object_id = normalize_object_id(name, idx_offset)
            if image_url:
                tasks.append(
                    {
                        "item_name": name,
                        "object_id": object_id,
                        "image_url": image_url,
                        "image_prompt": elem.get("image_prompt", ""),
                    }
                )
            else:
                # 文生图最终失败 → 降级为文字直生 3D（混元支持 text_to_3d，
                # 文字/图片二选一）。图片只是可选输入适配层，失败不该让整条链断。
                # image_url 用 __text_to_3d__: 前缀，generate_single_item 据此切文本模式；
                # retrieve_single_item 见此前缀会跳过图搜、直接转生成。
                prompt_text = (elem.get("image_prompt", "") or name).strip()
                tasks.append(
                    {
                        "item_name": name,
                        "object_id": object_id,
                        "image_url": f"__text_to_3d__:{prompt_text}",
                        "image_prompt": prompt_text,
                    }
                )
                logger.info(
                    "[Workflow][dispatch] %s 文生图失败，降级为文字直生 3D（text_to_3d）",
                    name,
                )

    if not tasks:
        return {"error": "所有物体均无生成图片，无法进行模型检索"}

    logger.info("[Workflow][dispatch] 组装 %s 个检索/生成任务", len(tasks))
    return {
        "intermediate": {
            **state.get("intermediate", {}),
            "retrieval_tasks": tasks,
        },
    }
