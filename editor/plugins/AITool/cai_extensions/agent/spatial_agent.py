"""空间推理 Agent"""
from __future__ import annotations
import json, logging, math
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

COT_SYSTEM_PROMPT = """你是空间推理专家。按5步推理后输出JSON: {"position":[x,y,z],"rotation":[rx,ry,rz],"scale":[sx,sy,sz],"position_candidates":[[x,y,z]],"reasoning_steps":[],"confidence":0.85,"warnings":[]}。只输出JSON。"""

class SpatialAgent:
    def __init__(self, timeout: float = 20.0): self.timeout = timeout

    def solve(self, intent: Dict[str, Any], scene_state: Dict[str, Any] = None, use_cot: bool = False) -> Dict[str, Any]:
        action = intent.get("action", "add"); params = intent.get("parameters", {})
        if action in ("delete", "question"): return {"position": None, "rotation": None, "scale": None, "method": "noop", "confidence": 1.0, "warnings": [], "reasoning_steps": [f"'{action}' 无需坐标"]}
        relation = self._build_relation(intent, scene_state)
        try:
            result = self._solve_with_solver(relation, scene_state)
            if result: result["method"] = "solver"; return result
        except Exception as e: logger.warning("[SpatialAgent] Solver failed: %s", e)
        if use_cot or relation:
            try:
                result = self._solve_with_cot(intent, scene_state)
                if result: result["method"] = "cot"; return result
            except Exception as e: logger.warning("[SpatialAgent] CoT failed: %s", e)
        logger.warning("[SpatialAgent] using room center default")
        return self._default_result(intent)

    def _build_relation(self, intent, scene_state=None) -> Optional[Dict[str, Any]]:
        if intent.get("action") != "add": return None
        target = intent.get("target", ""); params = intent.get("parameters", {})
        relation_type = params.get("relation", "near"); relation_target = params.get("relation_target", "")
        distance = params.get("distance_guide", 0.5)
        solver_map = {"near":"near_anchor","left":"near_anchor","right":"near_anchor","on":"on_surface","in_front":"in_front","against_wall":"against_wall","between":"between","under":"center_under_group","center":"center_under_group"}
        solver_rel = solver_map.get(relation_type, "near_anchor")
        relation = {"object_id": target, "relation": solver_rel, "distance": distance, "scale": [1,1,1], "rotation": [0,0,0]}
        if relation_target: relation["target"] = relation_target
        if relation_type in ("left","right"): relation["side"] = relation_type; relation["target"] = relation_target or self._find_default_anchor(scene_state)
        if relation_type == "against_wall": relation["target"] = self._infer_wall(params, scene_state); relation["offset"] = max(0.2, min(1.0, distance))
        return relation

    def _infer_wall(self, params, scene_state=None) -> str:
        combined = f"{params.get('zone','')} {params.get('relation_target','')}".lower()
        if "back" in combined or "后" in combined or "吧台" in combined: return "back"
        if "front" in combined or "前" in combined: return "front"
        if "left" in combined or "左" in combined: return "left"
        if "right" in combined or "右" in combined: return "right"
        return "back"

    def _find_default_anchor(self, scene_state=None) -> str:
        scene = scene_state or {}; intermediate = scene.get("intermediate", {})
        locked = intermediate.get("locked_actors", intermediate.get("scene_actors", []))
        if locked: return locked[0].get("name", locked[0].get("actor_name", "anchor"))
        return "anchor"

    def _solve_with_solver(self, relation, scene_state=None) -> Optional[Dict[str, Any]]:
        try:
            from ..flows.scene_composition_workflow_v2.constraint_solver import solve_relations
            scene = scene_state or {}; metadata = scene.get("metadata", {})
            room_size = metadata.get("room_size", [5, 3, 3])
            placed = self._extract_placed_objects(scene_state)
            solved = solve_relations([relation], room_size, metadata.get("asset_metadata", {}), placed=placed)
            if not solved: return None
            oid = relation.get("object_id", ""); r = solved.get(oid)
            if not r: return None
            pos, rot, scl = r.get("pos", [0,0,0]), r.get("rot", [0,0,0]), r.get("scale", [1,1,1])
            warnings = []
            if self._check_collision(pos, scl, scene_state):
                adj = self._resolve_collision(pos, scl, scene_state)
                if adj: pos = adj; warnings.append("碰撞已偏移")
            return {"position": pos, "rotation": rot, "scale": scl, "position_candidates": [pos], "reasoning_steps": [f"Solver: {relation.get('relation','?')}"], "confidence": 0.85, "warnings": warnings}
        except ImportError: return None

    def _solve_with_cot(self, intent, scene_state=None) -> Optional[Dict[str, Any]]:
        scene = scene_state or {}; metadata = scene.get("metadata", {}); room_size = metadata.get("room_size", [5, 3, 3])
        placed = self._extract_placed_objects(scene_state)
        objects_text = "\n".join(f"  - {k}: {v.get('pos',v.get('position','?'))}" for k, v in (placed or {}).items()) if placed else "  无"
        x_half, z_half = room_size[0] / 2, room_size[1] / 2 if len(room_size) > 1 else 2.5
        prompt = f"""## 房间 {room_size[0]}×{room_size[1]}×{room_size[2] if len(room_size)>2 else 3}m X∈[{-x_half:.1f},{x_half:.1f}] Z∈[{-z_half:.1f},{z_half:.1f}]\n## 意图 动作:{intent.get('action')} 目标:{intent.get('target')} 参数:{json.dumps(intent.get('parameters',{}),ensure_ascii=False)}\n## 已有物体\n{objects_text}\n按5步推理输出JSON。"""
        from Quasar.ai_models.base_pool.registry import get_chat_model
        def _do(): return get_chat_model(temperature=0.3,request_timeout=30.0).invoke([SystemMessage(content=COT_SYSTEM_PROMPT),HumanMessage(content=prompt)])
        executor = ThreadPoolExecutor(max_workers=1); future = executor.submit(_do)
        try: response = future.result(timeout=self.timeout)
        except FuturesTimeoutError: executor.shutdown(wait=False,cancel_futures=True); return None
        except Exception as e: executor.shutdown(wait=False); return None
        else: executor.shutdown(wait=False)
        text = (response.content if hasattr(response,"content") else str(response)).strip()
        if "```" in text: s=text.find("{"); e=text.rfind("}"); text=text[s:e+1] if s!=-1 and e!=-1 else text
        try:
            data = json.loads(text)
            pos = data.get("position")
            if not pos or len(pos) < 3: return None
            return {"position":[float(v) for v in pos[:3]],"rotation":[float(v) for v in data.get("rotation",[0,0,0])[:3]],"scale":[float(v) for v in data.get("scale",[1,1,1])[:3]],"position_candidates":data.get("position_candidates",[pos]),"reasoning_steps":data.get("reasoning_steps",[]),"confidence":float(data.get("confidence",0.7)),"warnings":data.get("warnings",[])}
        except json.JSONDecodeError: return None

    def _check_collision(self, position, scale, scene_state=None, threshold=0.15) -> bool:
        try:
            from ..flows.scene_composition_workflow_v2.nodes_tier_place import _check_overlap
            return _check_overlap(position, scale, self._extract_existing_list(scene_state), threshold=threshold)
        except ImportError: return self._simple_collision_check(position, scene_state)

    def _resolve_collision(self, position, scale, scene_state=None) -> Optional[List[float]]:
        offsets = [(0.5,0),(-0.5,0),(0,0.5),(0,-0.5),(0.8,0),(-0.8,0),(0,0.8),(0,-0.8)]
        for dx, dz in offsets:
            test = [position[0]+dx, position[1], position[2]+dz]
            if not self._check_collision(test, scale, scene_state, threshold=0.1): return test
        return None

    def _simple_collision_check(self, position, scene_state=None, threshold=0.3) -> bool:
        existing = self._extract_existing_list(scene_state)
        for ex in existing:
            ep = ex.get("pos", ex.get("position", [0,0,0]))
            if len(ep) >= 2 and abs(position[0]-ep[0]) < 0.8+threshold and abs(position[2]-ep[2]) < 0.8+threshold: return True
        return False

    def _extract_placed_objects(self, scene_state=None) -> Dict[str, Dict[str, Any]]:
        if not scene_state: return {}
        intermediate = scene_state.get("intermediate", {}); locked = intermediate.get("locked_actors", intermediate.get("scene_actors", []))
        return {a.get("name", a.get("actor_name", a.get("object_id", ""))): {"pos": a.get("position", a.get("pos", [0,0,0])), "scale": a.get("scale", [1,1,1])} for a in locked if a.get("name") or a.get("actor_name") or a.get("object_id")}

    def _extract_existing_list(self, scene_state=None) -> List[Dict[str, Any]]:
        placed = self._extract_placed_objects(scene_state)
        return [{"pos": v["pos"], "scale": v["scale"], "name": k} for k, v in placed.items()]

    def _default_result(self, intent) -> Dict[str, Any]:
        return {"position": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0], "scale": [1.0, 1.0, 1.0], "method": "default", "confidence": 0.2, "warnings": ["默认位置(房间中心)"], "reasoning_steps": ["全部回退"]}

__all__ = ["SpatialAgent"]
