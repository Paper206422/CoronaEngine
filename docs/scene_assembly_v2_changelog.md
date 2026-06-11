# 场景组装 v2 修改记录

> 分支: `feature/scene-assembly-v2`

---

## 2026-05-29

### 14:00 — 初始运行分析

**运行结果**: tier1 3次retry(评分65, 强制通过), tier2 锚点失败(Pydantic validation error), tier3 3次retry(强制通过)

**发现**:
- Qwen3-VL `problem_actors` 始终为空 → 差量修正失效
- Tier2 retry 时 LLM 把完整句子填入 `relation` 字段 → Pydantic 校验失败
- Tier1 全部物体 X=0 (布局不合理)

**修改**:

| 文件 | 改动 |
|------|------|
| `scene_review_tools.py` | VLM prompt 简化为自然语言, 去掉 `problem_actors` 结构要求 |
| `nodes_tier_review.py` | 新增 `_extract_problem_actors_with_llm()` 两阶段提取 (VLM→LLM) |
| `nodes_tier_review.py` | `_tier_review()` 集成两阶段提取自动触发 |
| `nodes_tier_place.py` | `TIER2_RETRY_PROMPT` 加 relation 枚举值 |
| `nodes_tier_place.py` | 新增 `_normalize_relation()` 子串匹配 |
| `nodes_tier_place.py` | 新增 `_place_fallback_absolute()` 锚点失败回退绝对坐标 |

---

### 15:05 — 第二轮运行 + C老师 Review

**运行结果**: Actor 全部命名为 "base" (file basename), tier1 3次retry, tier2 落地灯丢失

**C老师反馈**:
- `_extract_problem_actors_with_llm` 需要给 LLM 提供 actor 映射表 (简称→全名)
- `_normalize_relation` 应返回 None 而非默认 "right"
- `TIER2_RETRY_PROMPT` 需要正反例对比

**修改**:

| 文件 | 改动 |
|------|------|
| `nodes_tier_review.py` | `_EXTRACT_ACTORS_SYSTEM_PROMPT` 加映射示例 |
| `nodes_tier_review.py` | 新增 `_fuzzy_match_actor_name()` 子串兜底, 多匹配返回 None |
| `nodes_tier_place.py` | `TIER2_RETRY_PROMPT` 加 ✅❌ 反例 |
| `nodes_tier_place.py` | `_normalize_relation` 不可识别返回 None |
| `scene_composition_workflow/test_cases.py` | 更新 DEFAULT_MODELS + DEFAULT_PROMPT |
| `scene_composition_workflow/test_cases.py` | 新增 `run_test_v2()` + `discover_models()` |
| `collect_models.py` | test 模式补齐 metadata (scene_name, room_size) |

---

### 15:13 — 第三轮运行

**运行结果**: Actor 命名修复生效 (中文名), 但 tier1 重复导入 ×3 (沙发_1, _2)

**根因**: `_apply_diff_correction` 被 `if problem_names:` 守卫 → 两阶段提取失败时 problem_names 为空 → 旧 actor 不删除 → 每轮 retry 累积新副本

**修改**:

| 文件 | 改动 |
|------|------|
| `nodes_tier_place.py` | 新增 `_cleanup_tier_actors()` — retry 前清理当前 tier 全部旧 actor |
| `nodes_tier_place.py` | tier1/2/3 retry 路径调用 `_cleanup_tier_actors` |

---

### 15:49 — 第四轮运行

**运行结果**: 重复导入仍在 (落地灯 ×3), tier2 物品全部丢失 (台灯/落地灯)

**根因1**: `is_retry = bool(tier1_retry_actors)` → 当 review FAIL 但 problem_actors 为空时, `tier_retry_actors=[]`, `bool([])=False` → cleanup 不执行

**根因2**: `_cleanup_tier_actors` 删除旧 actor 后, `skip_names` 仍保留其名字 → 重导入被跳过

**修改**:

| 文件 | 改动 |
|------|------|
| `nodes_tier_place.py` | `is_retry` 改用 `review_decision == "fail"` (三个 tier) |
| `nodes_tier_place.py` | retry 后从 `prev_names` 减去 `cleaned_names` (tier2/tier3) |

---

### 16:00 — VLM 升级 + 两阶段废弃

**背景**: GPT-5.5 是多模态模型, 结构化输出稳定性远高于 Qwen3-VL

**修改**:

| 文件 | 改动 |
|------|------|
| `ai_setting.py` | `omni.model`: `qwen3-vl-235b` → `gpt-5.5` |
| `scene_review_tools.py` | VLM prompt 恢复 `problem_actors` 结构化输出 |
| `nodes_tier_review.py` | 删除两阶段 LLM 提取自动触发 |
| `nodes_tier_review.py` | 更新 `scene_desc` 输出规则 |

---

### 16:25 — 第五轮运行

**运行结果**: Tier1 PASS(82分) 首次通过! Tier2 落地灯 ×3, 台灯尺度过大

**根因1**: `remove_model` 可能返回 error envelope 而非 exception → `except Exception` 捕获不到 → 假成功

**根因2**: `place_object_near` 中 `find_actor` 大小写敏感 (引擎 lowercase L型→l型)

**根因3**: 引擎 `get_world_aabb()` 始终返回 null → 锚点计算失败 → 回退绝对坐标

**修改**:

| 文件 | 改动 |
|------|------|
| `nodes_tier_place.py` | `_cleanup_tier_actors` 加 `""`, `"_1"`, `"_2"` 后缀变体尝试 |
| `place_object_near.py` | `find_actor` 加 case-insensitive fallback |
| `place_object_near.py` | `_get_actor_position_and_aabb` 加默认 AABB 估算 (position + scale) |

---

### 22:00 — 物理沉降 + 默认 Scale

**背景**: 引擎每个 Actor 创建时自带 `Mechanics` 组件, 支持 `set_physics_enabled`。场景自带 `floor_grid` (Y=0)。

**修改**:

| 文件 | 改动 |
|------|------|
| `nodes_tier_place.py` | 新增 `_DEFAULT_SCALES` 表 (台灯 0.35, 落地灯 0.6, 靠垫 0.3...) |
| `nodes_tier_place.py` | 新增 `_apply_default_scale()` — LLM 输出 scale=[1,1,1] 时按类型修正 |
| `nodes_tier_place.py` | 新增 `_filter_floor_objects()` — 排除挂画/窗帘 |
| `nodes_tier_place.py` | 新增 `_apply_physics_settlement()` — 开物理1.2s→物体落到Y=0→关物理 |
| `nodes_tier_place.py` | tier1/2/3 每层 `_apply_layout` 后调 `_apply_default_scale` |
| `nodes_tier_place.py` | tier1/2/3 每层 `_import_actors` 后调 `_apply_physics_settlement` |

---

### 其他修复 (本轮累计)

| 文件 | 改动 |
|------|------|
| `generate.py` | `image_to_3d` 传 `item_name` 作为 `prompt` → 模型目录用物品名 |
| `placement_tools.py` | actor 命名优先级: `file_name → name → object_id → local_file.name` |
| `client_hunyuan3d.py` | Hunyuan3D API v3 适配 (端点/路径/参数/并发控制) |
| `model_tools.py` | `BoundedSemaphore(max_concurrent)` 并发控制 |
| `test_cases.py` | 北欧极简 7 件模型集 + `run_test_v2()` + `discover_models()` |

---

## 当前模型矩阵

| 环节 | 模型 | Provider |
|------|------|----------|
| Tier1 布局 | `o3-mini` | DMXAPI |
| Tier2/3 布局 | `gpt-5.5` | DMXAPI |
| VLM 审查 | `gpt-5.5` | DMXAPI |
| 物品分类 | `o3-mini` | DMXAPI |
| 3D 生成 | `3.0` | Hunyuan3D |
| 参考图 | `gpt-image-2` | GRSAI |

---

## 管线数据流 (当前)

```
/sc_v2 --test
  │
  ▼
collect_models (注入 DEFAULT_MODELS)
  │
  ▼
tier1_place  (o3-mini 绝对坐标)
  → _apply_default_scale (台灯/靠垫等)
  → _run_place_scene
  → _import_actors
  → _apply_physics_settlement (落地物体 Y→0)
  ▼
tier1_review (GPT-5.5, 8角度)
  ├─ PASS → tier2
  └─ FAIL → _cleanup_tier_actors → retry tier1_place (最多2次)
  ▼
tier2_place  (gpt-5.5 锚点 → place_object_near 计算)
  → _apply_default_scale
  → _run_place_scene
  → _import_actors
  → _apply_physics_settlement
  ▼
tier2_review
  ├─ PASS → tier3
  └─ FAIL → retry
  ▼
tier3_place  (gpt-5.5 绝对坐标)
  → _apply_default_scale
  → _run_place_scene
  → _import_actors
  → _apply_physics_settlement
  ▼
tier3_review → output_result
```

---

## 2026-05-30

### VLM 审查+修正合并 (GPT-5.5 视觉修正)

**背景**: 15+ 轮测试数据诊断 — 51% VLM 问题为位置/距离, 当前 retry 链路 VLM→text→LLM 信息丢失 90%

**方案**: GPT-5.5 看图后直接输出修正坐标 (corrections), 代码层执行, 不再经过 LLM retry

**修改**:

| 文件 | 改动 |
|------|------|
| `scene_review_tools.py` | VLM prompt 加 `corrections: [{object_id, position, rotation, reason}]` 字段 |
| `nodes_tier_review.py` | 新增 `_apply_corrections()` — 解析 corrections → `set_actor_transform` 直接执行 |
| `nodes_tier_review.py` | `_tier_review` 集成: corrections 优先 → 成功则跳过 diff correction + retry |

**数据流变化**:

```
旧: VLM → problem_actors → 删 actor → LLM retry 猜坐标 → 不准
新: VLM → corrections (直接坐标) → set_actor_transform → 一次修正到位
```

**保持兼容**: corrections 为空或失败时, 回退现有 `_apply_diff_correction` 逻辑
```
