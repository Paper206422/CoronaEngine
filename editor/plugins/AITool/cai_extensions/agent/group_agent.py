"""群 Agent — 讨论总结 + 风格守护"""
from __future__ import annotations
import json, logging, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Dict, List, Optional, Tuple
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)
_DISCUSSION_TIMEOUT_SEC = 180; _MIN_PARTICIPANTS = 2; _CONSENSUS_THRESHOLD = 0.6; _PATROL_OP_COUNT = 10; _PATROL_DEVIATION_COUNT = 3

DISCUSSION_SUMMARY_PROMPT = """你是群助手，总结多人讨论的场景共识。输出JSON:{"consensus_analysis":{"theme_agreement":0-1,"type_agreement":0-1,"core_elements":[]},"proposed_plan":{"scene_name":"","scene_type":"indoor","style_bible":{"theme":"","color_palette":[],"materials":[],"lighting":"","mood":"","avoid":[]},"initial_zones":[]},"uncertainties":[],"confidence":0-1}"""
STYLE_PATROL_PROMPT = """你是风格守护者。检查场景一致性。输出JSON:{"overall_consistency":0-100,"violations":[{"object_id":"","consistency_score":85,"description":"","suggestions":[]}],"style_drift_warning":false,"recommendations":[]}"""

class GroupAgent:
    def __init__(self, ai_chat: Callable[[str, List[str]], str] = None, discussion_timeout: float = _DISCUSSION_TIMEOUT_SEC, patrol_op_count: int = _PATROL_OP_COUNT):
        self._ai_chat = ai_chat; self._discussion_timeout = discussion_timeout; self._patrol_op_count = patrol_op_count
        self._chat_messages: List[Dict[str, Any]] = []; self._user_intents: Dict[str, Dict[str, Any]] = {}
        self._discussion_start_time: Optional[float] = None; self._last_summary: Optional[Dict[str, Any]] = None
        self._operation_count = 0; self._deviation_count = 0; self._operation_log: List[Dict[str, Any]] = []

    def on_chat_message(self, user_id: str, text: str):
        if self._discussion_start_time is None: self._discussion_start_time = time.time()
        self._chat_messages.append({"from": user_id, "text": text, "ts": int(time.time())})
        intent = self._extract_user_intent(text)
        if intent: self._user_intents[user_id] = intent

    def should_summarize(self) -> bool:
        if len(self._user_intents) >= _MIN_PARTICIPANTS: return True
        if self._calc_consensus() >= _CONSENSUS_THRESHOLD and len(self._user_intents) >= 2: return True
        if self._discussion_start_time and time.time() - self._discussion_start_time > self._discussion_timeout: return True
        return False

    def try_summarize(self) -> Optional[Dict[str, Any]]:
        if not self.should_summarize(): return None
        if not self._ai_chat: return None
        result = self._generate_summary()
        if result: self._last_summary = result; self._discussion_start_time = None
        return result

    def on_operation_event(self, op: Dict[str, Any]):
        self._operation_count += 1; self._operation_log.append(op)
        if op.get("metadata", {}).get("style_deviation") or op.get("data", {}).get("style_deviation"): self._deviation_count += 1

    def should_patrol(self, user_requested: bool = False) -> bool:
        if user_requested: return True
        if self._operation_count >= self._patrol_op_count: return True
        if self._deviation_count >= _PATROL_DEVIATION_COUNT: return True
        return False

    def try_patrol(self, style_bible=None, objects=None, user_requested=False) -> Optional[Dict[str, Any]]:
        if not self.should_patrol(user_requested): return None
        if not self._ai_chat: return None
        sb = style_bible or (self._last_summary.get("proposed_plan", {}).get("style_bible") if self._last_summary else {})
        try: return self._run_patrol(sb, objects or [])
        except Exception: return None

    @property
    def consensus_score(self) -> float: return self._calc_consensus()
    @property
    def deviation_rate(self) -> float: return self._deviation_count / self._operation_count if self._operation_count else 0.0
    def get_last_summary(self) -> Optional[Dict[str, Any]]: return self._last_summary

    def reset_for_new_scene(self):
        self._chat_messages.clear(); self._user_intents.clear(); self._discussion_start_time = None
        self._last_summary = None; self._operation_count = 0; self._deviation_count = 0; self._operation_log.clear()
    clear = reset_for_new_scene  # 别名

    def _extract_user_intent(self, text: str) -> Optional[Dict[str, Any]]:
        style_keywords = {"theme": ["赛博朋克","cyberpunk","工业风","极简","北欧","中式","日式","田园","现代","复古","哥特","酒吧","bar","暗黑"],"mood":["暗黑","暗色调","明亮","温暖","冷酷","柔和的","硬朗","冷色调"],"lighting":["霓虹灯","霓虹","暖光","冷光","自然光","昏暗"]}
        result = {}; text_lower = text.lower()
        for category, keywords in style_keywords.items():
            for kw in keywords:
                if kw.lower() in text_lower: result[category] = kw; break
        return result if result else None

    def _calc_consensus(self) -> float:
        if len(self._user_intents) < 2: return 0.0
        users_with_intent = sum(1 for i in self._user_intents.values() if i)
        if users_with_intent < 2: return 0.0
        base = users_with_intent / len(self._user_intents)
        bonus = 0.0
        for category in ("theme","mood","lighting"):
            values = [i.get(category,"").lower() for i in self._user_intents.values() if i.get(category)]
            if len(values) >= 2:
                pair_score=0; total_pairs=0
                for i in range(len(values)):
                    for j in range(i+1,len(values)):
                        total_pairs+=1
                        if _text_overlap(values[i],values[j])>0.3: pair_score+=1
                if total_pairs>0: bonus+=(pair_score/total_pairs)*0.15
        return min(1.0, base+bonus)

    def _generate_summary(self) -> Optional[Dict[str, Any]]:
        history = "\n".join(f"{m['from']}: {m['text']}" for m in self._chat_messages[-50:])
        try:
            msg = self._ai_chat(DISCUSSION_SUMMARY_PROMPT, [history])
            if msg: return self._parse_json(msg)
        except Exception as e: logger.warning("[GroupAgent] summary failed: %s", e)
        return None

    def _run_patrol(self, style_bible, objects) -> Optional[Dict[str, Any]]:
        objects_text = "\n".join(f"  - {o.get('name',o.get('object_id','?'))}" for o in (objects or [])[:100]) if objects else "无"
        recent_ops = "\n".join(f"  - {o.get('data',{}).get('action','?')}: {o.get('data',{}).get('target','?')}" for o in self._operation_log[-20:])
        prompt = STYLE_PATROL_PROMPT.replace("{style_bible}", json.dumps(style_bible, ensure_ascii=False, indent=2)).replace("{objects_text}", objects_text).replace("{recent_ops}", recent_ops)
        try:
            msg = self._ai_chat("只输出JSON。", [prompt])
            if msg: return self._parse_json(msg)
        except: return None

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        text = text.strip()
        if "```" in text: s=text.find("{"); e=text.rfind("}"); text=text[s:e+1] if s!=-1 else text
        try: return json.loads(text)
        except: return None

def _text_overlap(a: str, b: str) -> float:
    if not a or not b: return 0.0
    def _bigrams(s): s=s.lower().replace(" ",""); return {s} if len(s)<=1 else {s[i:i+2] for i in range(len(s)-1)}
    sa = _bigrams(a); sb = _bigrams(b)
    if not sa or not sb: return 0.0
    return len(sa & sb) / len(sa | sb)

__all__ = ["GroupAgent"]
