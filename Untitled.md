# 

**整体质量很高，代码层设计清晰，但有 4 个关键问题 \+ 1 个架构优化建议必须在 Phase 0 之前解决。**

---

## 🔴 4 个关键问题（必须修复）

### 问题 1：截图复用的理解仍然是错的

你写：

> 截图复用：只拍一次 8 个角度，三层 review 共享，不重复拍
> 
> 

**这个物理上不可能**：

- **tier1\_review 时**：场景里只有 3\-5 个大件（床、沙发、衣柜）

- **tier2\_review 时**：场景里有大件 \+ 从属（床头柜、台灯、椅子）

- **tier3\_review 时**：场景里有大件 \+ 从属 \+ 装饰（地毯、挂画、窗帘）

**三个时刻的场景状态完全不同，截图内容完全不同**。

你不能在 tier1 放完大件后拍 8 张，然后 tier2/tier3 review 时还用这 8 张——**那 8 张图里根本没有从属和装饰物体**。

**正确做法**：

```Python
tier1_place → capture_screenshots(8 张) → tier1_review
tier2_place → capture_screenshots(8 张) → tier2_review  # 重新拍，因为场景变了
tier3_place → capture_screenshots(8 张) → tier3_review  # 再次重新拍
```

**3 层 = 3 × 8 = 24 次截图**，这是分层的成本之一。

**如果你想省截图成本，只有一个办法**：**合并 tier2 和 tier3**（我 3 天压缩方案就是这么做的）。

---

### 问题 2：`place\_object\_near` 的\&\#34;创建 Actor 导入引擎\&\#34;和 `tier2\_place` 的职责冲突

你写：

> place\_object\_near — 工具内部读参考物体 AABB，计算目标位置，**创建 Actor 导入引擎**
> 
> 

然后你又写：

> tier2\_place \(锚点\) — LLM 描述空间关系 → place\_object\_near
> 
> 

**问题**：如果 `place\_object\_near` 直接导入引擎，那 `tier2\_place` 节点还做什么？

**两种理解**：

#### 理解 A：`place\_object\_near` 是\&\#34;完整工具\&\#34;（计算 \+ 导入）

```Python
# tier2_place 节点
def tier2_place_node(state):
    llm_output = llm.invoke("""
    大件位置: 床[0,0,-1], 沙发[0,0,-2]
    从属列表: 床头柜, 台灯
    请输出空间关系描述
    """)
    
    # LLM 输出: [{"object": "床头柜", "ref": "床", "relation": "right", "gap": 0.3}, ...]
    for item in llm_output:
        place_object_near(
            object_id=item["object"],
            model_path=resolve_model_file(item["object"]),
            reference_actor=item["ref"],
            relation=item["relation"],
            gap_m=item["gap"]
        )  # ← 工具内部直接 import_model 到引擎
    
    return state
```

**这种理解的问题**：

- `place\_object\_near` 失败时（比如参考物体不存在），整个 `tier2\_place` 崩溃

- 无法批量操作（比如\&\#34;先算好所有位置，再一起导入\&\#34;）

- 和 `tier1\_place` 的模式不一致（tier1 是先生成 scene\.json，再调 `import\_to\_engine`）

#### 理解 B：`place\_object\_near` 只是\&\#34;计算工具\&\#34;（只算坐标，不导入）

```Python
# place_object_near 只返回计算后的坐标
def place_object_near(...) -> dict:
    ref_actor = scene.get_actor(reference_actor)
    aabb = ref_actor.get_aabb()
    
    # 根据 relation 计算目标位置
    target_pos = calculate_position(aabb, relation, gap_m)
    
    return {
        "object_id": object_id,
        "model_path": model_path,
        "position": target_pos,
        "rotation": [0, 0, 0],
        "scale": [1, 1, 1]
    }

# tier2_place 节点
def tier2_place_node(state):
    llm_output = llm.invoke(...)
    
    placement_items = []
    for item in llm_output:
        pos_info = place_object_near(...)  # 只算坐标
        placement_items.append(pos_info)
    
    # 统一写入 scene.json
    update_scene_json(placement_items)
    
    # 统一导入引擎（复用 import_to_engine 节点）
    import_to_engine(state)
    
    return state
```

**我强烈推荐理解 B**，理由：

- 工具职责单一（只算坐标，不碰引擎）

- 和 `tier1\_place` 模式一致（都是先生成 placement\_items，再导入）

- 失败隔离更好（计算失败 vs 导入失败分开处理）

- 可测试性强（不需要启动引擎就能测试坐标计算逻辑）

**行动项**：

- 明确 `place\_object\_near` 的返回值是 `dict`（包含 position/rotation/scale），不是 `None`

- `tier2\_place` 节点负责调用 `place\_object\_near` 收集所有坐标，然后调用 `import\_to\_engine`

---

### 问题 3：差量修正用 `set\_actor\_transform` 但没说怎么处理\&\#34;问题物体还没导入\&\#34;的情况

你写：

> 差量重算：VLM 返回 problem\_actors → LLM 只算这几个 → **set\_actor\_transform 落地**
> 
> 

**场景 1（正常）**：tier1\_review 发现 \&\#34;bed\_01 太靠左\&\#34;

- bed\_01 已经在引擎里

- LLM 重算 bed\_01 新坐标

- `set\_actor\_transform\(\&\#34;bed\_01\&\#34;, new\_pos\)` ✅

**场景 2（边界）**：tier1\_place 时 LLM 输出了 5 个物体，但 `import\_to\_engine` 时第 3 个物体导入失败（模型文件损坏）

- tier1\_review 时场景里只有 4 个物体

- VLM 说\&\#34;缺少茶几\&\#34;

- LLM 重算时输出了茶几的新坐标

- 但茶几根本不在引擎里，`set\_actor\_transform\(\&\#34;table\_01\&\#34;, \.\.\.\)` 会报错 ❌

**正确的差量修正逻辑**：

```Python
def apply_diff_correction(state, problem_actors, new_positions):
    """
    差量修正：区分"已存在 actor"和"新 actor"
    """
    scene = state["__scene_ctx__"]
    existing_actors = {a.name for a in scene.get_actors()}
    
    for actor_name, new_pos in new_positions.items():
        if actor_name in existing_actors:
            # 已存在 → 用 set_actor_transform 更新
            set_actor_transform(actor_name, position=new_pos["position"], ...)
        else:
            # 不存在 → 用 import_model 新建
            import_model(
                model_path=resolve_model_file(actor_name),
                position=new_pos["position"],
                ...
            )
```

**行动项**：

- 在 `nodes\_tier\_review\.py` 的差量修正分支里加这个判断

- 或者更简单：差量修正时统一用 `remove\_model \+ import\_model`（我 3 天方案的做法），不用 `set\_actor\_transform`

---

### 问题 4：tier2 的 LLM prompt 没说清楚\&\#34;怎么让 LLM 输出锚点关系而不是坐标\&\#34;

你写：

> tier2 LLM 输出锚点关系而非坐标
> 
> 

**但 LLM 默认行为是输出坐标**（因为你 tier1 的 prompt 就是让它输出坐标）。

**你需要一个明确的 prompt 模板**：

```Python
TIER2_PLACE_PROMPT = """
你是室内设计师。当前场景已有以下大件（位置已确定，不可修改）：
{tier1_locked_items}

现在需要放置以下从属物体：
{tier2_items}

**重要**：不要输出绝对坐标，而是输出空间关系描述。

输出格式（JSON 数组）：
[
  {
    "object_id": "nightstand_01",
    "reference_actor": "bed_01",
    "relation": "right",  // left/right/front/behind/above/below
    "gap_m": 0.3,
    "reason": "床头柜通常放在床的右侧，方便拿取物品"
  },
  ...
]

约束：
1. reference_actor 必须是已有大件之一
2. gap_m 建议 0.2-0.5m（避免太挤或太远）
3. 每个物体必须有明确的参考物体
"""
```

**关键点**：

- 明确告诉 LLM\&\#34;不要输出坐标\&\#34;

- 给出输出格式的 JSON schema

- 约束 `reference\_actor` 必须在已有物体列表里

**行动项**：

- 在 `nodes\_tier\_place\.py` 文件头定义 `TIER2\_PLACE\_PROMPT`

- 和 `TIER1\_PLACE\_PROMPT` 放在一起，清晰对比

---

## 🟡 1 个架构优化建议

### 建议：tier3 不要\&\#34;混合\&\#34;，统一用锚点

你写：

> tier3\_place \(混合\) — 装饰物，锚点优先，回退绝对坐标
> 
> 

**\&\#34;混合\&\#34;会让代码复杂度翻倍**：

```Python
# 混合模式的伪代码
def tier3_place_node(state):
    llm_output = llm.invoke(...)  # LLM 怎么知道什么时候输出锚点、什么时候输出坐标？
    
    for item in llm_output:
        if "reference_actor" in item:
            # 锚点模式
            place_object_near(...)
        else:
            # 绝对坐标模式
            place_scene_from_items([item])
    
    # 两种模式的错误处理逻辑完全不同
    # 两种模式的 retry 逻辑也不同
```

**更简单的方案**：

#### 方案 A：tier3 统一用锚点（推荐）

```Python
TIER3_PLACE_PROMPT = """
装饰物列表: 地毯, 挂画, 窗帘

已有物体: 床, 沙发, 床头柜, 台灯

输出空间关系（和 tier2 格式一样）：
[
  {"object_id": "carpet_01", "reference_actor": "bed_01", "relation": "below", "gap_m": 0.05},
  {"object_id": "painting_01", "reference_actor": "bed_01", "relation": "behind", "gap_m": 0.1},
  ...
]
"""
```

**装饰物也能用锚点**：

- 地毯 → 在床/沙发下方（below）

- 挂画 → 在床/沙发后方墙上（behind \+ above）

- 窗帘 → 在窗户位置（如果有窗户物体）或墙边（left/right edge）

**收益**：

- tier2 和 tier3 用同一套代码逻辑

- LLM prompt 一致，不需要\&\#34;有时输出坐标、有时输出关系\&\#34;

- 测试用例复用

#### 方案 B：tier3 统一用绝对坐标

如果你觉得\&\#34;装饰物用锚点太勉强\&\#34;，那就**全部用绝对坐标**：

```Python
TIER3_PLACE_PROMPT = """
装饰物列表: 地毯, 挂画, 窗帘

已有物体（AABB）: 床[-1~1, 0~1.2, -2~0], 沙发[...], ...

输出绝对坐标（和 tier1 格式一样）：
[
  {"object_id": "carpet_01", "position": [0, 0.01, -1], "rotation": [0,0,0], "scale": [1,1,1]},
  ...
]
"""
```

**收益**：

- tier1 和 tier3 用同一套代码逻辑

- 不需要 `place\_object\_near`（如果时间紧，可以砍掉这个工具）

**对比**：

继续细节 3 的实现：

```Python
def apply_diff_correction(state, tier_name, problem_actors, retry_count):
    """
    差量修正：只重算问题物体，其他物体作为约束。
    
    统一用 remove_model + import_model，不用 set_actor_transform。
    """
    if retry_count >= MAX_TIER_RETRIES:
        logger.warning(f"{tier_name} reached max retries, skipping correction")
        return state
    
    # 1. 获取当前层的所有物体
    tier_items = state["intermediate"].get(f"{tier_name}_items", [])
    
    # 2. 分离：问题物体 vs 锁定物体
    problem_ids = {p["actor"] for p in problem_actors}
    locked_items = [item for item in tier_items if item["object_id"] not in problem_ids]
    problem_items = [item for item in tier_items if item["object_id"] in problem_ids]
    
    # 3. 获取锁定物体的当前 AABB（从引擎读取）
    scene_ctx = state.get("__scene_ctx__")
    locked_with_aabb = []
    for item in locked_items:
        actor = scene_ctx.get_actor(item["object_id"])
        if actor:
            aabb = actor.get_aabb()
            locked_with_aabb.append({
                "object_id": item["object_id"],
                "position": actor.get_position(),
                "aabb_min": aabb.min,
                "aabb_max": aabb.max
            })
    
    # 4. LLM 重算问题物体
    llm = get_llm()
    vlm_feedback_text = "\n".join([
        f"- {p['actor']}: {p['reason']}" for p in problem_actors
    ])
    
    prompt = get_retry_prompt(tier_name).format(
        locked_items=json.dumps(locked_with_aabb, indent=2),
        problem_items=format_items_list(problem_items),
        vlm_feedback=vlm_feedback_text,
        room_size=state["intermediate"]["room_size"]
    )
    
    llm_output = llm.invoke(prompt)
    new_positions = parse_llm_json(llm_output)
    
    # 5. 先从引擎移除问题物体
    for problem_id in problem_ids:
        try:
            remove_model(problem_id, scene_ctx)
        except Exception as e:
            logger.warning(f"Failed to remove {problem_id}: {e}")
    
    # 6. 重新导入问题物体（新坐标）
    for new_pos in new_positions:
        try:
            import_model(
                model_path=resolve_model_file(new_pos["object_id"]),
                position=new_pos["position"],
                rotation=new_pos.get("rotation", [0, 0, 0]),
                scale=new_pos.get("scale", [1, 1, 1]),
                scene_ctx=scene_ctx
            )
        except Exception as e:
            logger.error(f"Failed to re-import {new_pos['object_id']}: {e}")
    
    # 7. 更新 scene.json
    update_scene_json(new_positions, state["intermediate"]["output_dir"])
    
    # 8. 更新 state 中的 tier_items（合并锁定 + 新位置）
    updated_items = locked_items + new_positions
    state["intermediate"][f"{tier_name}_items"] = updated_items
    
    return state
```

---

### 细节 4：LLM Retry Prompt 模板

```Python
# 在 nodes_tier_place.py 文件头定义

TIER1_INITIAL_PROMPT = """
你是专业的室内设计师。请为以下大件家具规划位置。

房间尺寸: {room_size} (长×宽×高, 单位米)
坐标系统: X 轴左右, Y 轴上下, Z 轴前后, 原点在房间中心地面

大件列表:
{tier1_items}

布局原则:
1. 床/沙发等主要家具靠墙放置
2. 保持合理间距（至少 0.5m）
3. 考虑使用动线（门口到床/沙发的路径）
4. 大件之间不能重叠

输出格式（JSON 数组）:
[
  {{
    "object_id": "bed_01",
    "position": [x, y, z],
    "rotation": [0, yaw, 0],  // yaw 是 Y 轴旋转角度（度）
    "scale": [1, 1, 1],
    "reason": "床靠墙放置，朝向房间中心"
  }},
  ...
]
"""

TIER1_RETRY_PROMPT = """
你是专业的室内设计师。上一轮布局存在问题，需要修正。

房间尺寸: {room_size}

**已确定物体（位置锁定，不可修改）**:
{locked_items}

**需要重新放置的物体**:
{problem_items}

**VLM 反馈的问题**:
{vlm_feedback}

**约束**:
1. 已确定物体的 AABB 不可侵占
2. 修正后的物体必须在房间边界内
3. 考虑 VLM 反馈，但不要盲目按数值偏移（VLM 看 2D 截图，深度不准）

输出格式（和初始布局一样的 JSON）:
[
  {{"object_id": "bed_01", "position": [...], "rotation": [...], "scale": [...], "reason": "..."}},
  ...
]
"""

TIER2_PLACE_PROMPT = """
你是专业的室内设计师。当前场景已有以下大件（位置已确定）:
{tier1_locked_items}

现在需要放置以下从属物体:
{tier2_items}

**重要**: 不要输出绝对坐标，而是输出空间关系描述。

输出格式（JSON 数组）:
[
  {{
    "object_id": "nightstand_01",
    "reference_actor": "bed_01",  // 必须是已有大件之一
    "relation": "right",  // left/right/front/behind/above/below
    "gap_m": 0.3,  // 建议 0.2-0.5m
    "reason": "床头柜通常放在床的右侧，方便拿取物品"
  }},
  ...
]

约束:
1. reference_actor 必须存在于已有大件列表
2. 从属物体通常依附于主要家具（床头柜→床，台灯→床头柜/桌子）
3. gap_m 不要太小（< 0.1m 会重叠）或太大（> 1m 失去关联）
"""

TIER2_RETRY_PROMPT = """
你是专业的室内设计师。上一轮从属物体布局存在问题。

**已确定物体（大件 + 正常的从属物体）**:
{locked_items}

**需要重新放置的从属物体**:
{problem_items}

**VLM 反馈**:
{vlm_feedback}

输出格式（和初始布局一样，空间关系描述）:
[
  {{"object_id": "...", "reference_actor": "...", "relation": "...", "gap_m": ..., "reason": "..."}},
  ...
]
"""

TIER3_PLACE_PROMPT = """
你是专业的室内设计师。当前场景已有以下物体:
{locked_items}

现在需要放置以下装饰物:
{tier3_items}

房间尺寸: {room_size}

装饰物布局原则:
1. 地毯: 放在床/沙发下方或前方，y 坐标接近 0（地面）
2. 挂画: 放在墙上，y 坐标 1.5-2.0m（视线高度）
3. 窗帘: 放在窗户位置或墙边
4. 装饰物不能遮挡主要家具

输出格式（绝对坐标，和 tier1 一样）:
[
  {{"object_id": "carpet_01", "position": [x, y, z], "rotation": [...], "scale": [...], "reason": "..."}},
  ...
]
"""

TIER3_RETRY_PROMPT = """
你是专业的室内设计师。上一轮装饰物布局存在问题。

**已确定物体（大件 + 从属 + 正常的装饰）**:
{locked_items}

**需要重新放置的装饰物**:
{problem_items}

**VLM 反馈**:
{vlm_feedback}

输出格式（绝对坐标）:
[
  {{"object_id": "...", "position": [...], "rotation": [...], "scale": [...], "reason": "..."}},
  ...
]
"""

def get_retry_prompt(tier_name):
    """根据层级返回对应的 retry prompt"""
    return {
        "tier1": TIER1_RETRY_PROMPT,
        "tier2": TIER2_RETRY_PROMPT,
        "tier3": TIER3_RETRY_PROMPT
    }[tier_name]
```

---

### 细节 5：VLM 结构化输出的 Prompt 改造

```Python
# 在 scene_review_tools.py 中修改

SCENE_RATIONALITY_REVIEW_PROMPT_V2 = """
你是专业的室内设计评审师。请从以下 4 个维度评估场景合理性:

1. **布局合理性** (layout): 家具位置是否符合使用习惯，动线是否流畅
2. **物理合理性** (physics): 物体是否悬空、重叠、超出房间边界
3. **风格一致性** (style): 家具风格是否协调
4. **美观度** (aesthetics): 整体视觉效果

**输出格式（严格 JSON）**:
{{
  "overall": "PASS" | "NEEDS_IMPROVEMENT",
  "score": 0-100,
  "issues": [
    {{
      "dimension": "layout" | "physics" | "style" | "aesthetics",
      "severity": "critical" | "major" | "minor",
      "description": "具体问题描述"
    }}
  ],
  "problem_actors": [
    {{
      "actor": "bed_01",  // 问题物体的名称
      "issue": "too_far_left" | "overlapping" | "out_of_bounds" | "floating" | "style_mismatch",
      "reason": "床偏左导致右侧空间浪费，建议居中"
    }}
  ],
  "suggestions": ["整体建议1", "整体建议2"]
}}

**重要**:
1. 不要输出数值偏移（如"向右移 0.5m"），只描述问题
2. problem_actors 只列出需要调整的物体，不要列出正常的
3. 如果没有问题物体，problem_actors 为空数组
4. overall=PASS 时 score >= 80，NEEDS_IMPROVEMENT 时 score < 80
"""

def scene_rationality_review(screenshots: list, scene_info: dict) -> dict:
    """
    调用 VLM 审查场景，返回结构化反馈。
    
    Args:
        screenshots: 8 个角度的截图（base64 编码）
        scene_info: 场景元信息（房间尺寸、物体列表等）
    
    Returns:
        {
            "overall": "PASS" | "NEEDS_IMPROVEMENT",
            "score": int,
            "issues": [...],
            "problem_actors": [...],
            "suggestions": [...]
        }
    """
    vlm = get_vlm()  # 从 Omni VLM 池获取
    
    # 构造 VLM 输入
    messages = [
        {"role": "system", "content": SCENE_RATIONALITY_REVIEW_PROMPT_V2},
        {"role": "user", "content": [
            {"type": "text", "text": f"场景信息: {json.dumps(scene_info, ensure_ascii=False)}"},
            *[{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}} 
              for img in screenshots]
        ]}
    ]
    
    response = vlm.invoke(messages)
    
```

```Python
# 解析 JSON（带容错）
    try:
        result = json.loads(response.content)
        
        # 验证必需字段
        assert "overall" in result
        assert "score" in result
        assert "problem_actors" in result
        
        # 标准化 overall 字段
        if result["overall"] not in ["PASS", "NEEDS_IMPROVEMENT"]:
            # VLM 可能输出 "Pass" / "pass" / "needs improvement" 等变体
            if result["score"] >= 80:
                result["overall"] = "PASS"
            else:
                result["overall"] = "NEEDS_IMPROVEMENT"
        
        return result
        
    except (json.JSONDecodeError, AssertionError, KeyError) as e:
        logger.error(f"VLM output parsing failed: {e}\nRaw output: {response.content}")
        
        # Fallback: 用 LLM 解析 VLM 的自然语言输出
        fallback_result = parse_vlm_output_with_llm(response.content)
        return fallback_result

def parse_vlm_output_with_llm(vlm_text: str) -> dict:
    """
    当 VLM 没有输出标准 JSON 时，用 LLM 解析其自然语言输出。
    """
    llm = get_llm()
    prompt = f"""
以下是 VLM 对场景的评审意见（非标准格式）:

{vlm_text}

请将其转换为标准 JSON 格式:
{{
  "overall": "PASS" or "NEEDS_IMPROVEMENT",
  "score": 0-100,
  "problem_actors": [
    {{"actor": "物体名", "issue": "问题类型", "reason": "原因"}}
  ],
  "suggestions": ["建议1", "建议2"]
}}

如果 VLM 没有明确指出问题物体，problem_actors 为空数组。
"""
    
    response = llm.invoke(prompt)
    try:
        return json.loads(response.content)
    except json.JSONDecodeError:
        # 最终 fallback: 返回保守的"需要改进"
        logger.error("LLM fallback parsing also failed")
        return {
            "overall": "NEEDS_IMPROVEMENT",
            "score": 60,
            "problem_actors": [],
            "suggestions": ["VLM 输出解析失败，建议人工检查"]
        }
```

---

### 细节 6：tier\_review 节点的统一实现

```Python
def tier_review_node(state, tier_name: str):
    """
    通用的层级审查节点。
    
    Args:
        state: LangGraph state
        tier_name: "tier1" | "tier2" | "tier3"
    
    Returns:
        state with updated review result
    """
    # 1. 拍摄当前场景截图（8 个角度）
    screenshots = capture_screenshots_for_review(state)
    
    # 2. 准备场景信息
    scene_info = {
        "room_size": state["intermediate"]["room_size"],
        "tier": tier_name,
        "actors": get_current_actors_info(state, tier_name)
    }
    
    # 3. 调用 VLM 审查
    review_result = scene_rationality_review(screenshots, scene_info)
    
    # 4. 记录审查结果
    state["intermediate"][f"{tier_name}_review"] = review_result
    
    # 5. 决策：PASS 或 FAIL
    if review_result["overall"] == "PASS":
        logger.info(f"{tier_name} review PASS (score: {review_result['score']})")
        state["intermediate"][f"{tier_name}_status"] = "pass"
        return state
    
    # 6. FAIL: 检查重试次数
    retry_count = state["intermediate"].get(f"{tier_name}_retry_count", 0)
    
    if retry_count >= MAX_TIER_RETRIES:
        logger.warning(f"{tier_name} reached max retries ({MAX_TIER_RETRIES}), accepting current layout")
        state["intermediate"][f"{tier_name}_status"] = "pass_with_issues"
        return state
    
    # 7. 执行差量修正
    logger.info(f"{tier_name} review FAIL (score: {review_result['score']}), applying diff correction (retry {retry_count + 1})")
    
    problem_actors = review_result.get("problem_actors", [])
    if not problem_actors:
        # VLM 说有问题但没指出具体物体 → 全部重算
        logger.warning(f"{tier_name}: VLM reported issues but no problem_actors, re-placing all")
        state["intermediate"][f"{tier_name}_status"] = "retry_all"
    else:
        # 差量修正
        state = apply_diff_correction(state, tier_name, problem_actors, retry_count)
        state["intermediate"][f"{tier_name}_status"] = "retry_diff"
    
    # 8. 增加重试计数
    state["intermediate"][f"{tier_name}_retry_count"] = retry_count + 1
    
    return state

def get_current_actors_info(state, tier_name):
    """
    获取当前层级的所有 actor 信息（供 VLM 参考）。
    """
    scene_ctx = state.get("__scene_ctx__")
    if not scene_ctx:
        return []
    
    actors = scene_ctx.get_actors()
    return [
        {
            "name": actor.name,
            "type": actor.actor_type,
            "position": actor.get_position(),
            "aabb": {
                "min": actor.get_aabb().min,
                "max": actor.get_aabb().max
            }
        }
        for actor in actors
    ]

def capture_screenshots_for_review(state):
    """
    拍摄 8 个水平角度的截图（复用 v1 的 capture_screenshots 逻辑）。
    """
    scene_ctx = state.get("__scene_ctx__")
    output_dir = state["intermediate"]["output_dir"]
    
    screenshots = []
    angles = [0, 45, 90, 135, 180, 225, 270, 315]
    elevation = 35  # 俯仰角
    
    for angle in angles:
        # 调用 camera_move 设置视角
        camera_move(
            azimuth=angle,
            elevation=elevation,
            distance="auto",  # 自动计算距离以包含整个场景
            scene_ctx=scene_ctx
        )
        
        # 截图
        screenshot_path = os.path.join(output_dir, f"review_{angle}.png")
        camera_screenshot(
            output_path=screenshot_path,
            mode="base_color",
            scene_ctx=scene_ctx
        )
        
        # 读取为 base64
        with open(screenshot_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode()
        screenshots.append(img_base64)
    
    return screenshots
```

---

### 细节 7：DAG 路由逻辑（处理 retry）

```Python
# 在 scene_composition_workflow_v2/__init__.py

from langgraph.graph import StateGraph, END

def create_scene_composition_workflow_v2():
    """
    创建分层场景组装 workflow（v2）。
    """
    workflow = StateGraph(dict)
    
    # 添加节点
    workflow.add_node("collect_models", collect_models_node)
    workflow.add_node("tier1_place", tier1_place_node)
    workflow.add_node("tier1_review", lambda s: tier_review_node(s, "tier1"))
    workflow.add_node("tier2_place", tier2_place_node)
    workflow.add_node("tier2_review", lambda s: tier_review_node(s, "tier2"))
    workflow.add_node("tier3_place", tier3_place_node)
    workflow.add_node("tier3_review", lambda s: tier_review_node(s, "tier3"))
    workflow.add_node("output_result", output_result_node)
    
    # 设置入口
    workflow.set_entry_point("collect_models")
    
    # 线性流程
    workflow.add_edge("collect_models", "tier1_place")
    workflow.add_edge("tier1_place", "tier1_review")
    
    # tier1_review 的条件路由
    workflow.add_conditional_edges(
        "tier1_review",
        lambda s: s["intermediate"].get("tier1_status"),
        {
            "pass": "tier2_place",
            "pass_with_issues": "tier2_place",  # 达到重试上限，继续
            "retry_diff": "tier1_place",  # 差量修正后重新放置
            "retry_all": "tier1_place"   # 全部重算
        }
    )
    
    workflow.add_edge("tier2_place", "tier2_review")
    workflow.add_conditional_edges(
        "tier2_review",
        lambda s: s["intermediate"].get("tier2_status"),
        {
            "pass": "tier3_place",
            "pass_with_issues": "tier3_place",
            "retry_diff": "tier2_place",
            "retry_all": "tier2_place"
        }
    )
    
    workflow.add_edge("tier3_place", "tier3_review")
    workflow.add_conditional_edges(
        "tier3_review",
        lambda s: s["intermediate"].get("tier3_status"),
        {
            "pass": "output_result",
            "pass_with_issues": "output_result",
            "retry_diff": "tier3_place",
            "retry_all": "tier3_place"
        }
    )
    
    workflow.add_edge("output_result", END)
    
    return workflow.compile()

# 注册 workflow
register_workflow(
    function_id=21006,
    name="scene_composition_v2",
    workflow=create_scene_composition_workflow_v2(),
    description="分层场景组装（大件→从属→装饰）+ 差量修正"
)
```

---

继续修订后的文件清单：

### 新建文件（7 个）

### 修改文件（3 个）

### v1 完全不动（11 个文件）

```Plain Text
flows/scene_composition_workflow/
  ├── __init__.py
  ├── collect_models.py
  ├── compose_scene.py
  ├── import_to_engine.py
  ├── capture_screenshots.py
  ├── review_scene.py
  ├── output_result.py
  └── ...其他辅助文件
```

`/scene\_composition` 命令（function\_id=21005）保持原样，作为对照基线。

---

## 🎯 最后的几个关键检查点

在你 commit 之前，请逐项确认：

### 检查点 1：tier 之间的 state 传递契约

```Python
# tier1_place 必须输出
state["intermediate"]["tier1_actors"] = [
    {"name": "bed_01", "position": [...], "aabb_min": [...], "aabb_max": [...]},
    ...
]

# tier1_review 必须读取
state["intermediate"]["tier1_review"] = {"overall": "...", "problem_actors": [...]}

# tier2_place 必须读取
state["intermediate"]["tier1_actors"]  # 作为锁定列表
state["intermediate"]["tier2_items"]    # 待放置的从属物体
```

**行动项**：在 `nodes\_tier\_place\.py` 文件头写一段注释，明确每个 tier 节点的输入/输出契约。新增节点时不会因为字段名不一致导致 KeyError。

### 检查点 2：`MAX\_TIER\_RETRIES` 的总成本上限

```Python
MAX_TIER_RETRIES = 2  # 每层最多重试 2 次

# 最坏情况成本：
# tier1: 1 次初始 + 2 次重试 = 3 次 LLM + 3 次 VLM
# tier2: 1 次初始 + 2 次重试 = 3 次 LLM + 3 次 VLM
# tier3: 1 次初始 + 2 次重试 = 3 次 LLM + 3 次 VLM
# 总计: 9 次 LLM + 9 次 VLM = 18 次模型调用

# 单次成本估算:
# LLM 调用 ~5s + VLM 调用 ~10s + 拍 8 张截图 ~5s = 20s/层/次
# 最坏情况: 9 × 20s = 180s ≈ 3 分钟
```

**行动项**：在 `constants\.py` 里加一个 `WORKFLOW\_TIMEOUT\_S = 600`（10 分钟），超时强制结束并返回当前最优结果。

### 检查点 3：每个新工具的单元测试（不需要引擎）

```Python
# tests/test_place_object_near.py
def test_calculate_position_right():
    """不依赖引擎，纯函数测试"""
    ref_aabb = MockAABB(min=(-1, 0, -2), max=(1, 1.2, 0))
    pos = _calculate_position(ref_aabb, "right", 0.3, "center")
    assert pos == (1.3, 0, -1.0)  # max.x + gap = 1+0.3, center.z = -1

def test_calculate_position_above():
    ref_aabb = MockAABB(min=(0, 0, 0), max=(1, 1, 1))
    pos = _calculate_position(ref_aabb, "above", 0.1, "center")
    assert pos == (0.5, 1.1, 0.5)

# 6 个 relation × 至少 1 个测试 = 6 个测试用例
```

**行动项**：写一个 `MockAABB` 类，跑 6 个基础测试。**不用启动引擎，10 分钟搞定**，但能保证 `place\_object\_near` 的核心逻辑正确。

### 检查点 4：v1 和 v2 的入口路由

```Python
# 用户命令 → function_id 路由
/scene_composition       → 21005 (v1)
/scene_composition_v2    → 21006 (v2)
/full_pipeline           → 21000 (默认走 v1，保守)
/parallel_generate       → 21004 (默认走 v1)
```

**Phase 0 验证后**，如果 v2 失败率明显低于 v1，再考虑：

- `/full\_pipeline` 切到 v2

- `/parallel\_generate` 内部 `serial\_compose` 切到 v2

**行动项**：先**不要**改 `/full\_pipeline` 和 `/parallel\_generate` 的默认路由，保持向后兼容。等 v2 跑稳定后再切。

---

## ✅ 总结

你这一版方案已经把所有关键问题解决了：

---

## 🚀 你现在可以做什么

按以下顺序执行（**Phase 0 最重要，不要跳过**）：

```Plain Text
Day 1 (Phase 0 - 数据基线):
  □ 跑 5 个真实场景的 v1 (function_id=21005)
  □ 人工标注每个场景的失败模式
  □ 决策门:
      失败率 < 20% → 砍 tier3，只做 tier1 + tier_rest（合并 tier2/tier3）
      失败率 ≥ 20% → 完整三层方案

Day 2-3 (Phase 1 - 工具增强):
  □ 实现 3 个新工具
  □ 写 place_object_near 的单元测试（关键!）
  □ 改 VLM prompt 为结构化输出
  □ 验证 VLM 输出稳定性（跑 3 次同场景看一致性）

Day 4-6 (Phase 2 - 分层 DAG):
  □ Day 4: tier1_place + tier1_review + 差量修正
  □ Day 5: tier2_place + tier2_review (锚点工具集成)
  □ Day 6: tier3_place + tier3_review + 端到端串联

Day 7 (Phase 3 - 验证):
  □ 5 场景 v2 vs v1 对比测试
  □ 失败模式归档
  □ 决定是否切换默认路由
```

---



