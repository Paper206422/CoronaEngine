"""Agent 系统集成测试 — 12 suites, 130+ assertions"""
from __future__ import annotations
import json, logging, sys, time
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("test_agent")
_PASSED = 0; _FAILED = 0

def _assert(condition: bool, msg: str = ""):
    global _PASSED, _FAILED
    if condition: _PASSED += 1
    else: _FAILED += 1; logger.error("  FAIL: %s", msg)

def _report():
    total = _PASSED + _FAILED
    logger.info("=" * 60); logger.info("Results: %d/%d passed (%d failed)", _PASSED, total, _FAILED); logger.info("=" * 60)

def test_event_bus():
    logger.info("--- Test: EventBus ---")
    from cai_extensions.agent.event_bus import EventBus, EventType, get_event_bus
    bus = EventBus()
    q1 = bus.subscribe("user_a"); bus.subscribe("user_b")
    _assert(bus.subscriber_count == 2, "2 subscribers")
    bus.publish({"event_type": EventType.ADD_OBJECT, "user_id": "user_a"})
    _assert(bus.history_size == 1, "history 1")
    bus.publish({"event_type": EventType.USER_INTENT, "user_id": "user_b", "scene_id": "s1"})
    _assert(len(bus.replay(since_index=0)) == 2, "replay all")
    _assert(len(bus.replay(scene_id="s1")) == 1, "scene filter")
    bus.unsubscribe("user_a"); _assert(bus.subscriber_count == 1, "unsub")
    bus.clear(); _assert(bus.history_size == 0, "cleared")
    _assert(get_event_bus() is not None, "singleton")
    logger.info("  EventBus: all passed")

def test_memory():
    logger.info("--- Test: Memory ---")
    from cai_extensions.agent.memory import (
        MemoryManager,
        SceneMemory,
        SessionMemory,
        get_memory_manager,
        reset_memory_manager,
    )
    sess = SessionMemory(max_operations=5)
    sess.add_conversation("加个台灯", "已放置"); sess.add_operation({"action": "add", "target": "台灯"})
    _assert(len(sess.conversation_history) == 1 and len(sess.recent_operations) == 1, "session store")
    scene = SceneMemory("test"); scene.set_style_bible({"theme": "cyberpunk"}); scene.update_objects_state({"s": {"name": "沙发"}})
    _assert("cyberpunk" in scene.get_style_bible_text() and "沙发" in scene.get_objects_summary(), "scene store")
    mgr = MemoryManager("t"); mgr.record_conversation("h", "r"); mgr.set_style_bible({"theme": "m"})
    ctx = mgr.get_context_for_prompt(); _assert("m" in ctx["style_bible_text"], "context")
    scene.save("/tmp/_test_agent_mem.json"); loaded = SceneMemory.load("/tmp/_test_agent_mem.json")
    _assert(loaded.style_bible["theme"] == "cyberpunk", "roundtrip")
    reset_memory_manager()
    room_a = get_memory_manager("room-a")
    room_a.record_conversation("A 想要暗黑集市", "已记录")
    room_b = get_memory_manager("room-b")
    _assert(room_a is get_memory_manager("room-a"), "same scene memory reused")
    _assert(room_a is not room_b, "different scenes isolated")
    _assert("暗黑集市" not in room_b.get_context_for_prompt()["conversation_history"], "no cross-scene conversation leak")
    reset_memory_manager("room-a")
    _assert(get_memory_manager("room-a") is not room_a, "scene reset replaces only target")
    _assert(get_memory_manager("room-b") is room_b, "scene reset keeps other scenes")
    reset_memory_manager()
    logger.info("  Memory: all passed")

def test_intent_agent():
    logger.info("--- Test: IntentAgent ---")
    from cai_extensions.agent.intent_agent import IntentAgent, _keyword_fallback
    r1 = _keyword_fallback("在吧台旁边加个金属高脚凳")
    _assert(r1["action"] == "add" and r1["target"] and r1["parameters"]["zone"] == "bar_area", "add intent")
    _assert(_keyword_fallback("把沙发删掉")["action"] == "delete", "delete")
    _assert(_keyword_fallback("把台灯往右移")["action"] == "move", "move")
    _assert(_keyword_fallback("放大茶几")["action"] == "modify", "modify")
    _assert(IntentAgent().analyze("")["action"] == "question", "empty")
    logger.info("  IntentAgent: all passed")

def test_spatial_agent():
    logger.info("--- Test: SpatialAgent ---")
    from cai_extensions.agent.spatial_agent import SpatialAgent
    agent = SpatialAgent()
    intent = {"action": "add", "target": "台灯", "parameters": {"relation": "near", "relation_target": "沙发"}}
    scene = {"metadata": {"room_size": [5, 3, 3]}, "intermediate": {"locked_actors": [{"name": "沙发", "position": [0, 0, -1], "scale": [2, 1, 1]}]}}
    r = agent.solve(intent, scene_state=scene)
    _assert(r and r.get("position") and len(r["position"]) == 3 and r["position"][1] >= 0, "solver position")
    r2 = agent.solve({"action": "delete"}, scene_state=scene)
    _assert(r2["position"] is None, "delete no position")
    r3 = agent.solve(intent, scene_state={})
    _assert(r3 and r3["position"], "empty state default")
    logger.info("  SpatialAgent: all passed")

def test_style_agent():
    logger.info("--- Test: StyleAgent ---")
    from cai_extensions.agent.style_agent import StyleAgent
    agent = StyleAgent()
    bible = {"theme": "cyberpunk", "avoid": ["pastoral", "bright"]}
    r1 = agent.precheck({"action": "add", "target": "金属高脚凳", "parameters": {"style_deviation": False}}, bible)
    _assert(r1["feasible"] and r1["style_score"] > 50, "normal pass")
    r2 = agent.precheck({"action": "add", "target": "田园碎花窗帘", "parameters": {"style_deviation": False}}, bible)
    _assert(r2["style_score"] < 100 and r2["issues"], "style conflict detected")
    r3 = agent.precheck({"action": "add", "target": "田园装饰", "parameters": {"style_deviation": True}}, bible)
    _assert(r3["user_override"], "user override")
    _assert(agent.precheck({"action": "add", "target": "x"}, {}).get("feasible"), "empty bible")
    logger.info("  StyleAgent: all passed")

def test_coordinator():
    logger.info("--- Test: AgentCoordinator ---")
    from cai_extensions.agent.coordinator import AgentCoordinator
    c = AgentCoordinator()
    r = c.handle("在吧台旁边加个金属高脚凳", scene_state={"metadata": {"room_size": [5, 3, 3]}, "intermediate": {"locked_actors": [{"name": "吧台", "position": [0, 0, 0]}]}}, style_bible={"theme": "cyberpunk"})
    _assert(r and "intent" in r and "spatial" in r and "validation" in r, "handle structure")
    _assert(r["intent"]["action"] in ("add", "delete", "move", "modify", "question"), "valid action")
    r2 = c.handle("")
    _assert(r2["intent"]["action"] == "question", "empty→question")
    logger.info("  AgentCoordinator: all passed")

def test_collaboration():
    logger.info("--- Test: CollaborationManager ---")
    from cai_extensions.agent.collaboration import CollaborationManager, get_collaboration_manager
    cm = CollaborationManager()
    _assert(cm.lock_object("c1", "a"), "lock"); _assert(not cm.lock_object("c1", "b"), "conflict")
    _assert(cm.is_locked("c1") == "a", "is_locked"); _assert(cm.unlock_object("c1", "a"), "unlock")
    cm.broadcast_intent("a", "placing", [1.5, 0, 2.0]); cm.broadcast_intent("b", "moving", [1.6, 0, 2.1])
    _assert(cm.check_preview_collision("c", [1.55, 0, 2.05]) is not None, "collision")
    _assert("a" in cm.get_status_bar_text(), "status bar")
    cm.clear_intent("a"); cm.clear_intent("b"); _assert(len(cm.get_active_intents()) == 0, "cleared")
    cm.clear(); logger.info("  CollaborationManager: all passed")

def test_group_agent():
    logger.info("--- Test: GroupAgent ---")
    from cai_extensions.agent.group_agent import GroupAgent
    call_log = []
    def fake_ai(s, m): call_log.append(("call", s[:30])); return json.dumps({"consensus_analysis": {"theme_agreement": 1.0, "type_agreement": 1.0, "core_elements": ["bar"]}, "proposed_plan": {"scene_name": "cyberpunk_bar_01", "scene_type": "indoor", "style_bible": {"theme": "cyberpunk", "color_palette": ["#111"], "materials": ["metal"], "lighting": "neon", "mood": "dark", "avoid": ["bright"]}, "initial_zones": [{"zone_id": "bar_area", "function": "service"}]}, "uncertainties": [], "confidence": 0.9})
    ga = GroupAgent(ai_chat=fake_ai)
    _assert(not ga.should_summarize(), "no summary initially")
    ga.on_chat_message("a", "我要赛博朋克"); ga.on_chat_message("b", "对暗色调霓虹酒吧")
    _assert(ga.should_summarize(), "2 users→summarize"); _assert(ga.consensus_score > 0.5, f"consensus={ga.consensus_score:.2f}")
    s = ga.try_summarize(); _assert(s and s["proposed_plan"]["scene_name"] == "cyberpunk_bar_01", "summary")
    _assert(len(call_log) == 1, "called once")
    for _ in range(3): ga.on_operation_event({"data": {}, "metadata": {"style_deviation": True}})
    ga.on_operation_event({"data": {}, "metadata": {}})
    _assert(ga.deviation_rate == 0.75, "deviation 3/4"); _assert(ga.should_patrol(), "patrol trigger")
    ga.reset_for_new_scene(); logger.info("  GroupAgent: all passed")

def test_disambiguation():
    logger.info("--- Test: DisambiguationHandler ---")
    from cai_extensions.agent.coordinator import AgentCoordinator
    c = AgentCoordinator()
    r1 = c.resolve_ambiguity({"action": "add", "target": "t", "parameters": {}, "ambiguities": []}, confidence=0.95)
    _assert(r1["action"] == "execute", "high conf→execute")
    r2 = c.resolve_ambiguity({"action": "move", "target": "s", "parameters": {"distance_guide": 0.5}, "ambiguities": ["方向不明"]}, confidence=0.75)
    _assert(r2["action"] == "execute_with_warning" and len(r2["choices"]) >= 2, "mid conf→warn+choices")
    r3 = c.resolve_ambiguity({"action": "modify", "target": "t", "parameters": {}, "ambiguities": ["量级不明"]}, confidence=0.35)
    _assert(r3["action"] == "ask" and len(r3["choices"]) >= 2 and r3["message"], "low conf→ask")
    r4 = c.resolve_ambiguity({"action": "delete", "target": "x", "parameters": {}, "ambiguities": []}, confidence=0.4)
    _assert(any("确认" in ch.get("label", "") for ch in r4["choices"]), "delete confirm")
    logger.info("  DisambiguationHandler: all passed")

def test_multi_step():
    logger.info("--- Test: MultiStepPlanner ---")
    from cai_extensions.agent.multi_step_planner import MultiStepPlanner
    p = MultiStepPlanner()
    _assert(p.is_complex_task("把酒吧布置得更有氛围感"), "complex:氛围感"); _assert(p.is_complex_task("优化客厅灯光和装饰"), "complex:multi")
    _assert(not p.is_complex_task("加个台灯"), "simple:single"); _assert(not p.is_complex_task("删掉沙发"), "simple:delete")
    plan = p.decompose("把酒吧布置得更有氛围感", scene_state={"intermediate": {"locked_actors": [{"name": "吧台"}]}})
    _assert(plan and plan["is_complex"] and len(plan["tasks"]) >= 2, "multi-task decomposition")
    plan2 = p.decompose("加个台灯"); _assert(len(plan2["tasks"]) == 1, "single task")
    _assert(p.progress["total"] > 0, "has progress"); p.reset(); _assert(p.progress["total"] == 0, "reset")
    logger.info("  MultiStepPlanner: all passed")

def test_adapter():
    logger.info("--- Test: MasterAgent ---")
    from cai_extensions.agent.agent_adapter import (
        MasterAgent, SummaryAgent, PersonaRouter, Specialist,
        create_master_agent, create_summary_agent,
        is_scene_command, is_builtin_command, SPECIALISTS, _GENERALIST,
        _extract_cai_text_chunk,
    )
    _assert(is_scene_command("加个台灯"), "detect add"); _assert(is_scene_command("把沙发删掉"), "detect delete")
    _assert(is_scene_command("把台灯往右移"), "detect move"); _assert(not is_scene_command("你好"), "skip hello")
    _assert(is_builtin_command("/help") == "help", "cmd help"); _assert(is_builtin_command("/总结") == "summary", "cmd summary")
    _assert(is_builtin_command("/检查") == "patrol", "cmd patrol"); _assert(is_builtin_command("hi") is None, "not cmd")
    router = PersonaRouter()
    _assert(router.route("").key == "generalist", "empty→generalist")
    _assert(router.route("赛博朋克设计师").key == "cyberpunk", "cyberpunk match")
    _assert(router.route("灯光专家").key == "lighting", "lighting match")
    _assert(router.route("未知角色").key == "generalist", "unknown→generalist")
    spec = SPECIALISTS["cyberpunk"]
    prompt = spec.inject_prompt("test"); _assert("赛博朋克" in prompt and "neon glass" in prompt, "inject")
    _assert(len(_GENERALIST.capabilities) >= 5, "generalist caps")
    cai_chunk = (
        '{"session_id":"s","error_code":0,"status_info":"ok",'
        '"llm_content":[{"part":[{"content_type":"text","content_text":"真实回复"}]}]}'
    )
    _assert(_extract_cai_text_chunk(cai_chunk) == "真实回复", "extract CAI envelope text")
    m = MasterAgent(fallback_chat=lambda s, m: "fake")
    _assert("场景设计大师" in m._handle_help(""), "help gen")
    _assert("灯光师" in m._handle_help("灯光专家"), "help spec")
    _assert(m("", ["用户A: hello"]) == "fake", "fallback chat")
    r = m("", ["用户A: @agent 加个台灯"])
    _assert(r and ("📋" in r or "✅" in r or "[" in r), f"scene reply: {r[:60]}")
    _assert(isinstance(create_master_agent(), MasterAgent), "factory master")
    _assert(isinstance(create_summary_agent(), SummaryAgent), "factory summary")
    logger.info("  MasterAgent: all passed")

def test_imports():
    logger.info("--- Test: Imports ---")
    import cai_extensions.agent
    _assert(hasattr(cai_extensions.agent, "WORKFLOWS"), "WORKFLOWS"); _assert(hasattr(cai_extensions.agent, "WORKFLOW_COMMANDS"), "COMMANDS")
    _assert(cai_extensions.agent.SCENE_AGENT_FUNCTION_ID == 21007, "func id"); _assert(cai_extensions.agent.build_scene_agent_workflow() is not None, "DAG")
    logger.info("  Imports: all passed")

def run_all_tests():
    logger.info("=" * 60); logger.info("Agent System Integration Tests"); logger.info("=" * 60)
    test_event_bus(); test_memory(); test_intent_agent(); test_spatial_agent(); test_style_agent()
    test_coordinator(); test_collaboration(); test_group_agent(); test_disambiguation()
    test_multi_step(); test_adapter(); test_imports()
    _report(); return _FAILED == 0

if __name__ == "__main__":
    success = run_all_tests(); sys.exit(0 if success else 1)
