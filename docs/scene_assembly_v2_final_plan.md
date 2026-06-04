# 场景组装最终方案：关系驱动 + 几何求解 + VLM 优先修正

> 2026-06-01 | 基于 20+ 轮测试 + C 老师架构评审

---

## 核心原则

```
1. 不依赖引擎 AABB — trimesh 读文件 bbox
2. 不依赖 LLM 坐标 — LLM 输出语义关系, 代码算坐标
3. 不依赖 VLM 一定输出坐标 — corrections 优先, rule fallback
4. 不依赖物理沉降解决布局 — 保留为兜底处理引擎误差
5. 所有空间关系最终落到代码规则
```

---

## 一、总链路

```
Prompt
  ↓
collect_models (模型收集)
  ↓
Asset Metadata Builder (trimesh 读 bbox → metadata.json)
  ↓
Role & Relation Parser (LLM 输出语义关系)
  ↓
Tier1: Boundary-Anchor Placement (大件靠墙/居中)
  ↓
Tier2: Relation Solver Placement (从属在锚点附近)
  ↓
Tier3: Decoration Rule Placement (装饰绑定规则)
  ↓
Deterministic Polish (Relative Scale + Bottom Align)
  ↓
Engine Import
  ↓
VLM Review
  ├─ Corrections → apply (优先)
  ├─ Rule Correction → apply (fallback)
  └─ Physics Settlement → apply (最后兜底)
  ↓
Output
```

---

## 二、模块规格

### 1. Asset Metadata Builder (P0)

```python
def build_asset_metadata(model_path: str) -> dict:
    """trimesh 读 glb/obj, 返回 bbox + 推荐 placement_type"""
    import trimesh
    mesh = trimesh.load(model_path, force='mesh')
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    
    bmin = mesh.bounds[0]
    bmax = mesh.bounds[1]
    size = bmax - bmin
    
    return {
        "bbox_min": bmin.tolist(),
        "bbox_max": bmax.tolist(),
        "size": size.tolist(),
        "height": float(size[1]),
        "origin_y_offset": float(-bmin[1]),  # 原点→底部偏移
        "placement_type": _infer_placement_type(bmin, bmax),
    }

def _infer_placement_type(name: str, bmin, bmax) -> str:
    """从模型名+类别优先, bbox 兜底。
    
    Hunyuan3D 尺度异常会反向污染纯 bbox 分类,
    台灯 0.96m 高会被误判为 large_anchor。
    """
    h = bmax[1] - bmin[1]
    w = bmax[0] - bmin[0]
    d = bmax[2] - bmin[2]
    
    # 1) 模型名/类别优先
    name_kw = name.lower()
    if any(k in name_kw for k in ["地毯", "rug", "carpet"]):     return "floor_surface"
    if any(k in name_kw for k in ["台灯", "table_lamp"]):         return "on_surface"
    if any(k in name_kw for k in ["落地灯", "floor_lamp"]):       return "near_anchor"
    if any(k in name_kw for k in ["挂画", "窗帘", "painting"]):    return "against_wall"
    if any(k in name_kw for k in ["摆件", "花瓶", "靠垫"]):        return "on_surface"
    if any(k in name_kw for k in ["绿植", "盆栽", "plant"]):      return "near_wall"
    
    # 2) bbox 兜底
    if h < 0.03 and max(w, d) > 0.5:  return "floor_surface"
    if h < 0.3 and w < 0.5:            return "on_surface"
    if h > 0.8 and w < 0.5:            return "near_anchor"
    if h < 0.05 and w > 0.5:           return "against_wall"
    return "large_anchor"
```

### 2. Relative Scale Normalizer (P1)

```
规则:
  table_lamp:    height = support_height × 0.6
  floor_lamp:    height = anchor_height × 1.5
  rug:           width = group_width × 1.25, depth = group_depth × 1.25
  nightstand:    height = bed_height × 0.6
  decoration:    height = support_height × 0.3
  tv_stand:      若 height < 0.3m → scale_y 放大至 0.45-0.6m
                 仅当模型名含"悬空/壁挂"时才 wall_mount
                 否则按 large_anchor 落地处理
  
有 bbox → 反推 scale: target_height / raw_height
无 bbox → DEFAULT_SCALES 表 fallback
异常值 → clamp [0.1, 3.0]
```

### 3. Constraint Solver (P0)

```python
RELATIONS = {
    "on_surface":       (obj, tgt) → tgt.center_xz + tgt.top_y,
    "near_anchor":      (obj, anchor, side, dist) → anchor.side(side) + dist,
    "against_wall":     (obj, wall, offset) → wall.pos + offset,
    "in_front":         (obj, anchor, dist) → anchor.front(dist),
    "center_under_group": (obj, group) → group.center_xz + y=0.01,
    "between":          (obj, a, b) → midpoint(a, b),
}
```

### 4. Correction Pipeline (P1)

```python
def apply_corrections(review_result, scene):
    # 1) VLM corrections 优先 — 但必须经过 solver 校验
    corrections = review_result.get("corrections", [])
    for c in corrections:
        if not validate_object_id(c["object_id"]):   continue
        if not validate_bbox_bounds(c, scene):        continue
        if not validate_relation_invariant(c, scene): continue
        # 例: table_lamp 不能被移到地上, rug 不能被移到桌面高度
        execute_correction(c)
    
    # 2) Rule-based fallback
    for pa in review_result.get("problem_actors", []):
        rule = RULE_MAP.get(pa["issue"])
        if rule:
            rule(pa["actor"], pa.get("target"), scene)
    
    # 3) Physics last resort
    apply_physics_settlement(scene)
```

---

## 三、Tier 职责调整

| Tier | 旧职责 | 新职责 |
|------|--------|--------|
| Tier1 | o3-mini 输出坐标 | LLM 输出边界关系 (against_wall/center_in_zone) |
| Tier2 | gpt-5.5 输出锚点JSON | LLM 输出语义关系 (near_anchor/on_surface/in_front) |
| Tier3 | gpt-5.5 输出坐标 | LLM 输出绑定规则 (center_under_group/near_wall) |

---

## 四、保留 & 新增 & 删除

### 保留
- 三层 DAG + condition routing
- VLM 审查 (GPT-5.5, 8角度)
- Corrections 优先执行
- 物理沉降 (兜底)
- 挂墙修正 (融入 solver)
- _check_overlap (碰撞检测)
- _validate_positions (边界校验)

### 新增
- Asset Metadata Builder (trimesh → bbox)
- Relative Scale Normalizer (ratio-based)
- Constraint Solver (6 relations)
- Rule Correction Fallback (issue→action map)

### 删除
- place_object_near 工具 (已替换为 _calculate_semantic_position)
- _DEFAULT_SCALES 表 (替换为 Relative Scale Normalizer, 保留为 fallback)
- o3-mini 输出坐标 (改为输出关系)

---

## 五、实施风险标注 ⚠️

### 🔴 高风险

| 风险点 | 位置 | 说明 | 缓解 |
|--------|------|------|------|
| **Tier1 prompt 改 relation** | `nodes_tier_place.py` TIER1_INITIAL_PROMPT | o3-mini 可能输出不合法 JSON（relation 字段拼错/缺少 target） | 先验证 3 次 LLM 输出再接入, 加 JSON schema 校验 |
| **Constraint Solver 依赖顺序** | `constraint_solver.py` | `in_front` 的 target 可能还没放置→None→求解失败 | solver 执行前拓扑排序, 检测循环依赖 |
| **LLM 输出 relation 不稳定** | Tier1/Tier2 prompt | 不同场景的物体名不同, LLM 可能输出不存在的 target | 强制 target 白名单校验(只允许 anchor 列表中的名字) |

### 🟡 中风险

| 风险点 | 位置 | 说明 | 缓解 |
|--------|------|------|------|
| **trimesh 不能解析所有模型** | `asset_metadata.py` | Hunyuan3D 产出的 zip/obj/glb 格式不统一, trimesh 可能失败 | try/except → fallback DEFAULT_SCALES表 |
| **Relative Scale 需要 anchor 先有 scale** | `relative_scale.py` | 锚点本身 scale 还没定→相对计算无参照 | Tier1 先用 DEFAULT_SCALES 定锚点 scale |
| **VLM corrections 数量爆炸** | `nodes_tier_review.py` | 8件×3retry=24次 corrections 可能冲突 | 每次只修正 problem_actors 中的物体 |
| **Rule Correction 映射不全** | `_apply_corrections` | VLM 可能输出新 issue 不在 RULE_MAP 中 | 未知 issue → physics fallback |

### 🟢 低风险

| 风险点 | 说明 |
|--------|------|
| **现有静默吞异常(10处)** | `except Exception: pass` 可能掩盖真实 bug, 大改前应加 log.warning |
| **GPU 崩溃** | VK_ERROR 依然可能在截图密集时出现 |
| **物理沉降盲等** | sleep(1.2s) 不可靠, 但作为最后兜底可接受 |

---

## 六、实施状态 (2026-06-04 更新)

### Week 1: 基础闭环

| 天 | 任务 | 状态 | 备注 |
|----|------|------|------|
| Day 1 | Asset Metadata Builder | ✅ 完成 | trimesh bbox, collect_models 集成 |
| Day 2 | Constraint Solver | ✅ 完成 | 6 关系 + scale normalizer |
| Day 3 | Tier1 prompt → relation | ✅ 初始 | LLM 稳定输出语义关系；**retry merge bug 已修复** |
| Day 4 | Relative Scale Normalizer | ⚠️ 定义未集成 | solver 中有 `normalize_relative_scale`，placement 管线未调用 |
| Day 5 | 全链路联调 | ⚠️ 部分 | 坐标由 solver 产出 ✅；retry 待验证；tier3 未执行 |

### Week 2: 修正闭环

| 天 | 任务 | 状态 | 备注 |
|----|------|------|------|
| Day 1 | Rule Correction Fallback | ⚠️ 诊断日志 | RULE_ACTION_MAP 已定义，执行逻辑未接 |
| Day 2 | Tier3 绑定规则 | ❌ 未开始 | Tier3 prompt 仍是旧格式 |
| Day 3 | 全链路联调 | ❌ | 待 retry + tier3 修复 |
| Day 4 | 日志+统计 | ⚠️ | llm_raw dump 已加，retry dump 待验证 |
| Day 5 | Code Review + 清理 | ❌ | 待管线稳定 |

### 🔴 当前阻塞

| 问题 | 原因 | 修复 |
|------|------|------|
| **Retry 退化到 Z=-1.0** | merge 用 tier1_items (无 pos) | ✅ merge 已修复 |
| **Corrections 猜错坐标** | 文本 LLM 猜位置不可靠但跳过 retry | ✅ text LLM corrections 不再跳过 retry |
| **Tier3 不执行** | retry 卡住导致 chain 断裂 | ✅ 三层已跑通 (12:36 session) |
| **截图偶发中断** | 引擎线程修复后连续截图不稳定 | 8→4 角度缓解 |
| **评分 62-68 < 目标 75** | 布局 X 分散不够 + corrections 猜错位置 | 待 retry 修复后重评 |

### ⚠️ 中期待办

- Relative Scale Normalizer 接入 placement 管线
- Tier2/Tier3 prompt 改为语义关系格式
- RULE_ACTION_MAP 执行逻辑接入 (Week 2)
- get_world_aabb() 仍返回 null，trimesh bbox 作为替代
- 引擎碰撞修复 (90a62c9c) 是物理刚体碰撞，非 AABB API

---

## 七、验收标准 (目标)

```
□ 不调用 get_world_aabb()
□ Tier1/Tier2/Tier3 LLM 不输出坐标
□ 台灯 scale 反推自真实 bbox
□ 地毯位于沙发茶几组下方
□ 落地灯在 anchor 侧 0.3m
□ VLM corrections 优先执行
□ Rule correction fallback 触发日志可见
□ 重复 retry 0 个副本
□ 平均评分 ≥ 75
□ relation satisfaction ≥ 90% (语义关系被正确求解)
□ scale anomaly ≤ 1 / scene (异常 scale 数量)
□ floating / severe penetration = 0 (悬空/严重穿模)
```
