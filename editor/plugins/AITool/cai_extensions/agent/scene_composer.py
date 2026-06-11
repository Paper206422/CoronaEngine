"""场景组合器 — 从设计描述/物品清单批量生成并布局多个 3D 物体。

区别于单步编辑（加一个物体）和 multi-step（泛泛分解为几步），
SceneComposer 处理「根据这份清单/方案组合整个场景」类需求：

  1. 用 LLM 从文字中提取结构化物体清单
  2. 为每个物体获取 3D 模型（复用 ModelProvider：搜索→生成→下载）
  3. 用 Constraint Solver / 默认网格布局算出每个物体位置
  4. 返回组合结果（供上层导入引擎 + 广播）

全程详细日志便于验收。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 触发场景组合的关键词
_COMPOSE_PATTERNS = [
    r"物品清单", r"清单", r"组合(?:场景|这个|整个)", r"布置(?:整个|这个|好这)",
    r"根据.{0,10}(?:方案|清单|设计|效果图).{0,6}(?:生成|布置|组合|搭建)",
    r"按.{0,8}清单",
    r"把.{0,10}(?:都|全部|所有).{0,6}(?:生成|放|布置|导入)",
    r"一键(?:生成|布置|组合)",
    # 直接生成类：'生成欧式卧室' / '生成一个现代客厅' 等
    r"生成.{0,12}(?:卧室|客厅|厨房|书房|房间|浴室|场景|办公室|餐厅)",
]

_EXTRACT_SYSTEM_PROMPT = """你是场景物品清单解析器。从用户文字中提取需要放入 3D 场景的【主要独立家具/物件】。
输出 JSON 数组，每项: {"name":"物体名","quantity":数量,"keywords":"英文关键词(用于3D生成prompt)"}
规则:
- 只提取能独立建模、有体积的【大件物体】：如 床、衣柜、沙发、桌、椅、柜、台灯、地毯、绿植、挂画、镜子等
- 必须合并/忽略以下琐碎项，不要单独列出：
  * 床的附属：床垫、被子、枕头、靠枕、床旗、床品 → 都并入"床"，不单列
  * 墙面/背景：背景墙、软包、护墙板、石膏线、墙面 → 不是物体，忽略
  * 建筑设施：空调出风口、新风口、筒灯、灯带、顶灯（嵌入式）→ 忽略
  * 小件杂物：收纳篮、收纳盒、护肤品 → 忽略
  * 同类合并：左右床头柜=1种"床头柜"(quantity:2)，台灯/壁灯择一
- 忽略所有尺寸/颜色/风格/材质描述
- name 用简洁中文（2-6字），quantity 默认1
- keywords 给出适合 3D 生成的英文描述
- 控制在 8 个以内，只保留最重要的大件
只输出 JSON 数组，不要解释。"""

# 不该单独建模的物体（关键词黑名单，双保险过滤 LLM 漏网项）
_ITEM_BLACKLIST = [
    # 床品/附属
    "床垫", "被子", "被褥", "枕头", "靠枕", "抱枕", "床旗", "床品", "床单", "被",
    # 墙面/天花板
    "背景墙", "软包", "护墙板", "石膏线", "墙面", "墙", "天花", "踢脚线",
    # 建筑设施 + 天花板物品
    "空调", "新风", "出风口", "筒灯", "灯带", "顶灯", "嵌灯", "吊灯", "吸顶灯",
    # 墙面附着物（应在盒子上，不单独建模）
    "窗帘", "壁画", "挂画", "装饰画", "卷帘", "百叶",
    # 杂物
    "收纳篮", "收纳盒", "收纳", "护肤品", "摆件杂物",
]


def _is_blacklisted(name: str) -> bool:
    """判断物体名是否在黑名单（不该单独建模的琐碎/附属/建筑项）。"""
    n = (name or "").strip()
    if not n:
        return True
    return any(bad in n for bad in _ITEM_BLACKLIST)


def is_compose_request(text: str) -> bool:
    """判断是否为场景组合类请求。"""
    t = (text or "").strip()
    if not t:
        return False
    # 含数字列表（如 "1. xx 2. xx"）也视为清单
    if len(re.findall(r"^\s*\d+[\.、)]", t, re.MULTILINE)) >= 3:
        return True
    for pat in _COMPOSE_PATTERNS:
        if re.search(pat, t):
            return True
    return False


class SceneComposer:
    """场景组合器。"""

    # 单次场景生成的物体数量上限（防止一次生成过多 3D 模型，耗时/占用过大）
    DEFAULT_MAX_ITEMS = 8

    def __init__(self, room_size: List[float] = None, scene_name: str = "lanchat_scene",
                 max_items: int = DEFAULT_MAX_ITEMS) -> None:
        self.room_size = room_size or [5.0, 3.0, 3.0]
        self.scene_name = scene_name
        self.max_items = max(1, int(max_items))
        self._provider = None

    @property
    def provider(self):
        if self._provider is None:
            from .model_provider import ModelProvider
            self._provider = ModelProvider()
        return self._provider

    # ── 步骤1: 提取物体清单 ──────────────────────────────────────

    def extract_items(self, text: str) -> List[Dict[str, Any]]:
        """从文字中提取物体清单。优先 LLM，失败回退正则，再过滤黑名单。"""
        logger.info("[SceneComposer] 提取物体清单, 文本长度=%d", len(text))
        items = self._llm_extract(text)
        if not items:
            items = self._regex_extract(text)

        # 黑名单过滤 + 去重（剔除床品/背景墙/建筑设施等不该单独建模的琐碎项）
        filtered: List[Dict[str, Any]] = []
        seen = set()
        for it in items:
            name = (it.get("name") or "").strip()
            if _is_blacklisted(name):
                logger.info("[SceneComposer] 过滤琐碎项: %s", name)
                continue
            if name in seen:
                continue
            seen.add(name)
            filtered.append(it)

        logger.info("[SceneComposer] 提取到 %d 个物体（过滤前 %d）: %s",
                    len(filtered), len(items), [it.get("name") for it in filtered])
        return filtered

    def _llm_extract(self, text: str) -> List[Dict[str, Any]]:
        try:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
            from Quasar.ai_models.base_pool.registry import get_chat_model
            from langchain_core.messages import HumanMessage, SystemMessage

            def _call():
                llm = get_chat_model(temperature=0, request_timeout=30.0)
                return llm.invoke([
                    SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                    HumanMessage(content=text[:2000]),
                ])

            ex = ThreadPoolExecutor(max_workers=1)
            fut = ex.submit(_call)
            try:
                resp = fut.result(timeout=35.0)
            except FTimeout:
                ex.shutdown(wait=False, cancel_futures=True)
                logger.warning("[SceneComposer] LLM 提取超时")
                return []
            finally:
                ex.shutdown(wait=False)

            raw = (resp.content if hasattr(resp, "content") else str(resp)).strip()
            if "```" in raw:
                s = raw.find("["); e = raw.rfind("]")
                if s != -1 and e != -1:
                    raw = raw[s:e + 1]
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            items = []
            for d in data[:20]:
                if isinstance(d, dict) and d.get("name"):
                    items.append({
                        "name": str(d["name"]).strip(),
                        "quantity": int(d.get("quantity", 1) or 1),
                        "keywords": str(d.get("keywords", "") or d["name"]).strip(),
                    })
            return items
        except Exception as e:
            logger.warning("[SceneComposer] LLM 提取失败: %s", e)
            return []

    def _regex_extract(self, text: str) -> List[Dict[str, Any]]:
        """正则回退：抓取 "1. 双人床：..." 这类列表项。"""
        items: List[Dict[str, Any]] = []
        for m in re.finditer(r"^\s*\d+[\.、)]\s*([^\n：:，,（(]+)", text, re.MULTILINE):
            name = m.group(1).strip()
            if name and len(name) <= 20:
                items.append({"name": name, "quantity": 1, "keywords": name})
            if len(items) >= 20:
                break
        return items

    # ── 步骤2: 批量获取模型 ──────────────────────────────────────

    def acquire_models(self, items: List[Dict[str, Any]],
                       image_url: str = "") -> List[Dict[str, Any]]:
        """为每个物体获取 3D 模型路径。返回带 model_path 的物体列表。"""
        logger.info("[SceneComposer] === 批量获取 %d 个物体模型 ===", len(items))
        self._last_fail_reasons: List[str] = []
        resolved: List[Dict[str, Any]] = []
        for idx, item in enumerate(items, 1):
            name = item["name"]
            logger.info("[SceneComposer] (%d/%d) 获取模型: %s", idx, len(items), name)
            try:
                result = self.provider.acquire(
                    name=name,
                    image_url=image_url,
                    prompt_text=item.get("keywords") or f"high quality 3D model of {name}",
                )
                if result.success:
                    item = dict(item)
                    item["model_path"] = result.local_path
                    item["source"] = result.source
                    resolved.append(item)
                    logger.info("[SceneComposer] (%d/%d) ✓ %s → %s",
                                idx, len(items), name, result.local_path)
                else:
                    self._last_fail_reasons.append(f"{name}: {result.error}")
                    logger.warning("[SceneComposer] (%d/%d) ✗ %s: %s",
                                   idx, len(items), name, result.error)
            except Exception as e:
                self._last_fail_reasons.append(f"{name}: {e}")
                logger.exception("[SceneComposer] 获取模型异常 %s: %s", name, e)
        logger.info("[SceneComposer] === 模型获取完成: %d/%d 成功 ===",
                    len(resolved), len(items))
        return resolved

    # ── 步骤2(方案A): 调用原 model_retrieval workflow ──────────────
    def _run_model_retrieval(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """调用原 model_retrieval workflow，为每个物体「文生图→图生3D/检索」。

        完全复用原系统：构造 state.global_assets.multi_scene.approved_elements
        （只给 item_name + image_prompt，不给图，dispatch 会自动文生图补偿），
        invoke 编译好的 DAG，取回 global_assets.model_retrieval.model_results。

        不修改原 workflow 任何代码，仅作为调用方。失败时回退到 acquire_models。
        """
        self._last_fail_reasons = []
        try:
            from ..flows.model_retrieval_workflow import (
                WORKFLOWS, MODEL_RETRIEVAL_FUNCTION_ID,
            )
            graph = WORKFLOWS.get(MODEL_RETRIEVAL_FUNCTION_ID)
            if graph is None:
                raise RuntimeError("model_retrieval workflow 未注册")
        except Exception as e:
            logger.warning("[SceneComposer] 无法加载 model_retrieval workflow: %s，回退本地获取", e)
            return self.acquire_models(items)

        # 组装 approved_elements：每项 {item_name, image_prompt}
        approved = []
        for it in items:
            approved.append({
                "item_name": it["name"],
                "image_prompt": it.get("keywords") or it["name"],
            })

        state = {
            "session_id": f"compose_{int(__import__('time').time())}",
            "metadata": {
                "scene_name": self.scene_name, "room_size": self.room_size,
                "skip_six_view_capture": True,  # 跳过截图，避免引擎渲染死锁导致页面卡死
            },
            "global_assets": {
                "multi_scene": {
                    "approved_elements": approved,
                    "generated_images": {},  # 不预置图，让 dispatch 自动文生图
                }
            },
            "intermediate": {},
        }

        logger.info("[SceneComposer] 调用原 model_retrieval workflow（%d 个物体，文生图→图生3D）...",
                    len(approved))
        try:
            out = graph.invoke(state)
        except Exception as e:
            logger.exception("[SceneComposer] model_retrieval workflow 执行异常: %s", e)
            self._last_fail_reasons.append(f"workflow异常: {e}")
            return self.acquire_models(items)  # 兜底

        # 取回 model_results
        model_results = (out.get("global_assets", {})
                            .get("model_retrieval", {})
                            .get("model_results", []))
        if not model_results:
            logger.warning("[SceneComposer] model_retrieval 无结果，回退本地获取")
            return self.acquire_models(items)

        # 转成 SceneComposer 内部结构（带 model_path）
        resolved: List[Dict[str, Any]] = []
        from ..flows.model_retrieval_workflow.helpers import resolve_model_file
        for row in model_results:
            name = row.get("item_name", "")
            err = row.get("error")
            if err:
                self._last_fail_reasons.append(f"{name}: {err}")
                continue
            raw_path = row.get("model_path", "")
            local_path = resolve_model_file(raw_path) if raw_path else ""
            if not local_path:
                self._last_fail_reasons.append(f"{name}: 模型路径无效({raw_path})")
                continue
            resolved.append({
                "name": name,
                "model_path": local_path,
                "source": row.get("source", "generation"),
                "object_id": row.get("object_id", name),
            })

        logger.info("[SceneComposer] model_retrieval 完成: %d/%d 成功",
                    len(resolved), len(items))
        return resolved

    # ── 步骤3+4: 复用原有 scene_composition_workflow 的布局+导入 ──
    def _build_placement_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """转换为原 workflow compose_scene 期望的 placement_items 结构。"""
        return [{
            "object_id": it["name"], "name": it["name"],
            "file_name": it["name"], "local_path": it.get("model_path", ""),
        } for it in items]

    def compose(self, text: str, image_url: str = "",
                do_import: bool = True) -> Dict[str, Any]:
        """完整场景组合：提取清单 → 获取模型 → 复用原 workflow 布局+导入。"""
        logger.info("[SceneComposer] ====== 开始场景组合（复用原 workflow）======")
        items = self.extract_items(text)
        if not items:
            return {"items": [], "imported": [], "failed": [],
                    "extracted_count": 0, "model_count": 0,
                    "error": "未能从描述中提取出物体清单"}

        # 数量上限控制：超出则只取前 max_items 个，避免一次生成过多 3D 模型
        extracted_total = len(items)
        truncated = 0
        if extracted_total > self.max_items:
            truncated = extracted_total - self.max_items
            items = items[:self.max_items]
            logger.info("[SceneComposer] 物体数 %d 超过上限 %d，截断为前 %d 个（丢弃 %d）",
                        extracted_total, self.max_items, self.max_items, truncated)

        # 调用原 model_retrieval workflow：每个物体「文生图 → 图生3D / 检索复用」
        # 完全复用原系统成熟管线（dispatch 自带文生图补偿 + retrieve + generate）
        resolved = self._run_model_retrieval(items)
        if not resolved:
            reasons = getattr(self, "_last_fail_reasons", [])
            detail = ("；".join(reasons[:3]) + ("…" if len(reasons) > 3 else "")) if reasons else "未知原因"
            return {"items": items, "imported": [],
                    "failed": [it["name"] for it in items],
                    "extracted_count": extracted_total, "model_count": 0,
                    "truncated": truncated,
                    "fail_reasons": reasons,
                    "error": f"所有物体的 3D 模型获取失败（{detail}）"}
        result = self._run_original_workflow(text, resolved, items, do_import)
        result["extracted_count"] = extracted_total  # 报告真实识别总数
        result["truncated"] = truncated
        return result

    @staticmethod
    def _get_object_height(actor_name: str, asset_meta: Dict[str, Any],
                           geo_map: Dict[str, Any]) -> float:
        """从 AABB 或 geometry 中获取物体的高度（米）。

        优先 asset_metadata（trimesh 读出的精确 size），
        回退 compose_scene 输出的 scale（但 scale 不直接给出高度，返回 0）。
        """
        # asset_meta 的 key 是文件名 stem；用 actor_name + geo_map 三重匹配
        meta = (asset_meta.get(actor_name)
                or asset_meta.get(geo_map.get(actor_name, {}).get("name", ""))
                or {})
        if meta and meta.get("size") and len(meta["size"]) >= 2:
            return float(meta["size"][1])  # size = [width, height, depth]
        # 没法知道真实高度，返回 0 让调用方用 Y>=margin 兜底
        return 0.0

    # ── 场景框架（室内盒子 / 室外 terrain）──────────────────────

    @staticmethod
    def _detect_scene_indoor(prompt: str) -> bool:
        """从 prompt 推断是否为室内场景。默认按室内处理。"""
        text = (prompt or "").lower()
        outdoor_kw = ["室外", "户外", "森林", "山坡", "公园", "街道", "广场",
                       "outdoor", "forest", "park", "street", "garden",
                       "terrain", "mountain", "landscape"]
        indoor_kw = ["卧室", "客厅", "厨房", "室内", "房间", "书房", "浴室",
                      "bedroom", "living", "kitchen", "indoor", "room", "bath"]
        if any(k in text for k in outdoor_kw):
            return False
        if any(k in text for k in indoor_kw):
            return True
        return True  # 默认室内

    def _generate_room_box(self) -> None:
        """在引擎场景中生成整体房间盒子（六面体，单个空心 OBJ）。

        用单个 mesh 替代六片独立平面，物理上作为完整刚体——墙与墙锁死，
        物体怎么碰撞都撑不开。盒内空心，物体在里面自由摆放。
        可在盒子四个上顶点放置观察摄像头供 VLM 审核调整视角。
        """
        import os as _os, tempfile as _tf, time as _t

        width, depth, height = self.room_size[0], self.room_size[1], self.room_size[2]

        # 1. 生成空心盒子 OBJ（六面体，面法向内）
        tmp_dir = _os.path.join(_tf.gettempdir(), "corona_room_box")
        _os.makedirs(tmp_dir, exist_ok=True)
        mtl_path = _os.path.join(tmp_dir, "box.mtl")
        obj_path = _os.path.join(tmp_dir, "box.obj")
        with open(mtl_path, "w", encoding="ascii") as f:
            f.write("newmtl wall\nKa 0.85 0.85 0.85\nKd 0.92 0.92 0.92\n"
                    "Ks 0.0 0.0 0.0\nNs 0.0\nd 0.6\n")
        # 1×1×1 中心在原点，面法向内（从外面看逆时针=法向外；我们需要法向内）
        with open(obj_path, "w", encoding="ascii") as f:
            f.write("mtllib box.mtl\nusemtl wall\n"
                    "# 8 vertices of a 1x1x1 cube centered at origin\n"
                    "v -0.5 -0.5 -0.5\nv  0.5 -0.5 -0.5\nv  0.5  0.5 -0.5\nv -0.5  0.5 -0.5\n"
                    "v -0.5 -0.5  0.5\nv  0.5 -0.5  0.5\nv  0.5  0.5  0.5\nv -0.5  0.5  0.5\n"
                    "vn  0.0  0.0 -1.0\nvn  1.0  0.0  0.0\nvn  0.0  0.0  1.0\nvn -1.0  0.0  0.0\n"
                    "vn  0.0  1.0  0.0\nvn  0.0 -1.0  0.0\n"
                    "# 6 faces (quads), normals inward so camera sees through to inside\n"
                    "f 1//1 4//1 3//1 2//1\n"
                    "f 2//2 6//2 5//2 1//2\n"
                    "f 5//3 7//3 8//3 4//3\n"
                    "f 4//4 8//4 6//4 2//4\n"
                    "f 3//5 7//5 6//5 2//5\n"
                    "f 1//6 5//6 8//6 4//6\n")

        # 2. 场景 + Actor
        try:
            from CoronaCore.core.managers import scene_manager as _sm
            from CoronaCore.core.entities.actor import Actor
        except ImportError:
            return

        scene = _sm.get("")
        if scene is None:
            routes = _sm.list_all()
            scene = _sm.get(routes[0]) if routes else None
        if scene is None:
            return

        existing = {a.name for a in scene.get_actors()}
        if any(n.startswith("__room_") for n in existing):
            return

        # 3. 单个盒子 Actor
        try:
            actor = Actor(name="__room_box", route=obj_path, actor_type="mesh",
                          parent_scene=scene)
            # 盒子中心在房间中心，底部 Y=0
            actor.set_position([0.0, height / 2.0, 0.0], True)
            actor.set_scale([width, height, depth], True)
            # 开碰撞，锁死不动——整个盒子一个刚体，撑不开
            mech = getattr(actor, "_mechanics", None)
            if mech is not None:
                try:
                    mech.set_physics_enabled(True)
                    mech.set_damping(1.0)
                    mech.set_restitution(0.0)
                except Exception:
                    pass
            scene.add_actor(actor)
            _t.sleep(0.3)
            logger.info("[SceneComposer] 整体房间盒子已创建: %.1f×%.1f×%.1f m",
                        width, depth, height)
        except Exception as e:
            logger.warning("[SceneComposer] 房间盒子创建失败: %s", e)

    def _run_original_workflow(self, prompt: str, resolved: List[Dict[str, Any]],
                               all_items: List[Dict[str, Any]],
                               do_import: bool) -> Dict[str, Any]:
        """调用原 scene_composition_workflow 节点完成布局+导入。"""

        # 室内场景框架：先放置房间盒子（地板+4墙），再往里面摆物体
        if self._detect_scene_indoor(prompt):
            self._generate_room_box()

        extracted = len(all_items)
        model_count = len(resolved)
        placement_items = self._build_placement_items(resolved)

        asset_meta = {}
        try:
            from ..flows.scene_composition_workflow_v2.asset_metadata import (
                build_asset_metadata_batch,
            )
            paths = [it["model_path"] for it in resolved if it.get("model_path")]
            asset_meta = build_asset_metadata_batch(paths)
        except Exception as e:
            logger.warning("[SceneComposer] asset_metadata 构建失败（忽略）: %s", e)

        state: Dict[str, Any] = {
            "prompt": prompt[:1500],
            "metadata": {"scene_name": self.scene_name, "room_size": self.room_size},
            "intermediate": {
                "placement_items": placement_items,
                "scene_name": self.scene_name,
                "asset_metadata": asset_meta,
                "total_models": extracted, "valid_models": model_count,
            },
        }

        scene_path = ""
        actors: List[Dict[str, Any]] = []
        try:
            from ..flows.scene_composition_workflow.compose_scene import compose_scene_node
            logger.info("[SceneComposer] 调用原 compose_scene_node...")
            out = compose_scene_node(state)
            if out.get("error"):
                logger.warning("[SceneComposer] compose_scene 失败: %s", out["error"])
                return {"items": resolved, "imported": [],
                        "failed": [it["name"] for it in resolved],
                        "extracted_count": extracted, "model_count": model_count,
                        "error": f"布局失败: {out['error']}"}
            inter = out.get("intermediate", {})
            scene_path = inter.get("scene_json_path", "")
            actors = inter.get("scene_actors", [])
            state["intermediate"].update(inter)
            logger.info("[SceneComposer] compose_scene 完成: %d actors", len(actors))
        except Exception as e:
            logger.exception("[SceneComposer] compose_scene 异常: %s", e)
            return {"items": resolved, "imported": [],
                    "failed": [it["name"] for it in resolved],
                    "extracted_count": extracted, "model_count": model_count,
                    "error": f"布局异常: {e}"}

        imported: List[str] = []
        failed: List[str] = []
        if do_import:
            try:
                from ..flows.scene_composition_workflow.import_to_engine import (
                    import_to_engine_node,
                )
                logger.info("[SceneComposer] 调用原 import_to_engine_node...")
                imp_out = import_to_engine_node(state)
                imp_inter = imp_out.get("intermediate", {})
                imported = [a.get("name", "?") for a in imp_inter.get("imported_actors", [])]
                failed = [a.get("name", "?") for a in imp_inter.get("failed_actors", [])]
                logger.info("[SceneComposer] import 完成: 成功 %d, 失败 %d",
                            len(imported), len(failed))

                # 受控物理沉降：回设原位 → 极短暂开物理(消重叠) → 立即关掉
                # 避免完全关物理导致穿模，也避免物理开着导致物体弹飞
                if imported and actors:
                    import time as _t
                    try:
                        from CoronaCore.core.managers import scene_manager as _sm
                        scene = _sm.get("")
                        if scene is None:
                            routes = _sm.list_all()
                            scene = _sm.get(routes[0]) if routes else None

                        # 构建 actor name → 原始 geometry
                        geo_map = {a.get("name") or a.get("source_name", ""): a.get("geometry", {})
                                   for a in actors if a.get("geometry")}

                        # 第一阶段：全关物理 + 回设原位
                        mecha = []
                        for actor_name in imported:
                            actor = scene.find_actor(actor_name) if scene else None
                            if actor is None:
                                continue
                            mech = getattr(actor, "_mechanics", None)
                            if mech is not None:
                                try:
                                    mech.set_physics_enabled(False)
                                    mech.set_damping(0.98)       # 超高阻尼
                                    mech.set_restitution(0.0)    # 零弹性
                                    mecha.append((actor, mech))
                                except Exception:
                                    pass
                            # 回设原始位置
                            geo = geo_map.get(actor_name, {})
                            if geo.get("pos"):
                                actor.set_position(geo["pos"])
                            if geo.get("rot"):
                                actor.set_rotation(geo["rot"])
                            if geo.get("scale"):
                                actor.set_scale(geo["scale"])
                        logger.info("[SceneComposer] 位置回设完成: %d 个物体", len(mecha))

                        # 第二阶段：短暂开物理，仅消重叠
                        if mecha:
                            for _actor, mech in mecha:
                                try:
                                    mech.set_physics_enabled(True)
                                except Exception:
                                    pass
                            _t.sleep(0.6)  # 够消重叠，不够弹飞
                            for _actor, mech in mecha:
                                try:
                                    mech.set_physics_enabled(False)
                                except Exception:
                                    pass

                        # 第三阶段：位置钳制——把跑出盒子外的物体强制拉回
                        w, d, h = self.room_size[0], self.room_size[1], self.room_size[2]
                        hw, hd = w / 2.0, d / 2.0
                        margin = 0.15  # 离边界留一点空隙，避免嵌进墙里
                        clamped = 0
                        for actor_name in imported:
                            actor = scene.find_actor(actor_name) if scene else None
                            if actor is None:
                                continue
                            x, y, z = actor.get_position()
                            changed = False
                            if x < -hw + margin:
                                x = -hw + margin; changed = True
                            elif x > hw - margin:
                                x = hw - margin; changed = True
                            if y < margin:
                                y = margin; changed = True
                            elif y > h - margin:
                                y = h - margin; changed = True
                            if z < -hd + margin:
                                z = -hd + margin; changed = True
                            elif z > hd - margin:
                                z = hd - margin; changed = True
                            if changed:
                                actor.set_position([x, y, z])
                                clamped += 1

                        # 第四阶段：地面整平——所有落地物体底部贴地、不倾斜
                        leveled = 0
                        for actor_name in imported:
                            actor = scene.find_actor(actor_name) if scene else None
                            if actor is None:
                                continue
                            # 获取当前位姿
                            x, y, z = actor.get_position()
                            rx, ry, rz = actor.get_rotation()
                            changed = False
                            # 用 AABB 高度把底部拉到 Y=0
                            aabb_h = self._get_object_height(actor_name, asset_meta, geo_map)
                            if aabb_h > 0 and abs(y - aabb_h / 2.0) > 0.02:
                                y = aabb_h / 2.0  # 底部贴地
                                changed = True
                            elif y < margin:
                                y = margin; changed = True
                            # 只保留绕 Y 的旋转（水平方向），归零 X/Z 倾斜
                            if abs(rx) > 0.01 or abs(rz) > 0.01:
                                rx, rz = 0.0, 0.0
                                changed = True
                            if changed:
                                actor.set_position([x, y, z])
                                actor.set_rotation([rx, ry, rz])
                                leveled += 1

                        # 第五阶段：整平+钳制后，最后来一次物理消穿模
                        if clamped > 0 or leveled > 0:
                            if leveled:
                                logger.info("[SceneComposer] 地面整平 %d 个物体", leveled)
                            for _actor, mech in mecha:
                                try:
                                    mech.set_physics_enabled(True)
                                except Exception:
                                    pass
                            _t.sleep(0.35)
                            for _actor, mech in mecha:
                                try:
                                    mech.set_physics_enabled(False)
                                except Exception:
                                    pass

                        logger.info("[SceneComposer] 受控沉降+钳制+整平完成: %d 个物体", len(mecha))
                    except Exception as e:
                        logger.warning("[SceneComposer] 受控沉降失败（忽略）: %s", e)
            except Exception as e:
                logger.exception("[SceneComposer] import_to_engine 异常: %s", e)
                failed = [it["name"] for it in resolved]

        return {
            "items": resolved, "imported": imported, "failed": failed,
            "extracted_count": extracted, "model_count": model_count,
            "scene_path": scene_path, "error": None,
        }


__all__ = ["SceneComposer", "is_compose_request"]


