"""Agent Coordinator — 编排 + SelfReflection + Disambiguation"""
from __future__ import annotations
import json, logging, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

SELF_REFLECTION_PROMPT = """你是质量检查员。评估操作质量。5维度(0-100):intent_match,physical,harmony,style,ux。输出:{"scores":{},"overall_confidence":83,"issues":[],"suggestions":[],"decision":"execute"}。>90→execute,60-90→execute_with_warning,<60→ask_user。只输出JSON。"""

class AgentCoordinator:
    def __init__(self, timeout: float = 30.0): self.timeout = timeout; self._intent_agent = None; self._spatial_agent = None; self._style_agent = None

    @property
    def intent_agent(self):
        if self._intent_agent is None:
            from .intent_agent import IntentAgent; self._intent_agent = IntentAgent()
        return self._intent_agent
    @property
    def spatial_agent(self):
        if self._spatial_agent is None:
            from .spatial_agent import SpatialAgent; self._spatial_agent = SpatialAgent()
        return self._spatial_agent
    @property
    def style_agent(self):
        if self._style_agent is None:
            from .style_agent import StyleAgent; self._style_agent = StyleAgent()
        return self._style_agent

    def validate(self, intent: Dict[str, Any], spatial: Dict[str, Any], scene_state: Dict[str, Any] = None) -> Dict[str, Any]:
        scene = scene_state or {}; intermediate = scene.get("intermediate", {}); metadata = scene.get("metadata", {})
        style_bible = intermediate.get("style_bible", metadata.get("style_bible", {}))
        reflection = self._self_reflection(intent, spatial, scene_state, style_bible)
        confidence = reflection.get("overall_confidence", 50); decision = self._decide(confidence, reflection)
        return {"passed": decision != "ask_user", "decision": decision, "confidence": confidence, "reflection": reflection}

    def execute(self, intent, spatial, validation, scene_state=None) -> Dict[str, Any]:
        decision = validation.get("decision", "execute"); action = intent.get("action", "")
        if decision == "ask_user": return {"status": "pending_user_approval", "message": self._format_ask_user(intent, validation), "action": action}
        result = {"status": "executed", "action": action, "steps": []}
        try:
            if action == "add": result.update(self._execute_add(intent, spatial, scene_state))
            elif action == "delete": result.update(self._execute_delete(intent, scene_state))
            elif action == "move": result.update(self._execute_move(intent, spatial, scene_state))
            elif action == "modify": result.update(self._execute_modify(intent, spatial, scene_state))
            else: result.update({"status": "unknown"})
        except Exception as e: logger.error("[Coordinator] execute failed: %s", e); result["status"] = "error"; result["error"] = str(e)
        self._broadcast(intent, spatial, result); self._record(intent, spatial, result, scene_state)
        return result

    def handle(self, user_text: str, scene_state=None, style_bible=None) -> Dict[str, Any]:
        start = time.time(); scene = scene_state or {}
        memory = self._memory_for_scene(scene)

        # 对话历史（渐进式交互：让 LLM 知道之前说了什么、做了什么）
        conv_hist = ""
        try:
            conv_hist = memory.session.get_recent_conversation(5)
        except Exception:
            pass

        intent = self.intent_agent.analyze(user_text, scene_state=scene, style_bible=style_bible,
                                           conversation_history=conv_hist)

        # ── 记忆增强：回忆相似历史操作，注入推断 ──
        memory_hint = self._recall_similar(intent, scene_state=scene)

        style_check = self.style_agent.precheck(intent, style_bible)
        spatial = self.spatial_agent.solve(intent, scene_state=scene)
        validation = self.validate(intent, spatial, scene_state=scene)

        # ── 歧义处理：低/中置信度时生成候选选项 ──
        confidence = validation.get("confidence", 100) / 100.0
        disambiguation = self.resolve_ambiguity(intent, spatial, confidence=confidence)

        result = self.execute(intent, spatial, validation, scene_state=scene)

        # 把歧义候选/记忆提示挂到 ask_user 结果上，供上层展示
        if result.get("status") == "pending_user_approval":
            if disambiguation.get("choices"):
                result["choices"] = disambiguation["choices"]
            if disambiguation.get("message"):
                result["message"] = disambiguation["message"]
        if memory_hint:
            result["memory_hint"] = memory_hint

        return {"status": result.get("status", "unknown"), "intent": intent,
                "spatial": spatial, "validation": validation, "result": result,
                "disambiguation": disambiguation, "memory_hint": memory_hint,
                "elapsed_seconds": round(time.time() - start, 2)}

    def _memory_for_scene(self, scene_state: Dict[str, Any] | None = None):
        scene = scene_state or {}
        metadata = scene.get("metadata", {}) if isinstance(scene, dict) else {}
        scope = {}
        for key in ("lanchat_memory_scope", "memory_scope"):
            value = scene.get(key) if isinstance(scene, dict) else None
            if not isinstance(value, dict):
                value = metadata.get(key) if isinstance(metadata, dict) else None
            if isinstance(value, dict):
                scope.update(value)

        def _scope_value(*keys: str) -> str:
            for source in (metadata, scene, scope):
                if not isinstance(source, dict):
                    continue
                for key in keys:
                    value = source.get(key)
                    if value not in (None, ""):
                        return str(value).strip()
            return ""

        room_id = _scope_value("room_id", "lanchat_room_id")
        plan_id = _scope_value("plan_id", "seed_plan_id")
        batch_id = _scope_value("batch_id")
        agent_id = _scope_value("agent_id", "agent_name")
        scene_id = _scope_value("scene_id", "scene_name") or "default"
        if room_id or plan_id or batch_id or agent_id:
            from .memory import get_scoped_memory_manager
            return get_scoped_memory_manager(
                scene_id=scene_id,
                room_id=room_id,
                plan_id=plan_id,
                batch_id=batch_id,
                agent_id=agent_id,
            )
        from .memory import get_memory_manager
        return get_memory_manager(scene_id)

    def _recall_similar(self, intent: Dict[str, Any], scene_state: Dict[str, Any] | None = None) -> str:
        """回忆相似历史操作，返回可附加到回复的记忆提示（无则空串）。"""
        try:
            action = intent.get("action", "")
            target = intent.get("target", "")
            if action != "add" or not target:
                return ""
            similar = self._memory_for_scene(scene_state).find_similar_operations(action, target)
            if len(similar) >= 2:
                logger.info("[Coordinator] 记忆增强: '%s' 近期已添加 %d 次", target, len(similar))
                return f"💭 你已连续添加了 {len(similar)} 个「{target}」类物体，需要我按相同方式继续布置吗？"
        except Exception as e:
            logger.warning("[Coordinator] _recall_similar failed: %s", e)
        return ""

    def resolve_ambiguity(self, intent, spatial=None, confidence=0.0) -> Dict[str, Any]:
        spatial = spatial or {}; ambiguities = intent.get("ambiguities", [])
        if not ambiguities and confidence > 0.5: return {"action": "execute", "message": "", "choices": []}
        choices = self._generate_choices(intent, spatial)
        if confidence >= 0.9: return {"action": "execute", "message": "", "choices": []}
        elif confidence >= 0.6: return {"action": "execute_with_warning", "message": self._build_ambiguity_msg(intent, ambiguities), "choices": choices}
        else: return {"action": "ask", "message": self._build_clarify(intent, spatial, ambiguities), "choices": choices}

    def _generate_choices(self, intent, spatial) -> List[Dict]:
        action = intent.get("action","add"); target = intent.get("target","物体"); params = intent.get("parameters",{})
        current_pos = spatial.get("position", [0,0,0])
        if action == "modify":
            s = spatial.get("scale", [1,1,1])
            return [{"label":f"+20%","scale":[v*1.2 for v in s]},{"label":f"+50%","scale":[v*1.5 for v in s]},{"label":"×2","scale":[v*2 for v in s]}]
        if action == "move":
            o=params.get("distance_guide",0.5)
            return [{"label":f"右{o}m","position":[current_pos[0]+o,current_pos[1],current_pos[2]]},{"label":f"左{o}m","position":[current_pos[0]-o,current_pos[1],current_pos[2]]},{"label":f"前{o}m","position":[current_pos[0],current_pos[1],current_pos[2]-o]}]
        if action == "add":
            choices=[{"label":"默认位置","relation":"near"}]
            if params.get("relation_target"): t=params["relation_target"]; choices+=[{"label":f"{t}左侧","relation":"left"},{"label":f"{t}右侧","relation":"right"}]
            return choices
        return [{"label":f"确认{target}","action":"confirm"},{"label":"取消","action":"cancel"}]

    def _build_ambiguity_msg(self, intent, ambiguities) -> str:
        return f"关于「{intent.get('target','物体')}」的操作有不确定性:\n"+"\n".join(f"  · {a}" for a in ambiguities[:3])+"\n将执行默认方案。"

    def _build_clarify(self, intent, spatial, ambiguities) -> str:
        target = intent.get("target","物体"); params = intent.get("parameters",{})
        lines = [f"关于「{target}」需要确认:"]
        if ambiguities:
            for a in ambiguities[:2]: lines.append(f"  ❓ {a}")
        if intent["action"]=="modify":
            s = spatial.get("scale", [1,1,1]); lines.append(f"\n  当前 scale={[round(v,2) for v in s]}, 建议: {[round(v*1.3,2) for v in s]}")
        elif intent["action"]=="add" and params.get("relation_target"):
            lines.append(f"\n  建议放在 {params['relation_target']} 旁边")
        lines.append("\n请选择或输入具体指令:")
        return "\n".join(lines)

    def _self_reflection(self, intent, spatial, scene_state=None, style_bible=None) -> Dict[str, Any]:
        rule = self._rule_reflection(intent, spatial, scene_state)
        if rule["min_score"] < 60:
            try:
                llm = self._llm_reflection(intent, spatial, scene_state, style_bible)
                if llm: return llm
            except: pass
        overall = sum(rule["scores"].values()) / len(rule["scores"])
        return {"scores": rule["scores"], "overall_confidence": round(max(0, min(100, overall))), "issues": rule["issues"], "suggestions": rule["suggestions"], "method": "rule"}

    def _rule_reflection(self, intent, spatial, scene_state=None) -> Dict[str, Any]:
        issues=[]; suggestions=[]; scores={"intent_match":85,"physical":95,"harmony":90,"style":85,"ux":85}
        if intent.get("confidence",1.0) < 0.5: scores["intent_match"]=40; issues.append("意图置信度低")
        elif intent.get("_fallback"): scores["intent_match"]=50; issues.append("关键词回退模式")
        pos = spatial.get("position")
        if pos:
            if len(pos)>1 and pos[1]>3.0: scores["physical"]=30; issues.append(f"Y={pos[1]:.1f}m异常高")
            scene=scene_state or {}; r=scene.get("metadata",{}).get("room_size",[5,3,3])
            xh,zh=r[0]/2,r[1]/2 if len(r)>1 else 2.5
            if abs(pos[0])>xh+0.5 or abs(pos[2])>zh+0.5: scores["physical"]=25; issues.append("超出房间边界")
        if intent.get("parameters",{}).get("style_deviation"): scores["style"]=70; issues.append("用户风格偏离")
        return {"scores":scores,"min_score":min(scores.values()),"issues":issues,"suggestions":suggestions}

    def _llm_reflection(self, intent, spatial, scene_state=None, style_bible=None) -> Optional[Dict]:
        from Quasar.ai_models.base_pool.registry import get_chat_model
        prompt = SELF_REFLECTION_PROMPT.replace("{operation}",json.dumps({"action":intent.get("action"),"target":intent.get("target"),"position":spatial.get("position"),"scale":spatial.get("scale")},ensure_ascii=False)).replace("{intent}",json.dumps(intent,ensure_ascii=False)).replace("{scene_summary}",self._summarize_scene(scene_state)).replace("{style_bible}",json.dumps(style_bible or {},ensure_ascii=False))
        def _do(): return get_chat_model(temperature=0,request_timeout=20.0).invoke([SystemMessage(content="只输出JSON。"),HumanMessage(content=prompt)])
        executor=ThreadPoolExecutor(max_workers=1); future=executor.submit(_do)
        try: response=future.result(timeout=self.timeout)
        except FuturesTimeoutError: executor.shutdown(wait=False,cancel_futures=True); return None
        else: executor.shutdown(wait=False)
        text=(response.content if hasattr(response,"content") else str(response)).strip()
        if "```" in text: s=text.find("{"); e=text.rfind("}"); text=text[s:e+1] if s!=-1 else text
        r=json.loads(text); r["method"]="llm"; return r

    def _decide(self, confidence, reflection) -> str:
        return "execute" if confidence>=90 else ("execute_with_warning" if confidence>=60 else "ask_user")

    def _execute_add(self, intent, spatial, scene_state=None) -> Dict:
        pos=spatial.get("position"); rot=spatial.get("rotation",[0,0,0]); scl=spatial.get("scale",[1,1,1]); target=intent.get("target","")
        if not pos: return {"status":"skipped","reason":"无法确定位置"}
        scene=scene_state or {}; sn=scene.get("intermediate",{}).get("scene_name","composed_scene")

        # ── 步骤 A: 获取 3D 模型文件 ──
        logger.info("[Coordinator][3D] === _execute_add START: target=%r pos=%s ===",
                    target, [round(v,2) for v in pos])
        model_path = self._acquire_model(target, intent, scene_state=scene)
        if not model_path:
            logger.warning("[Coordinator][3D] model acquire failed for %r, fallback to planned_only", target)
            return {"status":"planned_only","object_id":target,"position":pos,
                    "note":"3D模型获取失败（搜索未命中且生成不可用）"}

        # ── 步骤 B: 导入引擎 ──
        logger.info("[Coordinator][3D] importing model=%r engine_path=%r", target, model_path)
        try:
            from ..flows.scene_composition_workflow.helpers import get_tool
            tool = get_tool("import_model")
            if tool:
                tool.invoke({"model_name":target, "object_id":target,
                             "scene_name":sn, "position":pos,
                             "rotation":rot, "scale":scl,
                             "model_path":model_path})
                logger.info("[Coordinator][3D] === _execute_add DONE: target=%r → engine ===", target)
                return {"status":"executed","object_id":target,"position":pos,
                        "model_path":model_path, "note":"3D模型已导入引擎"}
        except Exception as e:
            logger.warning("[Coordinator] import_model failed: %s", e)

        return {"status":"planned_only","object_id":target,"position":pos,
                "model_path":model_path, "note":"模型已就绪，引擎导入失败"}

    def _acquire_model(self, target: str, intent: Dict[str, Any],
                       scene_state: Dict[str, Any] = None) -> str:
        """获取 3D 模型文件路径（搜索 → 生成 → 下载，或直接文件路径）。

        若 intent 中检测到显式的模型文件路径（.obj/.glb/.fbx等），
        直接返回该路径，跳过搜索和 3D 生成。

        Returns:
            本地 .glb/.fbx 路径，或空字符串表示获取失败。
        """
        import os as _os, re as _re

        # 检测显式文件路径（用户指定了具体模型文件）
        direct_path = (
            (scene_state or {}).get("intermediate", {}).get("direct_model_path", "")
            or intent.get("parameters", {}).get("model_path", "")
        )
        if not direct_path and target:
            # target 本身可能就是路径（如 "F:\path\to\model.obj"）
            m = _re.search(r"((?:[A-Za-z]:|/)[^\s]{2,}\.(?:obj|glb|gltf|fbx|dae|stl))",
                           target, _re.IGNORECASE)
            if m:
                direct_path = m.group(1)
        if direct_path:
            direct_path = direct_path.replace("/", _os.sep).replace("\\", _os.sep)
            if _os.path.isfile(direct_path):
                logger.info("[Coordinator][3D] _acquire_model: 使用指定文件路径 %s", direct_path)
                return direct_path
            else:
                logger.warning("[Coordinator][3D] 文件路径不存在: %s", direct_path)

        # 收集所有可能的参考图来源
        scene = scene_state or {}
        image_url = (
            scene.get("intermediate", {}).get("reference_image_url", "")
            or intent.get("parameters", {}).get("image_url", "")
        )

        logger.info("[Coordinator][3D] _acquire_model: target=%r image_url=%r...",
                    target, image_url[:60] if image_url else "(none)")

        try:
            from .model_provider import ModelProvider
            provider = ModelProvider()
            result = provider.acquire(
                name=target,
                image_url=image_url,
                prompt_text=f"high quality 3D model of {target}",
            )

            if result.success:
                logger.info("[Coordinator][3D] _acquire_model SUCCESS: source=%s path=%r",
                            result.source, result.local_path)
            else:
                logger.warning("[Coordinator][3D] _acquire_model FAILED: source=%s error=%s",
                               result.source, result.error)
            return result.local_path

        except Exception as e:
            logger.exception("[Coordinator][3D] _acquire_model exception: %s", e)
            return ""

    def _execute_delete(self, intent, scene_state=None) -> Dict:
        target=intent.get("target","")
        try:
            from ..flows.scene_composition_workflow.helpers import get_tool
            tool=get_tool("remove_model")
            if tool: tool.invoke({"actor_name":target}); return {"status":"executed","object_id":target,"removed":True}
        except: pass
        return {"status":"planned_only","object_id":target,"note":"remove不可用"}

    def _execute_move(self, intent, spatial, scene_state=None) -> Dict:
        target=intent.get("target",""); pos=spatial.get("position")
        if not pos: return {"status":"skipped"}
        try:
            from ..flows.scene_composition_workflow.helpers import get_tool
            tool=get_tool("set_actor_transform")
            if tool: tool.invoke({"actor_name":target,"position":pos}); return {"status":"executed","object_id":target,"new_position":pos}
        except: pass
        return {"status":"planned_only","object_id":target,"new_position":pos}

    def _execute_modify(self, intent, spatial, scene_state=None) -> Dict:
        target=intent.get("target",""); scl=spatial.get("scale")
        try:
            from ..flows.scene_composition_workflow.helpers import get_tool
            tool=get_tool("set_actor_transform")
            if tool and scl: tool.invoke({"actor_name":target,"scale":scl}); return {"status":"executed","object_id":target,"new_scale":scl}
        except: pass
        return {"status":"planned_only","object_id":target}

    def _broadcast(self, intent, spatial, result):
        try:
            from .event_bus import EventType, get_event_bus
            get_event_bus().publish({"event_type":EventType.OPERATION_COMPLETE if result.get("status")=="executed" else EventType.USER_INTENT,"user_id":intent.get("user_id","default"),"data":{"action":intent.get("action"),"target":intent.get("target"),"position":spatial.get("position"),"status":result.get("status")},"metadata":{"confidence":intent.get("confidence")}})
        except: pass

    def _record(self, intent, spatial, result, scene_state=None):
        try:
            m = self._memory_for_scene(scene_state)  # scoped when room/plan context exists
            m.record_operation({"action":intent.get("action"),"target":intent.get("target"),"position":spatial.get("position"),"status":result.get("status"),"confidence":intent.get("confidence")})
        except Exception as e:
            logger.warning("[Coordinator] _record failed: %s", e)

    def _summarize_scene(self, scene_state=None) -> str:
        if not scene_state: return "场景为空"
        locked=scene_state.get("intermediate",{}).get("locked_actors",scene_state.get("intermediate",{}).get("scene_actors",[]))
        return f"已有物体: {', '.join(a.get('name',a.get('actor_name','?')) for a in locked[:20])} (共{len(locked)}个)" if locked else "场景为空"

    def _format_ask_user(self, intent, validation) -> str:
        r=validation.get("reflection",{}); issues=r.get("issues",[]); suggestions=r.get("suggestions",[])
        return f"关于「{intent.get('target','')}」的疑虑:\n"+"\n".join(f"  ⚠️ {i}" for i in issues)+("\n建议:\n"+"\n".join(f"  💡 {s}" for s in suggestions) if suggestions else "")+"\n是否继续?"

__all__ = ["AgentCoordinator"]
