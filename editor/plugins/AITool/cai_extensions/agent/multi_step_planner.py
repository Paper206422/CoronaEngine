"""Multi-Step Planner — 复杂任务分解"""
from __future__ import annotations
import json, logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)
DECOMPOSE_PROMPT = """你是场景规划专家。将复杂需求分解为子任务。输出JSON:{"analysis":"","is_complex":true,"tasks":[{"id":"","description":"","rationale":"","priority":1,"operations":[{"type":"add","object":"","relation":"near","target":""}],"checkpoint":""}]}"""
_COMPLEX_INDICATORS = ["氛围感","氛围","好看","高级","舒服","温馨","酷","布置","整理","优化","提升","改善","整体","所有","全部","整个","重新","风格统一","协调","搭配","灯光","光照","照明","环境"]
_MULTI_OBJECT = ["、","和","还有","另外","顺便","同时","以及"]
_ZONE_COMPLEX = ["灯","画","花","植物","装饰","摆件","地毯","窗帘"]

class MultiStepPlanner:
    def __init__(self, coordinator=None, on_confirm: Callable = None, timeout: float = 30.0):
        self._coordinator = coordinator; self._on_confirm = on_confirm; self.timeout = timeout
        self._current_plan: Optional[Dict] = None; self._completed_tasks: List = []; self._task_index = 0

    @property
    def coordinator(self):
        if self._coordinator is None:
            from .coordinator import AgentCoordinator; self._coordinator = AgentCoordinator()
        return self._coordinator

    @staticmethod
    def is_complex_task(user_text: str) -> bool:
        text = user_text.strip()
        if not text: return False
        score = 0
        if any(kw in text for kw in _COMPLEX_INDICATORS): score += 2
        if sum(1 for kw in _MULTI_OBJECT if kw in text) >= 2: score += 1
        if any(kw in text for kw in _ZONE_COMPLEX): score += 1
        if len(text) > 30: score += 1
        return score >= 2

    def decompose(self, user_text: str, scene_state=None) -> Dict[str, Any]:
        scene = scene_state or {}; metadata = scene.get("metadata", {})
        summary = self._summarize_scene(scene_state)
        prompt = f"## 需求\n{user_text}\n## 当前场景\n{summary}\n## 房间\n{metadata.get('room_size',[5,3,3])}\n请分解为子任务。"
        try:
            from Quasar.ai_models.base_pool.registry import get_chat_model
            def _do(): return get_chat_model(temperature=0.3,request_timeout=45.0).invoke([SystemMessage(content=DECOMPOSE_PROMPT),HumanMessage(content=prompt)])
            executor=ThreadPoolExecutor(max_workers=1); future=executor.submit(_do)
            try: response=future.result(timeout=self.timeout)
            except FuturesTimeoutError: executor.shutdown(wait=False,cancel_futures=True); return self._rule_decompose(user_text)
            else: executor.shutdown(wait=False)
            text=(response.content if hasattr(response,"content") else str(response)).strip()
            if "```" in text: s=text.find("{"); e=text.rfind("}"); text=text[s:e+1] if s!=-1 else text
            result=json.loads(text)
            if result.get("tasks"): self._current_plan=result; return result
        except Exception as e: logger.warning("[MultiStep] LLM decompose failed: %s", e)
        plan = self._rule_decompose(user_text); self._current_plan = plan; return plan

    def _rule_decompose(self, user_text) -> Dict[str, Any]:
        text=user_text.strip(); tasks=[]
        if any(kw in text for kw in ["灯光","光照","灯","照明","暗","亮","氛围感"]):
            tasks.append({"id":"task_light","description":"改善光照","rationale":"检测到光照需求","priority":1,"operations":[{"type":"add","object":"壁灯","relation":"against_wall"}],"checkpoint":"光照确认"})
        if any(kw in text for kw in ["装饰","摆件","花瓶","植物","绿植","花","好看","氛围"]):
            tasks.append({"id":"task_decor","description":"添加装饰","rationale":"检测到装饰需求","priority":2,"operations":[{"type":"add","object":"装饰摆件","relation":"on_surface"}],"checkpoint":"装饰确认"})
        if any(kw in text for kw in ["布局","拥挤","空旷","间距","位置","调整"]):
            tasks.append({"id":"task_space","description":"优化布局","rationale":"检测到空间需求","priority":3,"operations":[{"type":"move","object":"需调整的物体"}],"checkpoint":"布局确认"})
        if not tasks:
            tasks.append({"id":"task_1","description":text,"rationale":"单步","priority":1,"operations":[{"type":"add","object":"待定","relation":"near"}],"checkpoint":"确认"})
        return {"analysis":f"规则分解'{text}'→{len(tasks)}任务","is_complex":len(tasks)>1,"tasks":sorted(tasks,key=lambda t:t["priority"])}

    def execute_step(self, task, scene_state=None, style_bible=None) -> Dict:
        results=[]
        for op in task.get("operations",[]):
            intent={"action":op.get("type","add"),"target":op.get("object","未知"),"parameters":{"relation":op.get("relation","near"),"relation_target":op.get("target",""),"zone":op.get("zone","general")}}
            r=self.coordinator.handle(user_text=f"{op.get('type','add')} {op.get('object','')}",scene_state=scene_state,style_bible=style_bible)
            results.append({"operation":op,"result":r})
        return {"task_id":task.get("id",""),"results":results,"all_success":all(r["result"].get("status")in("executed","planned_only") for r in results)}

    def run_plan(self, scene_state=None, style_bible=None) -> Dict:
        if not self._current_plan: return {"status":"no_plan","completed":0,"total":0}
        tasks=self._current_plan.get("tasks",[]); completed=[]
        for i,task in enumerate(tasks):
            r=self.execute_step(task,scene_state,style_bible); completed.append(r)
            if self._on_confirm and not self._on_confirm({"task":task,"result":r,"progress":f"{i+1}/{len(tasks)}"}): break
        self._completed_tasks=completed; self._task_index=len(completed)
        return {"status":"complete","completed":len(completed),"total":len(tasks),"results":completed}

    @property
    def progress(self) -> Dict:
        if not self._current_plan: return {"completed":0,"total":0,"percentage":0}
        total=len(self._current_plan.get("tasks",[])); return {"completed":self._task_index,"total":total,"percentage":round(self._task_index/total*100) if total else 0}

    def get_plan_summary(self) -> str:
        if not self._current_plan: return "无计划"
        tasks=self._current_plan.get("tasks",[]); lines=[f"计划: {self._current_plan.get('analysis','')}"]
        for t in tasks:
            s="✅" if t["id"] in {r["task_id"] for r in self._completed_tasks} else "⏳"
            lines.append(f"  {s} {t['priority']}. {t['description']}")
        return "\n".join(lines)

    def reset(self): self._current_plan=None; self._completed_tasks=[]; self._task_index=0

    def _summarize_scene(self, scene_state=None) -> str:
        if not scene_state: return "场景为空"
        locked=scene_state.get("intermediate",{}).get("locked_actors",scene_state.get("intermediate",{}).get("scene_actors",[]))
        return f"已有({len(locked)}): {', '.join(a.get('name',a.get('actor_name','?')) for a in locked[:20])}" if locked else "场景为空"

__all__ = ["MultiStepPlanner"]
