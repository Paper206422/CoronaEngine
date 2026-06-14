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


def _build_room_box_obj(width: float, height: float, depth: float,
                        door: Optional[Dict[str, float]] = None) -> str:
    """构建房间盒子 OBJ 字符串（单位立方体，缩放由 Actor 完成）。

    M2 步骤 14b-i：纯函数，可离线几何验证（共面 + 法向内向）。
    - door=None  → 闭合六面盒子（与旧 _generate_room_box 几何完全一致，零损失）
    - door={width, height} → 前墙(z=+0.5)拆成左柱+右柱+门楣，包住一个落地门洞，
      camera 可从门洞走进去。门洞横向居中、底边贴地。

    单位立方体边长 1（中心原点），door 尺寸以"米"给出，按 width/height 归一化到
    单位坐标。所有面法向指向盒内（背面剔除后摄像机能看进内部）。
    """
    # 8 基础顶点 + 6 法向（与旧表一致）
    head = (
        "mtllib box.mtl\nusemtl wall\n"
        "# 8 vertices of a 1x1x1 cube centered at origin\n"
        "v -0.5 -0.5 -0.5\nv  0.5 -0.5 -0.5\nv  0.5  0.5 -0.5\nv -0.5  0.5 -0.5\n"
        "v -0.5 -0.5  0.5\nv  0.5 -0.5  0.5\nv  0.5  0.5  0.5\nv -0.5  0.5  0.5\n"
        "vn  0.0  0.0 -1.0\nvn  1.0  0.0  0.0\nvn  0.0  0.0  1.0\nvn -1.0  0.0  0.0\n"
        "vn  0.0  1.0  0.0\nvn  0.0 -1.0  0.0\n"
    )
    # 背/左/右/底/顶 5 面（门洞只改前墙，这 5 面恒定，法向内向）
    common_faces = (
        "f 1//3 2//3 3//3 4//3\n"   # back   z=-0.5 inward +Z
        "f 1//2 4//2 8//2 5//2\n"   # left   x=-0.5 inward +X
        "f 2//4 6//4 7//4 3//4\n"   # right  x=+0.5 inward -X
        "f 1//5 5//5 6//5 2//5\n"   # bottom y=-0.5 inward +Y
        "f 4//6 3//6 7//6 8//6\n"   # top    y=+0.5 inward -Y
    )

    if not door:
        # 闭合：前墙整面一块（与旧表完全一致）
        front = "f 5//1 8//1 7//1 6//1\n"   # front z=+0.5 inward -Z
        return head + (
            "# 6 faces (quads): each is a planar quad, normals inward.\n"
            "# verified by cross-product: 4 coplanar verts + inward normal.\n"
        ) + common_faces + front

    # 门洞：归一化到单位坐标，横向居中、底边贴地，留 5% 余量防止退化
    dw = max(0.05, min(0.9, float(door.get("width", 1.0)) / width))
    dh = max(0.05, min(0.9, float(door.get("height", 2.0)) / height))
    dl = -dw / 2.0          # door left  x
    dr = dw / 2.0           # door right x
    dt = -0.5 + dh          # door top   y（底边在 y=-0.5 地面）
    # 前墙新增 6 顶点（z=+0.5）：v9..v14
    extra_v = (
        "# front-wall door frame verts (z=+0.5)\n"
        f"v {dl:.4f} -0.5 0.5\n"    # v9  door bottom-left
        f"v {dr:.4f} -0.5 0.5\n"    # v10 door bottom-right
        f"v {dr:.4f} {dt:.4f} 0.5\n"  # v11 door top-right
        f"v {dl:.4f} {dt:.4f} 0.5\n"  # v12 door top-left
        f"v {dl:.4f} 0.5 0.5\n"     # v13 wall-top at door-left x
        f"v {dr:.4f} 0.5 0.5\n"     # v14 wall-top at door-right x
    )
    # 前墙拆 3 块（全在 z=+0.5，法向 -Z 内向，缠绕 bl->tl->tr->br）
    front_frame = (
        "# front wall as frame around door hole (normal -Z inward)\n"
        "f 5//1 8//1 13//1 9//1\n"     # left strip   x in [-0.5, dl]
        "f 10//1 14//1 7//1 6//1\n"    # right strip  x in [dr, 0.5]
        "f 12//1 13//1 14//1 11//1\n"  # top lintel   y in [dt, 0.5]
    )
    return head + extra_v + (
        "# walls: back/left/right/bottom/top + front-frame (door hole).\n"
    ) + common_faces + front_frame


def _build_floor_obj(mtl_lib: str = "grass.mtl", mtl_name: str = "grass") -> str:
    """构建一块朝上的地面 quad（单位 1×1，XZ 平面，缩放由 Actor 完成）。

    M2 步骤 14b-ii：enclosure=terrain 的最简实现——一片平地，无墙无顶。
    M2 步骤 15c：引用独立 grass.mtl（草地绿），不再借用 box 的灰墙材质。
    M2 步骤 15b：材质参数化（mtl_lib/mtl_name），terrain 用草地、shell 内皮用地毯，共用此几何。
    法向 +Y（朝上），camera 站在上面。Actor 缩放成 [w, 1, d]、置于 y=0。
    """
    return (
        f"mtllib {mtl_lib}\nusemtl {mtl_name}\n"
        "# unit floor quad in XZ plane, normal +Y (up)\n"
        "v -0.5 0.0 -0.5\nv  0.5 0.0 -0.5\nv  0.5 0.0  0.5\nv -0.5 0.0  0.5\n"
        "vn  0.0  1.0  0.0\n"
        "f 1//1 4//1 3//1 2//1\n"   # top face, CCW from above → normal +Y up
    )


# M2 步骤 14b-ii：把任意场景描述分解成一棵 Zone 树。开放性在这一步——
# LLM 读 prompt 成空间结构，代码不枚举场景类型（不写 if 教堂/if 蒙古包）。
# 退化：纯室内 → 返回单 box（走旧路径，零回归）；只有真·室内外混合才建两层树。
_ZONE_DECOMPOSE_SYSTEM_PROMPT = """你是空间场景分解器。把用户的场景描述分解成一棵"空间区域(Zone)树"。
不要枚举场景类型，只忠实描述空间结构。

输出 JSON：
{
  "zones": [
    {
      "id": "z0",
      "name": "区域名(中文)",
      "role": "outdoor" | "indoor",
      "enclosure": "terrain" | "box" | "shell",
      "shell_asset": null | "建筑模型名(中文)",
      "size": [宽, 深, 高],
      "parent": null | "父zone的id",
      "has_door": true | false
    }
  ]
}

字段说明：
- enclosure:
  * terrain = 开放平地(无墙无顶)
  * box = 合成的中性盒子(客厅/卧室/教堂内部这种"房间"，没有特定外观的建筑模型，由墙地顶围合)
  * shell = 由一个生成的建筑模型包裹(蒙古包/帐篷/小木屋这种有标志性外观的建筑，模型本身就是外壳)
- shell_asset: 仅当 enclosure=shell 时填，是那个建筑模型的名字(如"蒙古包")；其它情况填 null
- size: 单位米 [宽, 深, 高]; terrain 的高填 0
- parent: 顶层 zone 填 null; 嵌套在某区域内填父 zone 的 id
- has_door: box 是否朝父区域开门洞(仅 box 有意义; shell 用模型自带入口, terrain 无, 都填 false)

规则：
- 纯室内房间（客厅/卧室/办公室/教堂内部）→ 1 个 box，role=indoor，parent=null，has_door=false，shell_asset=null。
- 室内外混合且内层是【标志性外观建筑】（草原上的蒙古包 / 院子里的小木屋 / 雪地里的帐篷）→ 2 个：
  外层 terrain(role=outdoor, parent=null) + 内层 shell(role=indoor, parent=外层id, shell_asset="建筑名", has_door=false)。
- 室内外混合但内层只是【普通房间】（院子里的一间客厅）→ 外层 terrain + 内层 box(has_door=true)。
- 纯室外（一片草原 / 广场，无可进入建筑）→ 1 个 terrain，role=outdoor，parent=null。
- 最多 2 层。内层(box/shell)是"人活动空间"(宽深 4~6 米、高 2.5~3 米)；外层 terrain 一大片(15~25 米)。
只输出 JSON，不要解释。"""



# 触发场景组合的关键词
_COMPOSE_PATTERNS = [
    r"物品清单", r"清单", r"组合(?:场景|这个|整个)", r"布置(?:整个|这个|好这)",
    r"根据.{0,10}(?:方案|清单|设计|效果图).{0,6}(?:生成|布置|组合|搭建)",
    r"按.{0,8}清单",
    r"把.{0,10}(?:都|全部|所有).{0,6}(?:生成|放|布置|导入)",
    r"一键(?:生成|布置|组合)",
    # 直接生成类：'生成欧式卧室' / '生成一个现代客厅' 等
    r"生成.{0,9}(?:卧室|客厅|厨房|书房|房间|浴室|场景|办公室|餐厅)",
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
- 控制在 9 个以内，只保留最重要的大件
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
                 max_items: int = DEFAULT_MAX_ITEMS, zone_tree=None) -> None:
        self.room_size = room_size or [5.0, 3.0, 3.0]
        self.scene_name = scene_name
        self.max_items = max(1, int(max_items))
        self._provider = None
        # M2 步骤 14a：ZoneTree（可选）。为 None 时退化成单 Zone + enclosure=box，
        # 几何与旧 room_size 逻辑完全一致，零功能损失。
        self.zone_tree = zone_tree

    def _get_room_zone(self):
        """返回用于"物体布局"的 Zone（物体摆进它的体积里）。

        无 zone_tree 时按 room_size 构造默认单 Zone（退化形态）。
        有 zone_tree 时返回第一个 indoor/box/shell Zone（物体进室内），无则 root。
        注意：indoor 盒子恒在原点（center=[0,h/2,0]），所以现有"原点布局 + room_size"
        逻辑无需改动就落在盒内——这是 14b-ii 不动布局代码的关键。
        """
        if self.zone_tree is not None and self.zone_tree.root is not None:
            for z in self.zone_tree.list_all_zones():
                if (z.enclosure or "") in ("box", "shell") or z.role == "indoor":
                    return z
            return self.zone_tree.root
        # 退化：构造默认单 Zone（center/size 与旧 _generate_room_box 完全一致）
        from ..data_model.zone_tree import Zone, Volume
        w, d, h = self.room_size[0], self.room_size[1], self.room_size[2]
        return Zone(
            zone_id="zone_root",
            name=self.scene_name,
            role="indoor",
            volume=Volume(center=[0.0, h / 2.0, 0.0], size=[w, d, h]),
            enclosure="box",
        )

    def decompose_zone_tree(self, text: str):
        """M2 步骤 14b-ii：把场景描述分解成 ZoneTree。开放性在这一步（LLM 读结构）。

        返回 ZoneTree 或 None：
        - None → 纯室内单房间（走旧 _generate_room_box 单盒路径，零回归）
        - ZoneTree → 真·室内外混合（terrain + box + 门洞）或纯室外（单 terrain）

        代码不枚举场景类型——分解判断全在 LLM，本函数只把 LLM 输出实例化成树。
        失败/格式错误 → 返回 None（保守退化到单盒，不影响主链路）。
        """
        zones_spec = self._llm_decompose(text)
        if not zones_spec:
            return None
        try:
            tree = self._build_zone_tree(zones_spec)
        except Exception as e:
            logger.warning("[SceneComposer] ZoneTree 构建失败，退化单盒: %s", e)
            return None
        if tree is None:
            return None
        # 纯单室内盒（1 个 box、无 terrain、无门洞）→ 等价旧路径，返回 None 省一层
        zones = tree.list_all_zones()
        if len(zones) == 1 and zones[0].enclosure == "box" and not zones[0].connectors:
            return None
        logger.info("[SceneComposer] 场景分解为 %d 个 Zone: %s",
                    len(zones), [f"{z.name}({z.enclosure})" for z in zones])
        return tree

    def _llm_decompose(self, text: str) -> List[Dict[str, Any]]:
        """调 LLM 把场景拆成 zones 列表。失败返回 []。"""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
        from Quasar.ai_models.base_pool.registry import get_chat_model
        from langchain_core.messages import HumanMessage, SystemMessage

        def _call():
            llm = get_chat_model(temperature=0, request_timeout=60.0)
            return llm.invoke([
                SystemMessage(content=_ZONE_DECOMPOSE_SYSTEM_PROMPT),
                HumanMessage(content=text[:2000]),
            ])

        try:
            ex = ThreadPoolExecutor(max_workers=1)
            fut = ex.submit(_call)
            try:
                resp = fut.result(timeout=65.0)
            except FTimeout:
                ex.shutdown(wait=False, cancel_futures=True)
                logger.warning("[SceneComposer] Zone 分解超时，退化单盒")
                return []
            finally:
                ex.shutdown(wait=False)

            raw = (resp.content if hasattr(resp, "content") else str(resp)).strip()
            if "```" in raw:
                s = raw.find("{"); e = raw.rfind("}")
                if s != -1 and e != -1:
                    raw = raw[s:e + 1]
            data = json.loads(raw)
            zones = data.get("zones") if isinstance(data, dict) else None
            return zones if isinstance(zones, list) else []
        except Exception as e:
            logger.warning("[SceneComposer] Zone 分解失败，退化单盒: %s", e)
            return []

    def _build_zone_tree(self, zones_spec: List[Dict[str, Any]]):
        """把 LLM 的 zones 列表实例化成 ZoneTree。

        坐标约定（14b-ii 不动布局代码的关键）：
        - indoor box/shell 恒置原点 → 现有"原点布局"逻辑无需改动就落在体积内。
        - outdoor terrain 也置原点（一大片，内层嵌在中间）。
        - box 朝父 terrain 开门洞（has_door）→ 写进 connector，_generate_room_box 读它。
        - shell（15a）：用生成的建筑模型当围合体，模型自带入口，不开矩形门洞、不生成白盒。
        """
        from ..data_model.zone_tree import Zone, ZoneTree, Volume, Connector

        if not zones_spec:
            return None

        nodes: Dict[str, Zone] = {}
        order: List[str] = []
        for i, spec in enumerate(zones_spec[:2]):  # 最多两层
            zid = str(spec.get("id") or f"z{i}")
            enclosure = spec.get("enclosure") or "box"
            if enclosure not in ("box", "terrain", "shell"):
                enclosure = "box"
            role = spec.get("role") or ("outdoor" if enclosure == "terrain" else "indoor")
            size = spec.get("size") or ([20.0, 20.0, 0.0] if enclosure == "terrain"
                                        else list(self.room_size))
            try:
                w, d, h = float(size[0]), float(size[1]), float(size[2] if len(size) > 2 else 0.0)
            except Exception:
                w, d, h = (20.0, 20.0, 0.0) if enclosure == "terrain" else tuple(self.room_size)
            center = [0.0, h / 2.0 if enclosure in ("box", "shell") else 0.0, 0.0]
            zone = Zone(
                zone_id=zid, name=str(spec.get("name") or zid),
                role=role, enclosure=enclosure,
                volume=Volume(center=center, size=[w, d, h]),
            )
            # 15a：shell 记主外壳 asset 名（建筑模型），由 _place_shell 确定性包裹体积
            if enclosure == "shell":
                shell_name = (spec.get("shell_asset") or spec.get("name") or "").strip()
                zone.primary_shell_asset_id = shell_name or None
            zone.metadata["has_door"] = bool(spec.get("has_door"))
            zone.metadata["parent"] = spec.get("parent")
            nodes[zid] = zone
            order.append(zid)

        # 挂树 + 门洞（仅 box；shell 用模型自带入口）
        root = None
        for zid in order:
            z = nodes[zid]
            parent_id = z.metadata.get("parent")
            if parent_id and parent_id in nodes and parent_id != zid:
                nodes[parent_id].sub_zones.append(z)
                # box 朝父开门洞：宽 = min(房宽*0.5, 1.2)，高 = min(房高*0.8, 2.2)
                if z.enclosure == "box" and z.metadata.get("has_door"):
                    dw = min(z.volume.size[0] * 0.5, 1.2)
                    dh = min((z.volume.size[2] or 2.5) * 0.8, 2.2)
                    z.connectors.append(Connector(
                        connector_id=f"door_{zid}", type="door",
                        position=[0.0, 0.0, z.volume.size[1] / 2.0],
                        size=[dw, dh], target_zone_id=zid,
                    ))
            else:
                if root is None:
                    root = z
        if root is None:
            root = nodes[order[0]]
        return ZoneTree(root=root)

    def _collect_shell_assets(self) -> set:
        """15a：从 zone_tree 收集所有 shell zone 的主外壳 asset 名（用于从家具清单剔除）。"""
        names = set()
        if self.zone_tree is None or self.zone_tree.root is None:
            return names
        for z in self.zone_tree.list_all_zones():
            if (z.enclosure or "") == "shell" and z.primary_shell_asset_id:
                names.add(z.primary_shell_asset_id.strip())
        return names

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
        # extract 是推理任务（自然语言→结构化清单），与布局同级，超时不应比布局短。
        # request_timeout 30→90（布局是 120~180），future timeout 必须 > request_timeout。
        # 超时/空结果重试 1 次：它是 compose 的第一步，单点 API 抖动不该让整链失败。
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
        from Quasar.ai_models.base_pool.registry import get_chat_model
        from langchain_core.messages import HumanMessage, SystemMessage

        def _call():
            llm = get_chat_model(temperature=0, request_timeout=90.0)
            return llm.invoke([
                SystemMessage(content=_EXTRACT_SYSTEM_PROMPT),
                HumanMessage(content=text[:2000]),
            ])

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            try:
                ex = ThreadPoolExecutor(max_workers=1)
                fut = ex.submit(_call)
                try:
                    resp = fut.result(timeout=95.0)
                except FTimeout:
                    ex.shutdown(wait=False, cancel_futures=True)
                    logger.warning("[SceneComposer] LLM 提取超时 (第 %d/%d 次)%s",
                                   attempt, max_attempts,
                                   "，重试" if attempt < max_attempts else "，放弃")
                    continue
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
                if attempt > 1:
                    logger.info("[SceneComposer] LLM 提取第 %d 次重试成功", attempt)
                return items
            except Exception as e:
                logger.warning("[SceneComposer] LLM 提取失败 (第 %d/%d 次): %s%s",
                               attempt, max_attempts, e,
                               "，重试" if attempt < max_attempts else "，放弃")
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
        # 强化 prompt 避免不同物品生成相似图片 → 模型检索混淆
        approved = []
        for it in items:
            name = it["name"]
            kw = (it.get("keywords") or "").strip()
            # 用英文前缀 + 物品名构建区分度更高的 prompt
            prompt = (kw if kw and len(kw) > 6
                      else f"high quality 3D model of {name}, standalone, white background, "
                           f"photorealistic, product photography, {name}")
            approved.append({
                "item_name": name,
                "image_prompt": prompt,
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
                do_import: bool = True,
                do_review: bool = False) -> Dict[str, Any]:
        """完整场景组合: 提取清单 → 获取模型 → 审查 → 布局+导入。

        三阶段:
          1. generate_all  — 纯 API 调用, 并行, 不碰引擎
          2. review_queue  — 串行, 逐个导入→截屏→VLM→修正→卸载
          3. compose       — LLM 布局 (注入审查结果) → 批量导入 → 物理沉降
        """
        logger.info("[SceneComposer] ====== 开始场景组合 (三阶段) ======")
        items = self.extract_items(text)
        if not items:
            return {"items": [], "imported": [], "failed": [],
                    "extracted_count": 0, "model_count": 0,
                    "error": "未能从描述中提取出物体清单"}

        # ── Phase 0: 场景空间分解（开放性在这一步，LLM 读结构）──
        # 纯室内单房间 → None（走旧单盒路径）；真·室内外混合 → ZoneTree。
        # 放在截断前：shell 建筑要从家具清单分离 + 保护不被截断（它是场景主体）。
        if self.zone_tree is None:
            try:
                self.zone_tree = self.decompose_zone_tree(text)
            except Exception as e:
                logger.warning("[SceneComposer] 场景分解异常，退化单盒: %s", e)
                self.zone_tree = None
        # 关键：建树后把 room_size 同步成 indoor box/shell 的真实体积。下游布局 prompt 与
        # 导入后钳制都读 self.room_size——同步后它们自动按真实体积工作，无需改布局代码。
        if self.zone_tree is not None:
            box = self._get_room_zone()
            if box is not None and getattr(box, "enclosure", "") in ("box", "shell"):
                self.room_size = list(box.volume.size)
                logger.info("[SceneComposer] room_size 同步为 indoor 体积: %s",
                            self.room_size)

        # 15a：shell 建筑（如蒙古包）当围合体不是家具。确保它在生成清单里（缺则补）。
        shell_names = self._collect_shell_assets()
        for sname in shell_names:
            if not any((it.get("name") or "").strip() == sname for it in items):
                items.insert(0, {"name": sname, "quantity": 1,
                                 "keywords": f"{sname}, building exterior, architectural model"})

        extracted_total = len(items)
        truncated = 0
        if extracted_total > self.max_items:
            # 截断保护 shell 名：先留 shell，再用家具填满剩余额度
            shells_kept = [it for it in items if (it.get("name") or "").strip() in shell_names]
            furniture = [it for it in items if (it.get("name") or "").strip() not in shell_names]
            keep_furniture = max(0, self.max_items - len(shells_kept))
            items = shells_kept + furniture[:keep_furniture]
            truncated = extracted_total - len(items)
            logger.info("[SceneComposer] 物体数 %d 超过上限 %d，截断为 %d（保 shell %d，丢 %d）",
                        extracted_total, self.max_items, len(items), len(shells_kept), truncated)

        # ── Phase 1: generate_all (并行, 纯 API) ──
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

        # ── Phase 2: review_queue (串行, 全局锁保护) ──
        reviews: List[Dict[str, Any]] = []
        if do_review:
            reviews = self._review_models(resolved)
            logger.info("[SceneComposer] 审查完成: %d/%d", len(reviews), len(resolved))

        # ── Phase 3: compose (布局 + 导入, 注入审查结果) ──
        # 15a：shell 建筑从家具里分出来——它走确定性围合放置（_place_shells），
        # 绝不进布局 LLM（否则又被当家具摆中心，与白盒/terrain 双围合撕裂）。
        shell_names = self._collect_shell_assets()
        shell_models = [m for m in resolved
                        if (m.get("name") or "").strip() in shell_names]
        furniture = [m for m in resolved
                     if (m.get("name") or "").strip() not in shell_names]
        if shell_models:
            self._shell_models = shell_models
            logger.info("[SceneComposer] 分离出 %d 个外壳建筑（确定性放置，不进布局LLM）: %s",
                        len(shell_models), [m.get("name") for m in shell_models])

        # 15a：记录哪些 shell 被 decompose 识别出来了（即便模型生成失败也要汇报）。
        # shell_expected = 应该有的外壳；shell_models = 模型生成成功、待放置的外壳。
        shell_failed_gen = sorted(shell_names - {(m.get("name") or "").strip()
                                                 for m in shell_models})

        result = self._run_original_workflow(text, furniture, items, do_import,
                                              reviews=reviews)
        result["extracted_count"] = extracted_total
        result["truncated"] = truncated
        result["reviews"] = reviews
        # shell 汇报：放置成功/失败（_place_shells 写的）+ 模型生成就失败的
        shell_report = getattr(self, "_shell_report", {"placed": [], "failed": []})
        result["shell_placed"] = shell_report.get("placed", [])
        result["shell_failed"] = (shell_report.get("failed", [])
                                  + [f"{n}: 模型生成失败" for n in shell_failed_gen])
        result["shell_expected"] = sorted(shell_names)
        return result

    def _review_models(self, resolved: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Phase 2: 串行审查队列 — 逐个导入 → 截图 → VLM → 修正 → 卸载。

        全局锁保护, 同一时刻只审查一个模型, 避免截屏竞态死锁。
        """
        reviews: List[Dict[str, Any]] = []
        try:
            from .model_reviewer import review_single_model
        except ImportError:
            logger.warning("[SceneComposer] model_reviewer 不可用, 跳过审查")
            return reviews

        total = len(resolved)
        for i, item in enumerate(resolved, 1):
            name = item.get("name", "?")
            path = item.get("model_path", "")
            if not path:
                logger.warning("[SceneComposer] review %d/%d %s: 无模型路径, 跳过", i, total, name)
                continue

            logger.info("[SceneComposer] review %d/%d: %s", i, total, name)
            review = review_single_model(
                model_path=path,
                model_name=name,
                model_type=item.get("object_id", name),
            )
            reviews.append(review)

        return reviews

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

        # M2 步骤 14a：尺寸从根 Zone 的 Volume 读（退化时等价于旧 room_size）。
        zone = self._get_room_zone()
        width, depth, height = zone.volume.size[0], zone.volume.size[1], zone.volume.size[2]

        # 1. 生成空心盒子 OBJ（六面体，面法向内）
        tmp_dir = _os.path.join(_tf.gettempdir(), "corona_room_box")
        _os.makedirs(tmp_dir, exist_ok=True)
        mtl_path = _os.path.join(tmp_dir, "box.mtl")
        obj_path = _os.path.join(tmp_dir, "box.obj")
        with open(mtl_path, "w", encoding="ascii") as f:
            f.write("newmtl wall\nKa 0.85 0.85 0.85\nKd 0.92 0.92 0.92\n"
                    "Ks 0.0 0.0 0.0\nNs 0.0\nd 1.0\n")
        # M2 步骤 14b-i：OBJ 由纯函数生成（支持门洞）。门洞从根 Zone 的首个
        # connector 读；当前无 Zone 声明门洞 → door=None → 闭合盒子（与现状一致）。
        door = None
        if zone.connectors:
            c = zone.connectors[0]
            sz = getattr(c, "size", None)
            if sz and len(sz) >= 2:
                door = {"width": sz[0], "height": sz[1]}
        obj_text = _build_room_box_obj(width, height, depth, door=door)
        with open(obj_path, "w", encoding="ascii") as f:
            f.write(obj_text)

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
            # 盒子作为静态碰撞体：不参与物理运动，只挡住内部物体
            mech = getattr(actor, "_mechanics", None)
            if mech is not None:
                try:
                    mech.set_physics_enabled(False)
                except Exception:
                    pass
            scene.add_actor(actor)
            _t.sleep(0.3)
            logger.info("[SceneComposer] 整体房间盒子已创建: %.1f×%.1f×%.1f m",
                        width, depth, height)
        except Exception as e:
            logger.warning("[SceneComposer] 房间盒子创建失败: %s", e)

    def _generate_terrain(self, zone) -> None:
        """M2 步骤 14b-ii：为 enclosure=terrain 的 Zone 生成一块平地（无墙无顶）。

        镜像 _generate_room_box 的 Actor 套路：单 quad OBJ + 静态碰撞体。
        terrain 置原点、铺在 y=0，盒子嵌在它中间——camera 站在地上看到一大片。
        """
        import os as _os, tempfile as _tf, time as _t

        size = zone.volume.size
        width = size[0] if len(size) > 0 else 20.0
        depth = size[1] if len(size) > 1 else 20.0

        tmp_dir = _os.path.join(_tf.gettempdir(), "corona_room_box")
        _os.makedirs(tmp_dir, exist_ok=True)
        grass_mtl_path = _os.path.join(tmp_dir, "grass.mtl")
        floor_path = _os.path.join(tmp_dir, "floor.obj")
        # 15c：草地绿材质（不透明）。Kd 偏黄绿，Ka 略暗——比中性灰更像草原。
        with open(grass_mtl_path, "w", encoding="ascii") as f:
            f.write("newmtl grass\nKa 0.20 0.32 0.12\nKd 0.36 0.55 0.22\n"
                    "Ks 0.02 0.02 0.02\nNs 4.0\nd 1.0\n")
        with open(floor_path, "w", encoding="ascii") as f:
            f.write(_build_floor_obj())

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
        if "__room_terrain" in existing:
            return

        try:
            actor = Actor(name="__room_terrain", route=floor_path, actor_type="mesh",
                          parent_scene=scene)
            actor.set_position([0.0, 0.0, 0.0], True)
            actor.set_scale([width, 1.0, depth], True)
            mech = getattr(actor, "_mechanics", None)
            if mech is not None:
                try:
                    mech.set_physics_enabled(False)
                except Exception:
                    pass
            scene.add_actor(actor)
            _t.sleep(0.3)
            logger.info("[SceneComposer] 地面(terrain)已创建: %.1f×%.1f m", width, depth)
        except Exception as e:
            logger.warning("[SceneComposer] 地面创建失败: %s", e)

    def _generate_interior_floor(self, zone) -> None:
        """M2 步骤 15b：为 shell zone 铺一块内皮地面（interior_skin 的 floor 取值）。

        shell 建筑模型（蒙古包）是实心外观团块，没有可用内表面——进去后地面是黑的、
        物体悬空（F5 截图2）。这里按 volume 程序生成一块地面（地毯），不靠外壳内表面。
        关键：内嵌（比 volume 略小 INSCRIBE 倍），避免方地面四角戳穿圆壳墙体。
        墙/顶暂不补（外壳从内侧已挡住大部分视线）；interior_skin 的 wall/ceiling 后续可扩。
        """
        import os as _os, tempfile as _tf, time as _t

        size = zone.volume.size
        width = size[0] if len(size) > 0 else 4.0
        depth = size[1] if len(size) > 1 else 4.0
        INSCRIBE = 0.85  # 内嵌：方地面边长取 volume 的 0.85，四角不戳穿圆壳

        # interior_skin 参数化材质（默认地毯暖色；zone.interior_skin 可覆盖）
        floor_mat = "carpet"
        skin = getattr(zone, "interior_skin", None)
        if skin is not None and getattr(skin, "floor_material", None):
            floor_mat = str(skin.floor_material)

        tmp_dir = _os.path.join(_tf.gettempdir(), "corona_room_box")
        _os.makedirs(tmp_dir, exist_ok=True)
        carpet_mtl_path = _os.path.join(tmp_dir, "carpet.mtl")
        carpet_obj_path = _os.path.join(tmp_dir, "carpet.obj")
        # 地毯暖色（红棕），不透明
        with open(carpet_mtl_path, "w", encoding="ascii") as f:
            f.write(f"newmtl {floor_mat}\nKa 0.20 0.10 0.08\nKd 0.55 0.28 0.20\n"
                    "Ks 0.02 0.02 0.02\nNs 6.0\nd 1.0\n")
        with open(carpet_obj_path, "w", encoding="ascii") as f:
            f.write(_build_floor_obj(mtl_lib="carpet.mtl", mtl_name=floor_mat))

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
        if "__interior_floor" in existing:
            return

        try:
            actor = Actor(name="__interior_floor", route=carpet_obj_path,
                          actor_type="mesh", parent_scene=scene)
            # 略抬 1cm 压在 terrain 之上，避免与地面 z-fighting
            actor.set_position([0.0, 0.01, 0.0], True)
            actor.set_scale([width * INSCRIBE, 1.0, depth * INSCRIBE], True)
            mech = getattr(actor, "_mechanics", None)
            if mech is not None:
                try:
                    mech.set_physics_enabled(False)
                except Exception:
                    pass
            scene.add_actor(actor)
            _t.sleep(0.3)
            logger.info("[SceneComposer] 内皮地面已铺设: %.1f×%.1f m (材质=%s)",
                        width * INSCRIBE, depth * INSCRIBE, floor_mat)
        except Exception as e:
            logger.warning("[SceneComposer] 内皮地面铺设失败: %s", e)

    def _generate_scene_framework(self, prompt: str) -> None:
        """M2 步骤 14b-ii/15a：按 ZoneTree 生成场景框架。

        - terrain zone → 铺地面。
        - box zone → 合成白盒（带门洞），_generate_room_box 读它。
        - shell zone → 不生成白盒：建筑模型本身就是围合体，由 _place_shells 确定性放置。
        - 无 zone_tree（纯室内单房间）→ 走旧 _detect_scene_indoor + 单盒路径，零回归。
        """
        if self.zone_tree is not None and self.zone_tree.root is not None:
            zones = self.zone_tree.list_all_zones()
            has_terrain = any((z.enclosure or "") == "terrain" for z in zones)
            has_box = any((z.enclosure or "") == "box" for z in zones)
            has_shell = any((z.enclosure or "") == "shell" for z in zones)
            for z in zones:
                if (z.enclosure or "") == "terrain":
                    self._generate_terrain(z)
            if has_box:
                # _generate_room_box 内部用 _get_room_zone() 取 indoor 盒并读其门洞
                self._generate_room_box()
            # shell zone：不建白盒——建筑模型本身当围合，在 _place_shells 里放置。
            # 但要补内皮地面（15b）：外壳是实心团块没有可用内表面，进去地面是黑的。
            for z in zones:
                if (z.enclosure or "") == "shell":
                    self._generate_interior_floor(z)
            if not has_box and not has_shell and not has_terrain:
                # 树里既无 box 又无 shell 又无 terrain（异常）→ 兜底单盒
                self._generate_room_box()
            return
        # 退化：纯室内单房间走旧路径
        if self._detect_scene_indoor(prompt):
            self._generate_room_box()

    def _place_shells(self, shell_models: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """15a：把 shell 建筑模型确定性放置成围合体（不经布局 LLM）。

        用生成的建筑模型本身当外壳：居中、落地、按 AABB 缩放到包住对应 shell zone
        的 volume。模型自带入口（如蒙古包门帘），不在它身上 punch 矩形门洞——这正是
        修掉 F5 撕裂的关键（圆壳 + 方盒矩形洞 → 撕裂）。
        几何精度（是否严丝合缝包住、入口朝向）只能 F5 目测，这里给确定性的合理缺省。

        返回 {"placed": [...], "failed": ["名: 原因", ...]}，供 compose 汇报。
        shell 不进 _run_original_workflow 的家具汇报，必须独立上报，否则成败不可见。
        """
        report = {"placed": [], "failed": []}
        if not shell_models or self.zone_tree is None:
            return report
        import time as _t
        try:
            from CoronaCore.core.managers import scene_manager as _sm
            from CoronaCore.core.entities.actor import Actor
        except ImportError:
            report["failed"] = [f"{(m.get('name') or '?')}: 引擎不可用" for m in shell_models]
            return report

        # shell zone 按 asset 名索引（取各自 volume 算缩放）
        shell_zones = {}
        for z in self.zone_tree.list_all_zones():
            if (z.enclosure or "") == "shell" and z.primary_shell_asset_id:
                shell_zones[z.primary_shell_asset_id.strip()] = z

        # 读 AABB 算缩放（trimesh size = [width, height, depth]）
        asset_meta = {}
        try:
            from ..flows.scene_composition_workflow_v2.asset_metadata import (
                build_asset_metadata_batch,
            )
            paths = [m["model_path"] for m in shell_models if m.get("model_path")]
            asset_meta = build_asset_metadata_batch(paths)
        except Exception as e:
            logger.warning("[SceneComposer] shell AABB 读取失败（用缺省缩放）: %s", e)

        scene = _sm.get("")
        if scene is None:
            routes = _sm.list_all()
            scene = _sm.get(routes[0]) if routes else None
        if scene is None:
            report["failed"] = [f"{(m.get('name') or '?')}: 无可用场景" for m in shell_models]
            return report

        WRAP = 1.25  # 外壳比 volume 略大，内部舒适包住（墙厚占比 + 留白）
        for m in shell_models:
            name = (m.get("name") or "").strip()
            path = m.get("model_path", "")
            if not path:
                report["failed"].append(f"{name}: 无模型路径")
                continue
            zone = shell_zones.get(name)
            if zone is None:
                report["failed"].append(f"{name}: 未匹配到 shell zone（asset 名不一致）")
                logger.warning("[SceneComposer] 外壳 %s 未匹配 shell zone，shell_zones=%s",
                               name, list(shell_zones.keys()))
                continue
            vw, vd, vh = zone.volume.size[0], zone.volume.size[1], zone.volume.size[2]
            scale = [1.0, 1.0, 1.0]
            meta = asset_meta.get(name) or {}
            size = meta.get("size")
            if size and len(size) >= 3 and all(float(s) > 1e-6 for s in size[:3]):
                scale = [vw / float(size[0]) * WRAP,
                         vh / float(size[1]) * WRAP,
                         vd / float(size[2]) * WRAP]
            try:
                actor = Actor(name=f"__shell_{name}", route=path, actor_type="mesh",
                              parent_scene=scene)
                # 落地居中（生成模型 pivot 多在底部中心）。入口朝向无法保证，rot=0，待 F5。
                actor.set_position([0.0, 0.0, 0.0], True)
                actor.set_scale(scale, True)
                mech = getattr(actor, "_mechanics", None)
                if mech is not None:
                    try:
                        mech.set_physics_enabled(False)
                    except Exception:
                        pass
                scene.add_actor(actor)
                _t.sleep(0.3)
                report["placed"].append(name)
                logger.info("[SceneComposer] 外壳(shell)已放置: %s scale=%s",
                            name, [round(s, 2) for s in scale])
            except Exception as e:
                report["failed"].append(f"{name}: {e}")
                logger.warning("[SceneComposer] 外壳放置失败 %s: %s", name, e)
        return report


    def _run_original_workflow(self, prompt: str, resolved: List[Dict[str, Any]],
                               all_items: List[Dict[str, Any]],
                               do_import: bool,
                               reviews: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """调用原 scene_composition_workflow 节点完成布局+导入。

        reviews: Phase 2 审查结果, 注入布局 prompt 让 LLM 考虑旋转/比例建议。
        """

        # 场景框架：按 ZoneTree 生成（terrain/box，或退化单盒），再往里面摆物体
        self._generate_scene_framework(prompt)
        # 15a：shell 建筑确定性放置成围合体（模型路径此时已生成，故在框架之后）。
        shell_models = getattr(self, "_shell_models", None)
        if shell_models:
            self._shell_report = self._place_shells(shell_models)

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

        # 注入审查结果到布局 prompt
        layout_prompt = prompt[:1500]
        if reviews:
            from .model_reviewer import build_review_context
            review_ctx = build_review_context(reviews)
            layout_prompt = layout_prompt + "\n" + review_ctx
            logger.info("[SceneComposer] 已注入 %d 条审查结果到布局 prompt", len(reviews))

        state: Dict[str, Any] = {
            "prompt": layout_prompt,
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

                # 受控后处理：导入完成后一次性修正所有物体位置
                # 原则：位置修正全在物理关闭时做，最后只开一次极短物理消穿模
                if imported and actors:
                    import time as _t
                    try:
                        from CoronaCore.core.managers import scene_manager as _sm
                        scene = _sm.get("")
                        if scene is None:
                            routes = _sm.list_all()
                            scene = _sm.get(routes[0]) if routes else None
                        if scene is None:
                            raise RuntimeError("无可用场景")

                        geo_map = {a.get("name") or a.get("source_name", ""): a.get("geometry", {})
                                   for a in actors if a.get("geometry")}
                        w, d, h = self.room_size[0], self.room_size[1], self.room_size[2]
                        hw, hd, margin = w / 2.0, d / 2.0, 0.15

                        # 第一步：回设 LLM 位置 + 钳制 + 整平（物理全程关）
                        mecha, fixed, clamped, leveled = [], 0, 0, 0
                        for actor_name in imported:
                            actor = scene.find_actor(actor_name) if scene else None
                            if actor is None:
                                continue
                            mech = getattr(actor, "_mechanics", None)
                            if mech is not None:
                                try:
                                    mech.set_physics_enabled(False)
                                    mech.set_damping(0.98)
                                    mech.set_restitution(0.0)
                                    mecha.append((actor, mech))
                                except Exception:
                                    pass

                            geo = geo_map.get(actor_name, {})
                            x, y, z = actor.get_position()
                            rx, ry, rz = actor.get_rotation()

                            # 回设 LLM 布局位置
                            if geo.get("pos"):
                                px, py, pz = geo["pos"]
                                if abs(x - px) > 0.01 or abs(y - py) > 0.01 or abs(z - pz) > 0.01:
                                    x, y, z = px, py, pz
                                    fixed += 1

                            # 钳制到房间盒子内
                            changed = False
                            if x < -hw + margin: x = -hw + margin; changed = True
                            elif x > hw - margin: x = hw - margin; changed = True
                            if y < margin: y = margin; changed = True
                            elif y > h - margin: y = h - margin; changed = True
                            if z < -hd + margin: z = -hd + margin; changed = True
                            elif z > hd - margin: z = hd - margin; changed = True
                            if changed:
                                clamped += 1

                            # 地面整平：底部贴 Y=0，去倾斜
                            aabb_h = self._get_object_height(actor_name, asset_meta, geo_map)
                            if aabb_h > 0 and abs(y - aabb_h / 2.0) > 0.02:
                                y = aabb_h / 2.0
                                changed = True
                            if abs(rx) > 0.01 or abs(rz) > 0.01:
                                rx, rz = 0.0, 0.0
                                changed = True
                            if changed:
                                leveled += (1 if aabb_h > 0 else 0)

                            actor.set_position([x, y, z])
                            actor.set_rotation([rx, ry, rz])
                            if geo.get("scale"):
                                actor.set_scale(geo["scale"])

                        logger.info("[SceneComposer] 修正: 回设%d 钳制%d 整平%d",
                                    fixed, clamped, leveled)

                        # 第二步：仅一次极短暂物理消穿模（0.25s，阻尼 0.98 基本不位移）
                        if mecha:
                            for _actor, mech in mecha:
                                try:
                                    mech.set_physics_enabled(True)
                                except Exception:
                                    pass
                            _t.sleep(0.25)
                            for _actor, mech in mecha:
                                try:
                                    mech.set_physics_enabled(False)
                                except Exception:
                                    pass

                        logger.info("[SceneComposer] 后处理完成: %d 个物体", len(mecha))
                    except Exception as e:
                        logger.warning("[SceneComposer] 后处理失败（忽略）: %s", e)
            except Exception as e:
                logger.exception("[SceneComposer] import_to_engine 异常: %s", e)
                failed = [it["name"] for it in resolved]

        return {
            "items": resolved, "imported": imported, "failed": failed,
            "extracted_count": extracted, "model_count": model_count,
            "scene_path": scene_path, "error": None,
        }


__all__ = ["SceneComposer", "is_compose_request"]


