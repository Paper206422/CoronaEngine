"""意图理解 Agent"""
from __future__ import annotations
import json, logging, re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

INTENT_SYSTEM_PROMPT = """你是场景编辑助手。分析用户输入，输出结构化 JSON。
动作类型: add/delete/move/modify/question
判别规则:
- move: 改变物体位置(平移/挪动/推拉)，关键词: 移、挪、搬、推、拉、往左、往右
- modify: 改变物体大小/比例/角度，关键词: 放大、缩小、变大、变小、旋转、改成、修改、调整
- **重点**: "缩小一倍""放大两倍""变大"等尺寸变化一律是 modify，不是 move
输出: {"action":"add","target":"物体名","confidence":0.87,"parameters":{"zone":"bar_area","partition":"indoor","relation":"near","relation_target":"参照物","distance_guide":0.5,"quantity":1,"style_deviation":false,"deviation_reason":null},"reasoning":[],"ambiguities":[]}
只输出 JSON。"""

_ACTION_KEYWORDS = {"add":["加个","添加","放个","增加","创建","添加一个","加一个","放一个","新增"],"delete":["删掉","删除","移除","去掉","清除","干掉"],"modify":["放大","缩小","变大","变小","旋转","改成","修改","调整"],"move":["移","挪","移动","搬","推到","拉到","往左","往右","往前","往后"]}
_ZONE_KEYWORDS = {"bar_area":["吧台","酒吧","调酒","酒柜","高脚凳"],"seating_area":["沙发","座位","休息","茶几","椅子","凳子"],"entrance":["门口","入口","大门"],"service":["厨房","吧台","后厨"]}
_RELATION_KEYWORDS = {"near":["旁边","附近","靠着","挨着","边上","侧"],"on":["上面","顶上","上方"],"under":["下面","底下","下方"],"in_front":["前面","前方","对面"],"against_wall":["墙边","靠墙","贴墙"],"between":["之间","中间"],"left":["左边","左侧","往左","左面"],"right":["右边","右侧","往右","右面"]}

def _keyword_fallback(user_text: str) -> Dict[str, Any]:
    text = user_text.strip()
    action = "add"
    for act, kws in _ACTION_KEYWORDS.items():
        if any(kw in text for kw in kws): action = act; break
    zone = "general"
    for z, kws in _ZONE_KEYWORDS.items():
        if any(kw in text for kw in kws): zone = z; break
    relation = "near"
    for rel, kws in _RELATION_KEYWORDS.items():
        if any(re.search(kw, text) for kw in kws): relation = rel; break
    target = ""
    for pat in [r'加个(.+?)(?:[，。,.]|$)', r'添加(.+?)(?:[，。,.]|$)',
                r'把(.+?)(?:移|删|放大|缩小|旋转|调整|修改)',
                r'(?:对|给)(?:这个|那个)?(.+?)(?:缩小|放大|旋转|调整|修改|移动|删除)',
                r'(?:放大|缩小|旋转|删除|移除|移动)(.+?)(?:[，。,.]|$)']:  # 动词开头
        m = re.search(pat, text)
        if m:
            target = m.group(1).strip()
            if target:
                break
    if not target: target = text[:30]
    relation_target = ""; m2 = re.search(r'(?:旁边|附近|靠着|挨着|前面|后面|上面)(.+)', text) or re.search(r'在(.+?)的?', text)
    if m2: relation_target = m2.group(1).strip()[:20]
    logger.info("[IntentAgent] keyword fallback: action=%s target=%s relation=%s", action, target, relation)
    return {"action": action, "target": target or "未知物体", "confidence": 0.4, "parameters": {"zone": zone, "partition": "indoor", "relation": relation, "relation_target": relation_target, "distance_guide": 0.5, "quantity": 1, "style_deviation": False, "deviation_reason": None}, "reasoning": ["关键词回退"], "ambiguities": ["低置信度"], "_fallback": True}

class IntentAgent:
    def __init__(self, timeout: float = 15.0): self.timeout = timeout

    def analyze(self, user_text: str, scene_state: Dict[str, Any] = None, style_bible: Dict[str, Any] = None, conversation_history: str = "") -> Dict[str, Any]:
        if not user_text or not user_text.strip(): return self._empty_intent()
        try: return self._llm_analyze(user_text, scene_state, style_bible, conversation_history)
        except Exception as e: logger.warning("[IntentAgent] LLM failed: %s", e)
        return _keyword_fallback(user_text)

    def _llm_analyze(self, user_text: str, scene_state=None, style_bible=None, conversation_history="") -> Dict[str, Any]:
        scene = scene_state or {}; metadata = scene.get("metadata", {}); intermediate = scene.get("intermediate", {})
        room_size = metadata.get("room_size", [5, 3, 3]); scene_name = intermediate.get("scene_name", metadata.get("scene_name", "未命名"))
        locked_actors = intermediate.get("locked_actors", intermediate.get("scene_actors", []))
        objects_text = "\n".join(f"  - {a.get('name', a.get('actor_name', a.get('object_id', '?')))}: pos={a.get('position', a.get('pos', [0,0,0]))}" for a in locked_actors) if locked_actors else "  场景为空"
        zones = intermediate.get("zones", metadata.get("zones", []))
        zones_text = "\n".join(f"  - {z.get('zone_id', z)}: {z.get('function','')}" for z in zones) if zones else "无分区"
        sb = style_bible or {}; style_parts = []
        if sb.get("theme"): style_parts.append(f"主题:{sb['theme']}")
        if sb.get("materials"): style_parts.append(f"材质:{','.join(sb['materials'])}")
        style_text = "\n".join(style_parts) if style_parts else "无全局风格约束"
        prompt = f"""## 当前场景\n名称:{scene_name}\n房间:{room_size[0]}×{room_size[1]}×{room_size[2] if len(room_size)>2 else 3}m\n已有物体:\n{objects_text}\n分区:\n{zones_text}\n## Style Bible\n{style_text}\n## 对话历史\n{conversation_history or '无'}\n## 用户输入\n"{user_text}"\n请输出 JSON。"""
        response_text = self._call_llm(INTENT_SYSTEM_PROMPT, prompt)
        if not response_text: raise RuntimeError("LLM empty")
        return self._parse_response(response_text, user_text)

    def _call_llm(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        from Quasar.ai_models.base_pool.registry import get_chat_model
        def _do(): return get_chat_model(temperature=0, request_timeout=30.0).invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        executor = ThreadPoolExecutor(max_workers=1); future = executor.submit(_do)
        try: response = future.result(timeout=self.timeout)
        except FuturesTimeoutError: executor.shutdown(wait=False, cancel_futures=True); return None
        except Exception as e: executor.shutdown(wait=False); logger.warning("[IntentAgent] LLM error: %s", e); return None
        else: executor.shutdown(wait=False)
        return (response.content if hasattr(response, "content") else str(response)).strip()

    def _parse_response(self, text: str, original_input: str) -> Dict[str, Any]:
        text = text.strip()
        if "```" in text:
            s = text.find("{"); e = text.rfind("}")
            if s != -1 and e != -1: text = text[s:e+1]
        try: result = json.loads(text)
        except json.JSONDecodeError: return _keyword_fallback(original_input)
        if not isinstance(result, dict): return _keyword_fallback(original_input)
        return {"action": str(result.get("action") or "add").strip().lower(), "target": str(result.get("target") or "").strip(), "confidence": float(result.get("confidence") or 0.7),
                "parameters": {"zone": str(result.get("parameters", {}).get("zone") or "general"), "partition": str(result.get("parameters", {}).get("partition") or "indoor"), "relation": str(result.get("parameters", {}).get("relation") or "near").lower(), "relation_target": str(result.get("parameters", {}).get("relation_target") or ""), "distance_guide": float(result.get("parameters", {}).get("distance_guide") or 0.5), "quantity": int(result.get("parameters", {}).get("quantity") or 1), "style_deviation": bool(result.get("parameters", {}).get("style_deviation", False)), "deviation_reason": result.get("parameters", {}).get("deviation_reason")},
                "reasoning": result.get("reasoning", []), "ambiguities": result.get("ambiguities", [])}

    def _empty_intent(self) -> Dict[str, Any]:
        return {"action": "question", "target": "", "confidence": 0.0, "parameters": {"zone": "general", "partition": "indoor", "relation": "near", "relation_target": "", "distance_guide": 0.5, "quantity": 0, "style_deviation": False, "deviation_reason": None}, "reasoning": ["空"], "ambiguities": ["无输入"]}

__all__ = ["IntentAgent"]
