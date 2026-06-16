"""Role 模板注册表（突击方案 §2.4 / ⟦DECIDE:role-depth⟧=只影响说话风格+轻偏好）。

定位：给多 agent 注入"角色人格"——影响**说话风格**（长者稳重 / 小女孩天真 / 山贼粗野），
外加一句**轻量场景倾向**（不接进 decompose，避免与 M2 去特殊化缠死）。

设计（照搬 services/ai_hint_service.py 的 persona-as-system-prompt 范式）：
- 内置 N 个模板，每个 = {key, name, persona(说话风格), scene_hint(轻偏好)}。
- 用户自定义入口：传 persona 文本 → 存成模板（register_custom）。
- persona 文本最终拼进 chat 的 SystemMessage（见 agent_adapter._build_chat_system）。

边界（铁律）：
- 只影响 voice + 一句 scene_hint，**绝不**进 decompose / capability 层。
- LANChat 的 Agent.persona 是自由文本——本注册表把"模板名/自定义文本"统一成 persona 串，
  既能被 _router.route 关键词匹配（路由），又能注入 chat（说话风格）。
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RoleTemplate:
    """一个角色模板。

    persona: 注入 chat SystemMessage 的说话风格描述（第一人称人设）。
    scene_hint: 轻量场景倾向（一句话，可空）——不进 decompose，仅作 chat 时的软提示。
    builtin: 是否内置（用户自定义为 False）。
    """
    key: str
    name: str
    persona: str
    scene_hint: str = ""
    builtin: bool = True

    def inject(self, base_system: str) -> str:
        """把角色人格拼进基础 system prompt。"""
        parts = [base_system.rstrip()]
        parts.append(f"\n\n【你的角色】{self.name}")
        if self.persona:
            parts.append(f"\n【说话风格】{self.persona}")
        if self.scene_hint:
            parts.append(f"\n【场景倾向】{self.scene_hint}（仅作风格参考，不强制）")
        parts.append("\n始终以该角色的口吻回复，保持人设一致。")
        return "".join(parts)


# ── 内置模板（N 个，demo 可选）────────────────────────────────

_BUILTIN: Dict[str, RoleTemplate] = {
    t.key: t for t in [
        RoleTemplate(
            key="elder", name="长者",
            persona="沉稳、睿智、慢条斯理，常引经据典，用词文雅，喜欢用比喻讲道理，"
                    "语气温和而有威严，偶尔感慨世事。",
            scene_hint="偏好庄重、对称、有历史感的布置",
        ),
        RoleTemplate(
            key="little_girl", name="小女孩",
            persona="天真烂漫、活泼好奇，爱用感叹号和叠词，常问'为什么呀'，"
                    "情绪外放，看到喜欢的东西会很兴奋。",
            scene_hint="偏好明亮、可爱、色彩丰富的布置",
        ),
        RoleTemplate(
            key="bandit", name="山贼",
            persona="粗犷豪迈、口无遮拦，自称'老子'，说话带江湖气，喜欢拍胸脯打包票，"
                    "嫌弃斯文，讲究实用和气派。",
            scene_hint="偏好粗犷、实用、有营寨/篝火气息的布置",
        ),
        RoleTemplate(
            key="scholar", name="学者",
            persona="严谨、条理分明，喜欢分点阐述，用词精确，常补充背景知识，"
                    "克制而专业，不轻易下结论。",
            scene_hint="偏好整洁、功能分区清晰、有书卷气的布置",
        ),
        RoleTemplate(
            key="merchant", name="商人",
            persona="精明热情、能说会道，满嘴生意经，爱算性价比，常用'划算''包您满意'，"
                    "察言观色，善于推销。",
            scene_hint="偏好琳琅满目、有陈列感、热闹的布置",
        ),
    ]
}

# 退化默认（无 role / 空 persona 时）：通用助手，不注入人格。
DEFAULT_KEY = "generalist"


class RoleRegistry:
    """Role 模板注册表（进程级单例 + 用户自定义）。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._custom: Dict[str, RoleTemplate] = {}

    # ── 查询 ─────────────────────────────────────────────
    def list_templates(self) -> List[Dict[str, str]]:
        """列出所有可选模板（内置 + 自定义），供前端做选项。"""
        with self._lock:
            out = [{"key": t.key, "name": t.name, "builtin": "true",
                    "scene_hint": t.scene_hint} for t in _BUILTIN.values()]
            out += [{"key": t.key, "name": t.name, "builtin": "false",
                     "scene_hint": t.scene_hint} for t in self._custom.values()]
            return out

    def get(self, key: str) -> Optional[RoleTemplate]:
        with self._lock:
            return _BUILTIN.get(key) or self._custom.get(key)

    # ── 自定义 ───────────────────────────────────────────
    def register_custom(self, key: str, name: str, persona: str,
                        scene_hint: str = "") -> RoleTemplate:
        """注册用户自定义模板（key 冲突内置则加后缀，绝不覆盖内置）。"""
        with self._lock:
            safe = (key or name or "custom").strip() or "custom"
            if safe in _BUILTIN:
                safe = f"{safe}_custom"
            tpl = RoleTemplate(key=safe, name=name or safe, persona=persona or "",
                               scene_hint=scene_hint, builtin=False)
            self._custom[safe] = tpl
            logger.info("[RoleRegistry] 注册自定义角色: %s (%s)", tpl.name, safe)
            return tpl

    # ── 核心：把 persona 串解析成可注入的 RoleTemplate ────────
    def resolve(self, persona: str) -> Optional[RoleTemplate]:
        """把 LANChat 传来的 persona 串解析成模板。

        匹配优先级：① 精确 key/name ② 自定义 ③ persona 文本含某模板名（关键词）。
        都不中 → None（调用方退化为通用助手，不注入人格）。
        """
        p = (persona or "").strip()
        if not p or p == "你是一个有帮助的助手。":
            return None
        with self._lock:
            # ① 精确 key
            tpl = _BUILTIN.get(p) or self._custom.get(p)
            if tpl:
                return tpl
            # ② 按 name 精确
            for t in list(_BUILTIN.values()) + list(self._custom.values()):
                if t.name == p:
                    return t
            # ③ persona 文本里包含某模板名（如 "你是一位睿智的长者"）
            for t in list(_BUILTIN.values()) + list(self._custom.values()):
                if t.name and t.name in p:
                    return t
        # ④ 未命中模板：把整段 persona 当成"临时自定义人格"直接用（不落库）
        return RoleTemplate(key="adhoc", name="自定义", persona=p, builtin=False)


_default_registry: Optional[RoleRegistry] = None


def get_role_registry() -> RoleRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = RoleRegistry()
    return _default_registry


def inject_persona_voice(base_system: str, persona: str) -> str:
    """便捷入口：把 persona 串解析成角色并注入 base_system。

    未命中任何角色 → 原样返回 base_system（通用助手，不注入人格）。
    agent_adapter._build_chat_system 调这个把 role 接进 chat 说话风格。
    """
    tpl = get_role_registry().resolve(persona)
    if tpl is None:
        return base_system
    return tpl.inject(base_system)


__all__ = [
    "RoleTemplate", "RoleRegistry", "get_role_registry",
    "inject_persona_voice", "DEFAULT_KEY",
]
