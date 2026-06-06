"""
Multi-Scene Parallel Generation Workflow (B任务)

将用户的高层空间需求拆解为 N 个子场景，并行生成 3D 模型（Phase 1），
再串行导入引擎（Phase 2），最后汇总结果。

命令: /parallel_generate
DAG: decompose → classify_terrain → fork_generate → [checkpoint] → serial_compose → aggregate → END
"""
from __future__ import annotations

from typing import Dict, TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from Quasar.ai_workflow.executor import register_workflow_checkpoints
from Quasar.ai_workflow.state import WorkflowState

from .constants import PARALLEL_GENERATE_FUNCTION_ID
from .nodes import (
    classify_and_generate_terrain_node,
    decompose_node,
    fork_generate_node,
    serial_compose_node,
    aggregate_node,
)

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


def build_parallel_generate_workflow() -> "CompiledStateGraph":
    graph = StateGraph(WorkflowState)

    graph.add_node("decompose", decompose_node)
    graph.add_node("classify_terrain", classify_and_generate_terrain_node)
    graph.add_node("fork_generate", fork_generate_node)
    graph.add_node("serial_compose", serial_compose_node)
    graph.add_node("aggregate", aggregate_node)

    graph.add_edge(START, "decompose")
    graph.add_edge("decompose", "classify_terrain")
    graph.add_edge("classify_terrain", "fork_generate")
    graph.add_edge("fork_generate", "serial_compose")
    graph.add_edge("serial_compose", "aggregate")
    graph.add_edge("aggregate", END)

    return graph.compile()


WORKFLOWS: Dict[int, "CompiledStateGraph"] = {
    PARALLEL_GENERATE_FUNCTION_ID: build_parallel_generate_workflow(),
}

WORKFLOW_COMMANDS: Dict[str, int] = {
    "/parallel_generate": PARALLEL_GENERATE_FUNCTION_ID,
}

register_workflow_checkpoints(
    PARALLEL_GENERATE_FUNCTION_ID,
    {"decompose", "classify_terrain", "fork_generate", "serial_compose", "aggregate"},
)

__all__ = [
    "WORKFLOWS",
    "WORKFLOW_COMMANDS",
    "PARALLEL_GENERATE_FUNCTION_ID",
    "build_parallel_generate_workflow",
]
