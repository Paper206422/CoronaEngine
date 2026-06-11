"""
全流程 Pipeline 各阶段节点

每个节点完整地调用一个子工作流，并将子工作流产出的
global_assets / dialogue_entries 回写到 pipeline state，
由 LangGraph 的 reducer (deep_merge_dict / operator.add) 自动累积传递。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from Quasar.ai_workflow.progress import publish_node_entries_event
from Quasar.ai_workflow.state import (
    MultiSceneWorkflowState,
    ModelRetrievalWorkflowState,
    SceneCompositionWorkflowState,
    deep_merge_dict,
)
from Quasar.ai_workflow.streaming import build_node_dialogue_entry

_logger = logging.getLogger(__name__)

FUNCTION_ID = 21000
from .constants import FULL_PIPELINE_V2_FUNCTION_ID  # noqa: E402


def _push_pipeline_progress(
    state: Dict[str, Any],
    text: str,
    node_name: str = "multi_scene",
) -> None:
    """向界面推送 pipeline 阶段进度。"""
    session_id = str(state.get("session_id", "default") or "default")
    entry = build_node_dialogue_entry(
        "integrated",
        [{"content_type": "text", "content_text": text}],
        node_name=node_name,
        function_id=FUNCTION_ID,
    )
    ok = publish_node_entries_event(session_id, node_name, [entry])
    if not ok:
        _logger.warning("进度推送失败: session=%s node=%s", session_id[:8], node_name)


def _make_sub_state(pipeline_state: Dict[str, Any], function_id: int) -> Dict[str, Any]:
    """从 pipeline state 衍生子工作流初始状态。

    直接将当前已积累的 global_assets 注入子工作流，使其能读到上一步的产出。

    resume_from_review 路径说明：
      parse_request 在审核提交后会将 approved_elements 写入顶层 state，
      同时在 metadata 中置 resume_from_review=True。
      这两个字段必须一起透传给子工作流，否则 analyzer/human_review 节点
      虽看到 resume 标记但找不到元素，会重新调用 LLM。
    """
    return {
        "session_id": pipeline_state.get("session_id", "default"),
        "function_id": function_id,
        "prompt": pipeline_state.get("prompt", ""),
        "images": pipeline_state.get("images", []),
        "additional_type": pipeline_state.get("additional_type", []),
        "bounding_box": pipeline_state.get("bounding_box", []),
        "resolution": pipeline_state.get("resolution", "1:1"),
        "image_size": pipeline_state.get("image_size", "2K"),
        "metadata": dict(pipeline_state.get("metadata", {})),
        # 关键：把上一步积累的 global_assets 整体传入
        "global_assets": deep_merge_dict({}, pipeline_state.get("global_assets", {})),
        # resume_from_review 时透传已审核的元素列表，供子工作流跳过 analyzer/human_review
        "approved_elements": list(pipeline_state.get("approved_elements", []) or []),
        "extracted_elements": list(pipeline_state.get("extracted_elements", []) or []),
        "dialogue_entries": [],
        "intermediate": {},
        "error": None,
    }


def run_multi_scene_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """阶段 1/3：多物体场景设计分析，产出设计方案与参考图。"""
    # 延迟导入避免循环依赖；复用预构建图实例，不重复编译
    from ..integrated_multi_scene_workflow import (
        WORKFLOWS as _MS_WORKFLOWS,
        MULTI_SCENE_FUNCTION_ID,
    )

    _logger.info("[Pipeline] ▶ 阶段 1/3 multi_scene_workflow 开始")
    _push_pipeline_progress(state, "正在分析场景，生成设计方案...", "multi_scene")

    sub_state: MultiSceneWorkflowState = _make_sub_state(state, MULTI_SCENE_FUNCTION_ID)  # type: ignore[assignment]
    graph = _MS_WORKFLOWS[MULTI_SCENE_FUNCTION_ID]
    final = graph.invoke(sub_state)

    # 自动绕过 human_review，避免审核节点阻塞流水线
    if final.get("awaiting_review"):
        review_data = final.get("intermediate", {}).get("human_review", {})
        elements = review_data.get("elements", [])
        _logger.info("[Pipeline] auto-approving human_review: %d elements", len(elements))
        final["approved_elements"] = elements
        final["metadata"] = dict(final.get("metadata", {}))
        final["metadata"]["resume_from_review"] = True
        final["awaiting_review"] = False
        final = graph.invoke(final)

    approved_count = len(final.get("global_assets", {}).get("multi_scene", {}).get("approved_elements", []))
    _logger.info("[Pipeline] ✔ 阶段 1/3 完成，approved_elements=%d", approved_count)
    _push_pipeline_progress(state, f"场景分析完成，{approved_count} 个设计元素", "multi_scene")

    return {
        "global_assets": final.get("global_assets", {}),
        "dialogue_entries": final.get("dialogue_entries", []),
    }


def run_model_retrieval_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """阶段 2/3：模型检索与 3D 生成，为每个设计元素生成/检索 3D 模型。"""
    from ..model_retrieval_workflow import (
        WORKFLOWS as _MR_WORKFLOWS,
        MODEL_RETRIEVAL_FUNCTION_ID,
    )

    _logger.info("[Pipeline] ▶ 阶段 2/3 model_retrieval_workflow 开始")
    _push_pipeline_progress(state, "正在检索已有模型并生成 3D...", "model_retrieval")

    sub_state: ModelRetrievalWorkflowState = _make_sub_state(state, MODEL_RETRIEVAL_FUNCTION_ID)  # type: ignore[assignment]
    # 单场景跳过六视图截图（GPU 资源有限，Hunyuan3D 已返回预览图）
    sub_state.setdefault("metadata", {})["skip_six_view_capture"] = True
    graph = _MR_WORKFLOWS[MODEL_RETRIEVAL_FUNCTION_ID]
    final = graph.invoke(sub_state)

    model_results = final.get("global_assets", {}).get("model_retrieval", {}).get("model_results", [])
    generated = sum(1 for r in model_results if r.get("source") == "generation" and not r.get("error"))
    _logger.info("[Pipeline] ✔ 阶段 2/3 完成，model_results=%d", len(model_results))
    _push_pipeline_progress(state, f"3D 模型就绪，共 {len(model_results)} 个（新生成 {generated} 个）", "model_retrieval")

    return {
        "global_assets": final.get("global_assets", {}),
        "dialogue_entries": final.get("dialogue_entries", []),
    }


def _resolve_composition_workflow(state: Dict[str, Any]):
    """根据 function_id 选择场景组装版本。"""
    fid = state.get("function_id", 0)
    if fid == FULL_PIPELINE_V2_FUNCTION_ID:
        from ..scene_composition_workflow_v2 import (
            WORKFLOWS as _SC_WORKFLOWS,
            SCENE_COMPOSITION_V2_FUNCTION_ID as _SC_FID,
        )
        return _SC_WORKFLOWS, _SC_FID, "v2"
    from ..scene_composition_workflow import (
        WORKFLOWS as _SC_WORKFLOWS,
        SCENE_COMPOSITION_FUNCTION_ID as _SC_FID,
    )
    return _SC_WORKFLOWS, _SC_FID, "v1"


def run_scene_composition_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """阶段 3/3：场景组合，将 3D 模型导入并编排最终场景。"""
    sc_workflows, sc_fid, sc_version = _resolve_composition_workflow(state)

    _logger.info("[Pipeline] ▶ 阶段 3/3 scene_composition_%s 开始", sc_version)
    _push_pipeline_progress(state, f"正在进行场景布局与模型导入 ({sc_version})...", "scene_composition")

    sub_state: SceneCompositionWorkflowState = _make_sub_state(state, sc_fid)  # type: ignore[assignment]

    # 优先使用 multi_scene 阶段生成的详细布局描述作为 compose prompt，
    # 其中包含每个物品的位置、风格、搭配等信息，比原始用户输入更精准。
    layout_text: str = (
        state.get("global_assets", {}).get("multi_scene", {}).get("layout_text", "")
    )
    if layout_text:
        sub_state["prompt"] = layout_text
        _logger.info(
            "[Pipeline] 使用 multi_scene.layout_text 作为场景组合 prompt (%d 字符)",
            len(layout_text),
        )

    graph = sc_workflows[sc_fid]
    final = graph.invoke(sub_state)

    scene_path = final.get("global_assets", {}).get("scene_composition", {}).get("scene_path", "")
    _logger.info("[Pipeline] ✔ 阶段 3/3 (%s) 完成，scene_path=%s", sc_version, scene_path)
    _push_pipeline_progress(state, f"场景生成完毕 ({sc_version}) ✓", "scene_composition")

    return {
        "global_assets": final.get("global_assets", {}),
        "dialogue_entries": final.get("dialogue_entries", []),
    }
