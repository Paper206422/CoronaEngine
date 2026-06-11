"""
场景组装 v3: 分层 DAG + 每层独立审查 + 差量修正

三层:
  tier1: 大件 (LLM 绝对坐标)
  tier2: 从属 (锚点关系 → place_object_near 计算坐标)
  tier3: 装饰 (LLM 绝对坐标, 同 tier1)

DAG:
  collect_models → tier1_place → capture* → tier1_review
                   ↑ FAIL                       ↓ PASS
                   └────────────────────────────┘
                                                tier2_place → capture* → tier2_review
                                                ↑ FAIL                    ↓ PASS
                                                └─────────────────────────┘
                                                                          tier3_place → capture* → tier3_review
                                                                          ↑ FAIL                    ↓ PASS
                                                                          └─────────────────────────┘
                                                                                                    output_result → END

* capture 在 tier_review 内部调用, 每层独立拍摄 (场景状态不同, 不能共享)

命令: /scene_composition_v2 (21006)
"""

from __future__ import annotations

from typing import Dict, TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from Quasar.ai_workflow.executor import register_workflow_checkpoints
from Quasar.ai_workflow.state import SceneCompositionWorkflowState

from ..scene_composition_workflow.collect_models import collect_models_node
from ..scene_composition_workflow.output_result import output_result_node

from .nodes_tier_place import tier1_place_node, tier2_place_node, tier3_place_node
from .nodes_tier_review import tier1_review_node, tier2_review_node, tier3_review_node
from .nodes_tier_review import MAX_TIER_RETRIES

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

SCENE_COMPOSITION_V2_FUNCTION_ID = 21006


# ===========================================================================
# 条件路由 (retry_diff / retry_all → tier_place, pass → next tier)
# ===========================================================================

def _route_tier1(state) -> str:
    decision = state.get("intermediate", {}).get("tier1_review_decision", "pass")
    count = state.get("intermediate", {}).get("tier1_retry_count", 0)
    if decision == "fail" and count <= MAX_TIER_RETRIES:
        return "tier1_place"
    return "tier2_place"


def _route_tier2(state) -> str:
    decision = state.get("intermediate", {}).get("tier2_review_decision", "pass")
    count = state.get("intermediate", {}).get("tier2_retry_count", 0)
    if decision == "fail" and count <= MAX_TIER_RETRIES:
        return "tier2_place"
    return "tier3_place"


def _route_tier3(state) -> str:
    decision = state.get("intermediate", {}).get("tier3_review_decision", "pass")
    count = state.get("intermediate", {}).get("tier3_retry_count", 0)
    if decision == "fail" and count <= MAX_TIER_RETRIES:
        return "tier3_place"
    return "output_result"


# ===========================================================================
# DAG
# ===========================================================================

def build_scene_composition_v2_workflow() -> "CompiledStateGraph":
    graph = StateGraph(SceneCompositionWorkflowState)

    graph.add_node("collect_models", collect_models_node)
    graph.add_node("tier1_place", tier1_place_node)
    graph.add_node("tier1_review", tier1_review_node)
    graph.add_node("tier2_place", tier2_place_node)
    graph.add_node("tier2_review", tier2_review_node)
    graph.add_node("tier3_place", tier3_place_node)
    graph.add_node("tier3_review", tier3_review_node)
    graph.add_node("output_result", output_result_node)

    graph.add_edge(START, "collect_models")
    graph.add_edge("collect_models", "tier1_place")
    graph.add_edge("tier1_place", "tier1_review")
    graph.add_conditional_edges("tier1_review", _route_tier1, {
        "tier1_place": "tier1_place",
        "tier2_place": "tier2_place",
    })
    graph.add_edge("tier2_place", "tier2_review")
    graph.add_conditional_edges("tier2_review", _route_tier2, {
        "tier2_place": "tier2_place",
        "tier3_place": "tier3_place",
    })
    graph.add_edge("tier3_place", "tier3_review")
    graph.add_conditional_edges("tier3_review", _route_tier3, {
        "tier3_place": "tier3_place",
        "output_result": "output_result",
    })
    graph.add_edge("output_result", END)

    return graph.compile()


# ===========================================================================
# 注册
# ===========================================================================

WORKFLOWS: Dict[int, "CompiledStateGraph"] = {
    SCENE_COMPOSITION_V2_FUNCTION_ID: build_scene_composition_v2_workflow(),
}

WORKFLOW_COMMANDS: Dict[str, int] = {
    "/scene_composition_v2": SCENE_COMPOSITION_V2_FUNCTION_ID,
    "/sc_v2": SCENE_COMPOSITION_V2_FUNCTION_ID,
}

register_workflow_checkpoints(
    SCENE_COMPOSITION_V2_FUNCTION_ID,
    {"tier1_place", "tier1_review", "tier2_place", "tier2_review",
     "tier3_place", "tier3_review", "output_result"},
)

__all__ = [
    "WORKFLOWS",
    "WORKFLOW_COMMANDS",
    "SCENE_COMPOSITION_V2_FUNCTION_ID",
    "build_scene_composition_v2_workflow",
]
