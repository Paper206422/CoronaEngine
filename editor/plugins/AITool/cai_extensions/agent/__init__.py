"""场景组装 Agent — 交互式自然语言场景编辑 + LANChat 全能力接管"""
from __future__ import annotations
from typing import Dict, TYPE_CHECKING
from langgraph.graph import END, START, StateGraph
from Quasar.ai_workflow.executor import register_workflow_checkpoints
from Quasar.ai_workflow.state import SceneCompositionWorkflowState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

SCENE_AGENT_FUNCTION_ID = 21007

def parse_intent_node(state: dict) -> dict:
    from .intent_agent import IntentAgent
    user_text = state.get("current_instruction", "") or state.get("prompt", "")
    if not user_text: return state
    agent = IntentAgent(); intent = agent.analyze(user_text, scene_state=state)
    state.setdefault("intermediate", {})["agent_intent"] = intent
    return state

def solve_spatial_node(state: dict) -> dict:
    from .spatial_agent import SpatialAgent
    intermediate = state.get("intermediate", {}); intent = intermediate.get("agent_intent", {})
    agent = SpatialAgent(); result = agent.solve(intent, scene_state=state)
    intermediate["agent_spatial"] = result; return state

def validate_node(state: dict) -> dict:
    from .coordinator import AgentCoordinator
    intermediate = state.get("intermediate", {})
    coordinator = AgentCoordinator()
    intermediate["agent_validation"] = coordinator.validate(
        intermediate.get("agent_intent", {}), intermediate.get("agent_spatial", {}), scene_state=state)
    return state

def execute_node(state: dict) -> dict:
    from .coordinator import AgentCoordinator
    intermediate = state.get("intermediate", {})
    coordinator = AgentCoordinator()
    intermediate["agent_result"] = coordinator.execute(
        intermediate.get("agent_intent", {}), intermediate.get("agent_spatial", {}),
        intermediate.get("agent_validation", {}), scene_state=state)
    return state

def build_scene_agent_workflow() -> "CompiledStateGraph":
    graph = StateGraph(SceneCompositionWorkflowState)
    for name, node in [("parse_intent", parse_intent_node), ("solve_spatial", solve_spatial_node),
                        ("validate", validate_node), ("execute", execute_node)]:
        graph.add_node(name, node)
    graph.add_edge(START, "parse_intent"); graph.add_edge("parse_intent", "solve_spatial")
    graph.add_edge("solve_spatial", "validate"); graph.add_edge("validate", "execute")
    graph.add_edge("execute", END); return graph.compile()

WORKFLOWS: Dict[int, "CompiledStateGraph"] = {SCENE_AGENT_FUNCTION_ID: build_scene_agent_workflow()}
WORKFLOW_COMMANDS: Dict[str, int] = {"/scene_agent": SCENE_AGENT_FUNCTION_ID, "/sc_agent": SCENE_AGENT_FUNCTION_ID}
register_workflow_checkpoints(SCENE_AGENT_FUNCTION_ID, {"parse_intent", "solve_spatial", "validate", "execute"})

__all__ = ["WORKFLOWS", "WORKFLOW_COMMANDS", "SCENE_AGENT_FUNCTION_ID", "build_scene_agent_workflow"]
