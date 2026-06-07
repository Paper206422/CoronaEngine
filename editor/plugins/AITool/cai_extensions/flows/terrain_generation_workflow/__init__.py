"""
Terrain Generation Workflow — LangGraph DAG

START → analyze_params → generate_terrain → output_result → END

命令: /terrain_generate, /terrain
"""
from __future__ import annotations

from typing import Dict, TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from Quasar.ai_workflow.executor import register_workflow_checkpoints
from Quasar.ai_workflow.state import WorkflowState

from .constants import TERRAIN_GENERATE_FUNCTION_ID
from .nodes import analyze_params_node, generate_terrain_node, output_result_node

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


def build_terrain_workflow() -> "CompiledStateGraph":
    graph = StateGraph(WorkflowState)

    graph.add_node("analyze_params", analyze_params_node)
    graph.add_node("generate_terrain", generate_terrain_node)
    graph.add_node("output_result", output_result_node)

    graph.add_edge(START, "analyze_params")
    graph.add_edge("analyze_params", "generate_terrain")
    graph.add_edge("generate_terrain", "output_result")
    graph.add_edge("output_result", END)

    return graph.compile()


WORKFLOWS: Dict[int, "CompiledStateGraph"] = {
    TERRAIN_GENERATE_FUNCTION_ID: build_terrain_workflow(),
}

WORKFLOW_COMMANDS: Dict[str, int] = {
    "/terrain_generate": TERRAIN_GENERATE_FUNCTION_ID,
    "/terrain": TERRAIN_GENERATE_FUNCTION_ID,
}

register_workflow_checkpoints(
    TERRAIN_GENERATE_FUNCTION_ID,
    {"analyze_params", "generate_terrain", "output_result"},
)

__all__ = [
    "WORKFLOWS",
    "WORKFLOW_COMMANDS",
    "TERRAIN_GENERATE_FUNCTION_ID",
    "build_terrain_workflow",
]
