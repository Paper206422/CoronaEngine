"""Master Agent — 统一入口，接管 LANChat 全部 AI 能力。

替换 LANChat 原有的两处回调:
  1. AgentRunner 推理 → create_master_agent()     (system, messages) -> str
  2. SummaryService 摘要 → create_summary_agent()  (prompt) -> str

Master Agent 内部能力:
  - 场景编辑 (add/delete/move/modify) → AgentCoordinator
  - 普通聊天 → CAIApp + specialist 上下文
  - 讨论总结 → GroupAgent 共识 + Style Bible 生成
  - 风格巡检 → GroupAgent 定期检查
  - 能力查询 → /help 命令

架构:
  LANChat 群聊消息
    ├─ AgentRunner.run() → MasterAgent(system, messages)
    │   ├─ 场景指令 → Coordinator
    │   ├─ /总结 /summary → GroupAgent.try_summarize()
    │   ├─ /检查 /patrol → GroupAgent.try_patrol()
    │   └─ 其他 → CAIApp 聊天
    │
    └─ SummaryService.compress() → SummaryAgent(prompt)
        └─ 增强版摘要 (含场景上下文)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 场景指令检测
# ═══════════════════════════════════════════════════════════════════════════

_SCENE_COMMAND_PATTERNS = [
    r"(?:加个?|添加|放个?|增加|创建|新[增建]|导入).{1,20}",
    r"(?:删[掉除]|移除|去掉|清除).{0,20}$",
    r"(?:把|将).{1,20}(?:移[动到]?|挪[动到]?|搬[到]?|推到?|拉到?)",
    r"(?:往|向)(?:左|右|前|后|上|下)移",
    r"(?:放大|缩小|变大|变小|旋转|改成?|调整|修改).{1,20}",
    r"(?:布置|摆放|排列|安排|设计|规划|装饰).{1,30}",
    r"(?:灯光|光照|照明|氛围|环境光|光源).{1,20}",
    r"生成.{0,8}(?:3d|3D|模型|物体|场景|家具|清单)",
    r"(?:按|根据|依据).{0,10}清单",
    r"(?:组合|搭建).{0,8}(?:场景|房间|卧室|客厅|酒吧)",
    r"@agent\s", r"@场景\s", r"/sc_agent\s",
]

_NON_SCENE_PATTERNS = [
    r"^(?:你好|hello|hi|hey)\b", r"^(?:谢谢|thanks?|thank you)\b",
    r"^(?:什么|怎么|如何|为什么|什么时候)\b", r"^\?\s*$", r"^[。！？\.\!\?]$",
]

_BUILTIN_COMMANDS = [
    r"^/(?:help|能力|list)\b", r"^(?:帮助|你能做什么|有什么能力)\b",
    r"^/(?:总结|summary|summarize)\b", r"^(?:总结一下|来个总结|讨论总结)\b",
    r"^/(?:检查|巡检|patrol|check)\b", r"^(?:巡检一下|风格检查|检查风格)\b",
]


def is_scene_command(text: str) -> bool:
    text = text.strip()
    if not text or len(text) < 2:
        return False
    for pat in _NON_SCENE_PATTERNS:
        if re.match(pat, text):
            return False
    for pat in _SCENE_COMMAND_PATTERNS:
        if re.search(pat, text):
            return True
    return False


def is_builtin_command(text: str) -> Optional[str]:
    """检测内置命令。返回命令类型或 None。

    返回: "help" | "summary" | "patrol" | None
    """
    text = text.strip()
    if re.match(r"^/(?:help|能力|list)\b", text) or re.match(r"^(?:帮助|你能做什么|有什么能力)\b", text):
        return "help"
    if re.match(r"^/(?:总结|summary|summarize)\b", text) or re.match(r"^(?:总结一下|来个总结|讨论总结)\b", text):
        return "summary"
    if re.match(r"^/(?:检查|巡检|patrol|check)\b", text) or re.match(r"^(?:巡检一下|风格检查|检查风格)\b", text):
        return "patrol"
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Specialist 注册表
# ═══════════════════════════════════════════════════════════════════════════

class Specialist:
    """一个 specialist 模块 — 独立的 name + style_bible + 能力描述。"""

    def __init__(self, key: str, name: str, style_bible: Dict[str, Any],
                 capabilities: List[str], keywords: List[str]) -> None:
        self.key = key
        self.name = name
        self.style_bible = style_bible
        self.capabilities = capabilities
        self.keywords = keywords

    def match_persona(self, persona: str) -> bool:
        if not persona:
            return False
        persona_lower = persona.lower()
        return any(kw in persona_lower for kw in self.keywords)

    def inject_prompt(self, base_prompt: str) -> str:
        bible_text = self._format_bible()
        caps = "\n".join(f"  - {c}" for c in self.capabilities)
        return f"""{base_prompt}

## 当前专家: {self.name}

风格约束:
{bible_text}

擅长:
{caps}
"""

    def _format_bible(self) -> str:
        sb = self.style_bible
        parts = []
        if sb.get("theme"):       parts.append(f"主题: {sb['theme']}")
        if sb.get("color_palette"): parts.append(f"色调: {', '.join(sb['color_palette'])}")
        if sb.get("materials"):   parts.append(f"材质: {', '.join(sb['materials'])}")
        if sb.get("mood"):        parts.append(f"氛围: {sb['mood']}")
        if sb.get("avoid"):       parts.append(f"避讳: {', '.join(sb['avoid'])}")
        if sb.get("lighting"):    parts.append(f"光照: {sb['lighting']}")
        return "\n".join(parts) if parts else "无特定风格约束"


SPECIALISTS: Dict[str, Specialist] = {
    "cyberpunk": Specialist(
        key="cyberpunk", name="赛博朋克设计师",
        style_bible={
            "theme": "cyberpunk wasteland",
            "color_palette": ["#1a1a2e", "#16213e", "#0f3460", "#e94560"],
            "materials": ["weathered metal", "neon glass", "concrete"],
            "lighting": "low ambient + colored neon",
            "mood": "dystopian, gritty, vibrant",
            "avoid": ["pastoral", "bright", "medieval", "田园", "明亮暖色"],
        },
        capabilities=["暗色调金属家具", "霓虹灯光布置", "工业废墟风格", "赛博朋克酒吧/街道"],
        keywords=["赛博朋克", "cyberpunk", "暗黑", "霓虹"],
    ),
    "minimalist": Specialist(
        key="minimalist", name="北欧极简设计师",
        style_bible={
            "theme": "scandinavian minimalist",
            "color_palette": ["#f5f0e8", "#e8e0d5", "#d4c9b8", "#ffffff"],
            "materials": ["light oak", "linen", "wool", "matte ceramic"],
            "lighting": "soft natural + warm ambient",
            "mood": "calm, airy, clean",
            "avoid": ["ornate", "gold", "baroque", "繁复", "镀金", "深色"],
        },
        capabilities=["浅木色家具布置", "明亮通透空间", "极简线条", "北欧客厅/卧室"],
        keywords=["极简", "北欧", "minimalist", "scandinavian", "简约", "干净", "明亮"],
    ),
    "chinese": Specialist(
        key="chinese", name="新中式设计师",
        style_bible={
            "theme": "modern chinese",
            "color_palette": ["#4a3728", "#8b7355", "#f5f0e8", "#2c2c2c"],
            "materials": ["walnut wood", "bamboo weave", "rice paper", "dark elm"],
            "lighting": "warm indirect + paper lantern",
            "mood": "elegant, serene, scholarly",
            "avoid": ["neon", "plastic", "chrome", "霓虹", "塑料"],
        },
        capabilities=["胡桃木/黑檀木家具", "茶室/书房布局", "水墨配色", "新中式客厅"],
        keywords=["中式", "新中式", "茶室", "书房", "胡桃木", "禅", "雅致"],
    ),
    "industrial": Specialist(
        key="industrial", name="工业风设计师",
        style_bible={
            "theme": "industrial loft",
            "color_palette": ["#3a3a3a", "#6b6b6b", "#8b4513", "#d4d4d4"],
            "materials": ["concrete", "black steel", "exposed brick", "distressed leather"],
            "lighting": "exposed bulb + metal cage",
            "mood": "raw, urban, masculine",
            "avoid": ["floral", "lace", "pastel", "花卉", "蕾丝", "粉嫩"],
        },
        capabilities=["混凝土/黑铁材质", "loft 公寓/酒吧", "裸露结构", "工业风空间"],
        keywords=["工业风", "industrial", "loft", "仓库", "铁艺", "粗犷"],
    ),
    "lighting": Specialist(
        key="lighting", name="灯光师",
        style_bible={},
        capabilities=["壁灯/落地灯/吊灯布置", "霓虹/灯带氛围", "色温选择", "光影层次"],
        keywords=["灯光", "灯", "光照", "照明", "光源", "氛围光", "霓虹灯", "色温", "亮", "暗"],
    ),
    "plant": Specialist(
        key="plant", name="绿植顾问",
        style_bible={},
        capabilities=["室内盆栽布置", "植物与空间匹配", "绿植组合", "花卉摆放"],
        keywords=["绿植", "植物", "盆栽", "花", "绿化", "花园", "树木"],
    ),
    "material": Specialist(
        key="material", name="材质顾问",
        style_bible={},
        capabilities=["金属/木材/玻璃/布料/石材搭配", "配色方案", "材质冲突检测"],
        keywords=["材质", "配色", "颜色", "色调", "材料", "质感", "搭配"],
    ),
    "tidying": Specialist(
        key="tidying", name="整理助手",
        style_bible={},
        capabilities=["发现不协调布局", "重叠/悬空检测", "整理建议", "快速优化"],
        keywords=["整理", "检查", "检查一下", "看看", "有什么问题", "优化", "调整布局", "重新布置"],
    ),
}

_GENERALIST = Specialist(
    key="generalist", name="场景设计大师",
    style_bible={},
    capabilities=[
        "全风格场景设计（赛博朋克/北欧/中式/工业风）",
        "家具布局与空间规划",
        "灯光设计与氛围营造",
        "绿植与装饰摆放",
        "材质与配色建议",
        "布局检查与优化",
    ],
    keywords=[],
)

_GENERALIST_INTRO = """我是 **场景设计大师**，具备以下全部能力：

🎨 风格 — 赛博朋克 / 北欧极简 / 新中式 / 工业风
💡 灯光 — 壁灯、落地灯、霓虹灯带、色温
🌿 绿植 — 盆栽、花卉、空间绿化
🔧 材质 — 金属、木材、玻璃、布料搭配
📐 整理 — 检查重叠、悬空、比例异常

**场景指令** (直接对我说):
  • 加个台灯 | 把沙发往右移 | 删掉茶几
  • 把酒吧布置得更有氛围感
  • 检查一下布局有什么问题

**内置命令**:
  /help — 显示此帮助
  /总结 — 根据群聊讨论生成风格方案
  /检查 — 对当前场景做风格巡检"""


class PersonaRouter:
    """根据 persona 匹配 specialist。"""

    def __init__(self):
        self._specialists = dict(SPECIALISTS)

    def route(self, persona: str) -> Specialist:
        if not persona or persona.strip() == "你是一个有帮助的助手。":
            return _GENERALIST
        for key in ["cyberpunk", "minimalist", "chinese", "industrial",
                     "lighting", "plant", "material", "tidying"]:
            spec = self._specialists[key]
            if spec.match_persona(persona):
                logger.info("[MasterAgent] persona → %s (%s)", spec.name, spec.key)
                return spec
        return _GENERALIST

    def register(self, specialist: Specialist) -> None:
        self._specialists[specialist.key] = specialist

    def list_all(self) -> List[Dict[str, Any]]:
        return [{"key": k, "name": s.name, "capabilities": s.capabilities, "keywords": s.keywords}
                for k, s in self._specialists.items()]


# ═══════════════════════════════════════════════════════════════════════════
# SummaryAgent — 替换 SummaryService 的 ai_chat 回调
# ═══════════════════════════════════════════════════════════════════════════

class SummaryAgent:
    """摘要回调 — 增强版群聊压缩，融入场景上下文。

    签名: (prompt: str) -> str  (匹配 SummaryService 的 ai_chat 接口)
    """

    def __init__(self, fallback_chat: Callable[[str], str] = None) -> None:
        self._fallback_chat = fallback_chat

    def __call__(self, prompt: str) -> str:
        """生成群聊摘要，融入场景感知。

        LANChat 的 SummaryService 传入的 prompt 格式:
          "你是对话摘要助手。把以下群聊压缩成简洁要点..."
          + [已有摘要] + [新增对话] + [合并后的摘要]
        """
        try:
            # 尝试用 LLM 生成增强摘要 (带场景上下文)
            return self._enhanced_summary(prompt)
        except Exception as e:
            logger.warning("[SummaryAgent] enhanced summary failed: %s, falling back", e)
            return self._fallback_summary(prompt)

    def _enhanced_summary(self, prompt: str) -> str:
        """生成增强摘要 — 提取场景相关的风格共识。"""
        # 注入场景感知指令
        enhanced_prompt = prompt.replace(
            "把以下群聊压缩成简洁要点",
            "把以下群聊压缩成简洁要点。特别关注: 风格偏好、色调、材质、灯光、场景类型等场景设计相关的共识。如有明确的风格讨论，在摘要末尾用 [风格共识] 标注。"
        )
        return self._call_llm(enhanced_prompt)

    def _fallback_summary(self, prompt: str) -> str:
        if self._fallback_chat:
            return self._fallback_chat(prompt)
        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> str:
        try:
            from plugins.AITool.main import AITool
            from Quasar.cai.protocol.request import ChatRequest
            req = ChatRequest.from_text(text=prompt, metadata={"skip_conversation_store": True})
            chunks = AITool._cai_app.chat(req)
            return "".join(chunks).strip()
        except Exception as e:
            raise RuntimeError(f"LLM 调用失败: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MasterAgent — 统一入口 (AgentRunner 回调)
# ═══════════════════════════════════════════════════════════════════════════

class MasterAgent:
    """Master Agent — 接管 LANChat AgentRunner 的全部能力。

    能力:
      - 场景编辑 → AgentCoordinator
      - 普通聊天 → CAIApp + specialist 上下文
      - 讨论总结 → GroupAgent
      - 风格巡检 → GroupAgent
      - 能力查询 → /help
    """

    def __init__(
        self,
        fallback_chat: Callable[[str, List[str]], str] = None,
        global_style: Dict[str, Any] = None,
    ) -> None:
        self._fallback_chat = fallback_chat
        self._global_style = global_style or {}
        self._router = PersonaRouter()
        self._coordinator = None
        self._group_agent = None
        self._planner = None
        self._collaboration = None

    @property
    def coordinator(self):
        if self._coordinator is None:
            from .coordinator import AgentCoordinator
            self._coordinator = AgentCoordinator()
        return self._coordinator

    @property
    def group_agent(self):
        if self._group_agent is None:
            from .group_agent import GroupAgent
            self._group_agent = GroupAgent(ai_chat=self._group_ai_chat)
        return self._group_agent

    @property
    def planner(self):
        if self._planner is None:
            from .multi_step_planner import MultiStepPlanner
            self._planner = MultiStepPlanner(coordinator=self.coordinator)
        return self._planner

    @property
    def collaboration(self):
        if self._collaboration is None:
            from .collaboration import get_collaboration_manager
            self._collaboration = get_collaboration_manager()
        return self._collaboration

    def _group_ai_chat(self, system: str, messages: list) -> str:
        """GroupAgent 的 ai_chat 回调 — 调用 CAIApp。"""
        import json as _json
        try:
            from plugins.AITool.main import AITool
            from Quasar.cai.protocol.request import ChatRequest
            convo = "\n".join(messages) if isinstance(messages, list) else str(messages)
            text = f"{system}\n\n{convo}"
            req = ChatRequest.from_text(text=text, metadata={"skip_conversation_store": True})
            chunks = AITool._cai_app.chat(req)
            # 解析流式JSON响应
            result_text = []
            for chunk in chunks:
                try:
                    data = _json.loads(chunk)
                    for content in data.get("llm_content", []):
                        for part in content.get("part", []):
                            if part.get("content_type") == "text":
                                result_text.append(part.get("content_text", ""))
                except (_json.JSONDecodeError, KeyError, TypeError):
                    continue
            return "".join(result_text).strip() or "{}"
        except Exception as e:
            logger.warning("[MasterAgent] group_ai_chat failed: %s, using fallback", e)
            if self._fallback_chat:
                try:
                    return self._fallback_chat(system, messages if isinstance(messages, list) else [str(messages)])
                except Exception:
                    pass
            return "{}"

    # ── 对外接口 ───────────────────────────────────────────────────

    def __call__(self, system: str, messages: List[str]) -> str:
        """LANChat AgentRunner 回调入口。

        关键: 必须始终返回字符串, 绝不抛异常 —— 否则 LANChat 线程池
        会吞掉异常, _on_done 永不执行, 群聊收不到任何回复。
        """
        try:
            trigger = self._extract_trigger_text(messages)
            logger.info("[MasterAgent] __call__ trigger=%r persona=%r", trigger[:80], (system or "")[:40])

            # 1. 内置命令
            cmd = is_builtin_command(trigger)
            if cmd == "help":
                return self._handle_help(system)
            if cmd == "summary":
                return self._handle_summary(system, messages)
            if cmd == "patrol":
                return self._handle_patrol(system)

            # 2. 场景指令
            if is_scene_command(trigger):
                logger.info("[MasterAgent] routing → scene")
                return self._handle_scene(trigger, system, messages)

            # 3. 普通聊天
            logger.info("[MasterAgent] routing → chat")
            return self._handle_chat(system, messages)
        except Exception as e:
            logger.exception("[MasterAgent] __call__ 异常, 返回兜底回复")
            msg = str(e).lower()
            if any(k in msg for k in ("ssl", "eof", "timeout", "connection",
                                      "reset", "refused", "unreachable")):
                return "🌐 网络好像不太稳定，请稍后再发一次～"
            return "🤖 抱歉，刚才处理消息时出了点问题，请换个说法再试一次。"

    # ── 内置命令 ──────────────────────────────────────────────────

    def _handle_help(self, persona: str) -> str:
        specialist = self._router.route(persona)
        if specialist.key == "generalist":
            return _GENERALIST_INTRO
        caps = "\n".join(f"  • {c}" for c in specialist.capabilities)
        bible = specialist._format_bible()
        style_section = f"\n\n当前风格:\n{bible}" if bible else ""
        return f"**{specialist.name}** 擅长:\n{caps}{style_section}"

    def _handle_summary(self, persona: str, messages: List[str]) -> str:
        """讨论总结 — 用 GroupAgent 生成 Style Bible。"""
        # 从 messages 中提取聊天记录喂给 GroupAgent
        for msg in messages:
            if msg.startswith("[此前对话摘要]") or msg.startswith("[摘要]"):
                continue
            if ": " in msg:
                user, text = msg.split(": ", 1)
                self.group_agent.on_chat_message(user, text)

        if not self.group_agent.should_summarize():
            return "📝 讨论内容还不够丰富，继续聊聊风格偏好、色调、功能需求吧。至少需要 2 人参与讨论。"

        result = self.group_agent.try_summarize()
        if not result:
            return "⚠️ 总结生成失败，请稍后重试。"

        # 格式化输出
        plan = result.get("proposed_plan", {})
        bible = plan.get("style_bible", {})
        consensus = result.get("consensus_analysis", {})

        lines = ["📋 **讨论总结**\n"]
        lines.append(f"共识度: theme={consensus.get('theme_agreement', 0):.0%}  type={consensus.get('type_agreement', 0):.0%}")
        if bible:
            lines.append(f"\n**Style Bible**:")
            if bible.get("theme"):     lines.append(f"  主题: {bible['theme']}")
            if bible.get("mood"):      lines.append(f"  氛围: {bible['mood']}")
            if bible.get("materials"): lines.append(f"  材质: {', '.join(bible['materials'])}")
            if bible.get("lighting"):  lines.append(f"  光照: {bible['lighting']}")
            if bible.get("avoid"):     lines.append(f"  避讳: {', '.join(bible['avoid'])}")
        if plan.get("scene_name"):
            lines.append(f"\n场景名: {plan['scene_name']}")
        uncertainties = result.get("uncertainties", [])
        if uncertainties:
            lines.append(f"\n⚠️ 待确认: {', '.join(uncertainties)}")
        lines.append("\n确认后即可开始布置！直接对我说场景指令即可。")

        return "\n".join(lines)

    def _handle_patrol(self, persona: str) -> str:
        """风格巡检 — 用 GroupAgent 检查风格一致性。"""
        specialist = self._router.route(persona)
        bible = specialist.style_bible if specialist.key != "generalist" else self._global_style

        if not bible:
            return "📝 还没有设置风格标准。先讨论一下想要的风格，然后输入 /总结 来生成 Style Bible。"

        # 同步巡检 (不依赖 VLM, 用 GroupAgent 的规则检查)
        self.group_agent.on_operation_event({"data": {"action": "patrol_check"}, "metadata": {}})
        if not self.group_agent.should_patrol(user_requested=True):
            return f"✅ 操作量较少 ({self.group_agent._operation_count} 次)，尚未触发巡检阈值。当前偏离率: {self.group_agent.deviation_rate:.0%}"

        result = self.group_agent.try_patrol(style_bible=bible, user_requested=True)
        if not result:
            return "⚠️ 巡检执行失败，请稍后重试。"

        score = result.get("overall_consistency", "?")
        violations = result.get("violations", [])
        recs = result.get("recommendations", [])

        lines = [f"🔍 **风格巡检报告** (一致性: {score}/100)\n"]
        if violations:
            lines.append("**偏离项:**")
            for v in violations[:5]:
                lines.append(f"  ⚠️ {v.get('object_id', '?')}: {v.get('description', '')} (评分 {v.get('consistency_score', '?')})")
                for s in v.get("suggestions", []):
                    lines.append(f"    💡 {s}")
        else:
            lines.append("✅ 未检测到明显偏离")
        if recs:
            lines.append(f"\n**建议:** {', '.join(recs[:3])}")

        return "\n".join(lines)

    # ── 场景指令 ──────────────────────────────────────────────────

    def _handle_scene(self, user_text: str, persona: str, messages: List[str]) -> str:
        specialist = self._router.route(persona)
        logger.info("[MasterAgent] scene → %s: %s", specialist.key, user_text[:80])

        style_bible = dict(self._global_style)
        if specialist.style_bible:
            style_bible.update(specialist.style_bible)

        if specialist.key == "tidying":
            user_text = self._enhance_tidying(user_text, messages)

        scene_state = {
            "metadata": {"room_size": [5, 3, 3], "scene_name": "lanchat_scene", "style_bible": style_bible},
            "intermediate": {"style_bible": style_bible},
        }

        # 场景组合（物品清单/整体布置）→ SceneComposer 批量建模+布局+导入
        # 判断同时看当前指令 + 历史消息：用户可能只说"生成3d模型/按清单生成"，
        # 而真正的物品清单在之前 AI 给出的消息里。
        from .scene_composer import is_compose_request
        compose_text = self._gather_compose_text(user_text, messages)
        if is_compose_request(user_text) or is_compose_request(compose_text):
            logger.info("[MasterAgent] scene → compose (整体场景组合)")
            return self._handle_scene_compose(user_text, messages, specialist)

        # 复杂需求 → Multi-Step Planning 分解；简单指令 → 单步 Coordinator
        from .multi_step_planner import MultiStepPlanner
        if MultiStepPlanner.is_complex_task(user_text):
            logger.info("[MasterAgent] scene → multi-step (complex task)")
            return self._handle_scene_multistep(user_text, scene_state, style_bible, specialist)

        return self._handle_scene_single(user_text, scene_state, style_bible, specialist, messages)

    def _handle_scene_compose(self, user_text: str, messages: List[str],
                              specialist: "Specialist") -> str:
        """整体场景组合：从清单/方案批量生成模型、布局、导入引擎。"""
        from .scene_composer import SceneComposer

        # 优先从最近对话中找完整清单文本（用户可能只说"按清单生成"）
        compose_text = self._gather_compose_text(user_text, messages)
        image_url = self._extract_image_url(messages)

        composer = SceneComposer(room_size=[5.0, 3.0, 3.0], scene_name="lanchat_scene")
        result = composer.compose(compose_text, image_url=image_url, do_import=True)

        # 记录到 GroupAgent
        for _ in result.get("items", []):
            self.group_agent.on_operation_event({"data": {"action": "add"}, "metadata": {}})

        tag = f"[{specialist.name}]"
        if result.get("error") and not result.get("imported"):
            return f"{tag} ⚠️ 场景组合失败：{result['error']}"

        extracted = result.get("extracted_count", 0)
        model_count = result.get("model_count", 0)
        imported = result.get("imported", [])
        failed = result.get("failed", [])

        lines = [f"{tag} 🏗️ 场景组合完成"]
        lines.append(f"  • 识别物体：{extracted} 个")
        lines.append(f"  • 获取模型：{model_count} 个")
        lines.append(f"  • 导入引擎：{len(imported)} 个")
        if imported:
            lines.append(f"\n✅ 已放入场景：{('、'.join(imported[:10]))}")
        if failed:
            lines.append(f"⚠️ 未完成：{('、'.join(failed[:8]))}")
        return "\n".join(lines)

    def _gather_compose_text(self, user_text: str, messages: List[str]) -> str:
        """收集用于组合的文本：当前指令 + 最近含清单的历史消息。"""
        # 若当前指令本身就含清单（数字列表），直接用
        import re as _re
        if len(_re.findall(r"^\s*\d+[\.、)]", user_text, _re.MULTILINE)) >= 3:
            return user_text
        # 否则回溯最近的长消息（很可能是 AI 给出的物品清单）
        for msg in reversed(messages):
            if msg.startswith("[此前对话摘要]") or msg.startswith("[摘要]"):
                continue
            body = msg.split(": ", 1)[-1] if ": " in msg else msg
            if len(_re.findall(r"^\s*\d+[\.、)]", body, _re.MULTILINE)) >= 3 or "清单" in body:
                logger.info("[MasterAgent] compose: 使用历史清单文本 (len=%d)", len(body))
                return body + "\n\n" + user_text
        return user_text

    def _handle_scene_single(self, user_text: str, scene_state: Dict[str, Any],
                             style_bible: Dict[str, Any], specialist: "Specialist",
                             messages: List[str]) -> str:
        """单步场景编辑 — 含协同感知（意图预览 / 冲突检测 / 物体锁）。"""
        sender = self._extract_sender(messages)

        # 注入参考图 URL（用于 3D 模型生成）
        image_url = self._extract_image_url(messages)
        if image_url:
            scene_state.setdefault("intermediate", {})["reference_image_url"] = image_url
            logger.info("[MasterAgent] scene: reference image %r", image_url)

        result = self.coordinator.handle(user_text=user_text, scene_state=scene_state, style_bible=style_bible)

        intent = result.get("intent", {})
        spatial = result.get("spatial", {})
        target = intent.get("target", "")
        position = spatial.get("position")

        # 协同感知：检测是否与他人正在操作的预览位置冲突
        collab_warning = ""
        if position and target:
            conflict_user = self.collaboration.check_preview_collision(sender, position)
            if conflict_user:
                collab_warning = f"\n⚠️ {conflict_user} 正在附近操作，请注意协调。"
            # 广播本次操作意图（供他人感知）+ 短暂锁定目标物体
            action = intent.get("action", "")
            self.collaboration.broadcast_intent(
                sender,
                tooltip=f"{action} {target}",
                preview_position=position,
                status="placing_object" if action == "add" else "moving",
            )
            if action in ("move", "modify", "delete"):
                self.collaboration.lock_object(target, sender, operation=action)

        # 记录操作到 GroupAgent (用于风格巡检)
        self.group_agent.on_operation_event({
            "data": {"action": intent.get("action"), "target": target},
            "metadata": {},
        })

        reply = self._format_scene(result, specialist) + collab_warning

        # 记录本轮对话到记忆单例（供后续记忆增强 / 上下文回忆）
        try:
            from .memory import get_memory_manager
            get_memory_manager().record_conversation(user_text, reply)
        except Exception as e:
            logger.warning("[MasterAgent] record_conversation failed: %s", e)

        return reply

    def _handle_scene_multistep(self, user_text: str, scene_state: Dict[str, Any],
                                style_bible: Dict[str, Any], specialist: "Specialist") -> str:
        """复杂需求 — 分解为子任务并逐步执行，返回计划+执行摘要。"""
        plan = self.planner.decompose(user_text, scene_state=scene_state)
        tasks = plan.get("tasks", [])
        if not tasks:
            # 分解失败，退化为单步
            result = self.coordinator.handle(user_text=user_text, scene_state=scene_state, style_bible=style_bible)
            return self._format_scene(result, specialist)

        run = self.planner.run_plan(scene_state=scene_state, style_bible=style_bible)

        # 每个子任务都记一次操作事件，便于风格守护累计
        for _ in tasks:
            self.group_agent.on_operation_event({"data": {"action": "multi_step"}, "metadata": {}})

        tag = f"[{specialist.name}]"
        lines = [f"{tag} 📐 复杂需求已分解为 {len(tasks)} 步:"]
        for i, t in enumerate(tasks, 1):
            lines.append(f"  {i}. {t.get('description', '?')}")
        completed = run.get("completed", 0)
        lines.append(f"\n✅ 已执行 {completed}/{len(tasks)} 步")
        if plan.get("analysis"):
            lines.append(f"\n💡 {plan['analysis']}")
        return "\n".join(lines)

    def _enhance_tidying(self, user_text: str, messages: List[str]) -> str:
        if len(user_text) > 10:
            return user_text
        return "检查当前场景的布局，发现任何不协调、重叠、悬空、比例异常的问题，并给出修正建议"

    # ── 普通聊天 ──────────────────────────────────────────────────

    def _handle_chat(self, persona: str, messages: List[str]) -> str:
        specialist = self._router.route(persona)
        system = self._build_chat_system(specialist)

        # 记录到 GroupAgent (用于后续总结)
        for msg in messages:
            if msg.startswith("[摘要]") or msg.startswith("[此前"):
                continue
            if ": " in msg:
                user, text = msg.split(": ", 1)
                self.group_agent.on_chat_message(user, text)

        if self._fallback_chat:
            return self._fallback_chat(system, messages)
        return self._call_caiapp(system, messages)

    def _build_chat_system(self, specialist: Specialist) -> str:
        base = "你是场景设计助手。如果用户询问你的能力，引导他们使用场景指令或 /help 查看。回复简洁实用。"
        if specialist.key == "generalist":
            return base + "\n\n你拥有全风格设计能力。"
        return specialist.inject_prompt(base)

    def _call_caiapp(self, system: str, messages: List[str]) -> str:
        try:
            from plugins.AITool.main import AITool
            from Quasar.cai.protocol.request import ChatRequest
            convo = "\n".join(messages)
            text = f"{system}\n\n以下是群聊上下文：\n{convo}\n\n请以你的身份回复最新消息。"
            req = ChatRequest.from_text(text=text, metadata={"skip_conversation_store": True})
            chunks = AITool._cai_app.chat(req)
            return "".join(chunks).strip()
        except Exception as e:
            logger.warning("[MasterAgent] CAIApp failed: %s, using fallback_chat", e)
            if self._fallback_chat:
                return self._fallback_chat(system, messages)
            return "🌐 网络好像不太稳定，请稍后再试～"

    # ── 格式化 ────────────────────────────────────────────────────

    def _format_scene(self, result: Dict[str, Any], specialist: Specialist) -> str:
        status = result.get("status", "unknown")
        intent = result.get("intent", {})
        spatial = result.get("spatial", {})
        exec_result = result.get("result", {})
        action = intent.get("action", "?")
        target = intent.get("target", "物体")
        tag = f"[{specialist.name}]"

        # 记忆提示（连续操作时的主动询问）+ 歧义候选选项
        memory_hint = result.get("memory_hint", "") or exec_result.get("memory_hint", "")
        mem_suffix = f"\n{memory_hint}" if memory_hint else ""

        if status == "executed":
            pos = spatial.get("position", [0, 0, 0])
            pos_str = f"({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})" if pos and len(pos) >= 3 else ""
            note = exec_result.get("note", "")
            model_info = f" [{note}]" if note else ""
            return f"{tag} ✅ 已{'放置' if action == 'add' else '移动'}「{target}」到 {pos_str}{model_info}{mem_suffix}"
        if status == "planned_only":
            pos = spatial.get("position", [0, 0, 0])
            pos_str = f"({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})" if pos and len(pos) >= 3 else ""
            note = exec_result.get('note', '引擎未连接')
            has_model = exec_result.get('model_path', '')
            if has_model:
                note += f" (模型已就绪: {has_model})"
            return f"{tag} 📋 已规划「{target}」位置 {pos_str}\n({note}){mem_suffix}"
        if status == "pending_user_approval":
            msg = exec_result.get("message", "需要确认")
            choices = exec_result.get("choices", [])
            lines = [f"{tag} ❓ {msg}"]
            if choices:
                lines.append("\n可选方案（回复编号或直接说明）：")
                for i, c in enumerate(choices, 1):
                    lines.append(f"  {i}. {c.get('label', '?')}")
            return "\n".join(lines) + mem_suffix
        if action == "question":
            return f"{tag} 🤔 请具体说明，例如: 在沙发旁边加个台灯"
        if status == "error":
            return f"{tag} ❌ {exec_result.get('error', '未知错误')}"
        return f"{tag} ⚠️ 操作未完成"

    # ── 辅助 ───────────────────────────────────────────────────────

    def _extract_trigger_text(self, messages: List[str]) -> str:
        if not messages:
            return ""
        for msg in reversed(messages):
            if msg.startswith("[此前对话摘要]") or msg.startswith("[摘要]"):
                continue
            text = msg.split(": ", 1)[-1] if ": " in msg else msg
            text = re.sub(r'@\w+\s*', '', text).strip()
            return text
        return messages[-1] if messages else ""

    def _extract_sender(self, messages: List[str]) -> str:
        """从最近一条非摘要消息中提取发言人名字（用于协同锁/意图预览）。"""
        if not messages:
            return "user"
        for msg in reversed(messages):
            if msg.startswith("[此前对话摘要]") or msg.startswith("[摘要]"):
                continue
            if ": " in msg:
                return msg.split(": ", 1)[0].strip() or "user"
            return "user"
        return "user"

    def _extract_image_url(self, messages: List[str]) -> str:
        """从最近的消息中提取 fileid:// 或 http 图片 URL。

        用于场景编辑时作为 3D 生成的参考图。
        """
        import re as _re
        for msg in reversed(messages):
            if msg.startswith("[此前对话摘要]") or msg.startswith("[摘要]"):
                continue
            text = msg.split(": ", 1)[-1] if ": " in msg else msg
            # fileid://xxx
            m = _re.search(r'fileid://(\S+)', text)
            if m:
                return f"fileid://{m.group(1)}"
            # 效果图 URL
            m2 = _re.search(r'(https?://\S+\.(?:png|jpg|jpeg|webp|gif))', text, _re.IGNORECASE)
            if m2:
                return m2.group(1)
        return ""


# ═══════════════════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════════════════

def create_master_agent(
    global_style: Dict[str, Any] = None,
    fallback_chat: Callable[[str, List[str]], str] = None,
) -> MasterAgent:
    """创建 MasterAgent — 替换 LANChat 的 _make_agent_ai_chat()。

    用法 (在 LANChat main.py 中):
        from cai_extensions.agent.agent_adapter import create_master_agent
        server._agent_runner = AgentRunner(ai_chat=create_master_agent())
    """
    return MasterAgent(fallback_chat=fallback_chat, global_style=global_style)


def create_summary_agent(
    fallback_chat: Callable[[str], str] = None,
) -> SummaryAgent:
    """创建 SummaryAgent — 替换 LANChat 的 _make_summary_ai_chat()。

    用法 (在 LANChat main.py 中):
        from cai_extensions.agent.agent_adapter import create_summary_agent
        server._summary_service = SummaryService(ai_chat=create_summary_agent())
    """
    return SummaryAgent(fallback_chat=fallback_chat)


# 兼容旧接口
create_lanchat_adapter = create_master_agent
AgentAdapter = MasterAgent


__all__ = [
    "MasterAgent", "SummaryAgent", "AgentAdapter",
    "Specialist", "PersonaRouter",
    "create_master_agent", "create_summary_agent", "create_lanchat_adapter",
    "is_scene_command", "is_builtin_command", "SPECIALISTS",
]
