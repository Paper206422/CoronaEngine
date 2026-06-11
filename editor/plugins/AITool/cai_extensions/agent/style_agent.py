"""风格校验 Agent"""
from __future__ import annotations
import json, logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Any, Dict, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

_STYLE_CONFLICT_PATTERNS = {
    "cyberpunk": {"forbidden": ["田园","乡村","复古木","碎花","蕾丝","pastoral","rustic"],"suspicious":["暖色调","木质","布艺","棉麻"]},
    "minimalist": {"forbidden": ["繁复","雕刻","镀金","花纹","ornate","baroque"],"suspicious":["复杂的","多重","层次丰富的"]},
    "industrial": {"forbidden": ["精致","细腻","柔美","花卉","delicate","floral"],"suspicious":["抛光","光滑","柔和的"]},
}

class StyleAgent:
    def __init__(self, timeout: float = 10.0): self.timeout = timeout

    def precheck(self, intent: Dict[str, Any], style_bible: Dict[str, Any] = None, user_is_explicit: bool = False) -> Dict[str, Any]:
        sb = style_bible or {}
        if not sb: return {"feasible": True, "user_override": False, "style_score": 100, "issues": [], "suggestions": []}
        params = intent.get("parameters", {})
        if params.get("style_deviation") or user_is_explicit:
            return {"feasible": True, "user_override": True, "style_score": 100, "issues": [f"用户主动突破: {params.get('deviation_reason','')}"], "suggestions": []}
        kw = self._keyword_check(intent, sb)
        if kw["issues"]: return kw
        try: return self._llm_precheck(intent, sb)
        except Exception as e: logger.warning("[StyleAgent] LLM failed: %s", e); return {"feasible": True, "user_override": False, "style_score": 80, "issues": [], "suggestions": []}

    def _keyword_check(self, intent, style_bible) -> Dict[str, Any]:
        theme = (style_bible.get("theme","") or "").lower(); target = (intent.get("target","") or "").lower()
        issues=[]; suggestions=[]; score=100
        for known, patterns in _STYLE_CONFLICT_PATTERNS.items():
            if known in theme:
                for f in patterns["forbidden"]:
                    if f in target: issues.append(f"'{intent['target']}'与风格'{known}'冲突(关键词:'{f}')"); score-=30; suggestions.append(f"避免'{f}'元素")
                for s in patterns["suspicious"]:
                    if s in target: score-=10; suggestions.append(f"'{s}'在'{known}'中需谨慎")
        for avoid_kw in style_bible.get("avoid", []):
            if avoid_kw.lower() in target: issues.append(f"含禁止元素:'{avoid_kw}'"); score-=40
        return {"feasible": True, "user_override": False, "style_score": max(0,score), "issues": issues, "suggestions": suggestions, "method": "keyword"}

    def generate_style_prompt_override(self, intent, style_bible) -> str:
        target = intent.get("target",""); sb = style_bible or {}
        if not sb or not target: return target
        parts = [target]
        if sb.get("theme"): parts.insert(0, sb["theme"])
        if sb.get("materials"): parts.append(f"made of {', '.join(sb['materials'][:2])}")
        if sb.get("mood"): parts.append(sb["mood"])
        return ", ".join(parts)

    def _llm_precheck(self, intent, style_bible) -> Dict[str, Any]:
        from Quasar.ai_models.base_pool.registry import get_chat_model
        prompt = f"""Style Bible:{json.dumps(style_bible,ensure_ascii=False)}\n动作:{intent.get('action')} 目标:{intent.get('target')} 参数:{json.dumps(intent.get('parameters',{}),ensure_ascii=False)}\n判断是否符合风格。输出JSON: {{"feasible":true,"user_override":false,"style_score":85,"issues":[],"suggestions":[]}}"""
        def _do(): return get_chat_model(temperature=0,request_timeout=15.0).invoke([SystemMessage(content="只输出JSON。"),HumanMessage(content=prompt)])
        executor=ThreadPoolExecutor(max_workers=1); future=executor.submit(_do)
        try: response=future.result(timeout=self.timeout)
        except FuturesTimeoutError: executor.shutdown(wait=False,cancel_futures=True); raise RuntimeError("timeout")
        else: executor.shutdown(wait=False)
        text=(response.content if hasattr(response,"content") else str(response)).strip()
        if "```" in text: s=text.find("{"); e=text.rfind("}"); text=text[s:e+1] if s!=-1 else text
        return json.loads(text)

__all__ = ["StyleAgent"]
