# 场景生成 Agent 系统技术架构方案

> UbiComp Workshop：多人联机 Agent 场景生成  
> 基于 CoronaEngine v2 管线，简化部署复杂度，单机全量运行

---

## 一、系统概述

### 1.1 核心设计

```
┌─────────────────────────────────────────────────────────┐
│                     CoronaEngine 主机                     │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│  │ 用户 A    │  │ 用户 B    │  │ 用户 C    │               │
│  │ 本地Agent │  │ 本地Agent │  │ 本地Agent │               │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘               │
│        │              │              │                      │
│        └──────────────┼──────────────┘                      │
│                       │                                     │
│              ┌────────▼────────┐                            │
│              │   EventBus      │  (asyncio.Queue)           │
│              │   事件/操作同步  │                            │
│              └────────┬────────┘                            │
│                       │                                     │
│              ┌────────▼────────┐                            │
│              │   群 Agent      │  (GPT-5.5, 复用 DMXAPI)    │
│              │   讨论总结      │                            │
│              │   风格守护      │                            │
│              └─────────────────┘                            │
│                                                           │
│  复用 v2 管线: Constraint Solver / VLM Review / 3D 生成   │
└─────────────────────────────────────────────────────────┘
```

### 1.2 设计原则

1. **去中心化协同**：每个本地 Agent 独立决策，群 Agent 不强制干预
2. **用户主权**：用户可突破风格限制，Agent 建议但执行用户决定
3. **单机运行**：全部逻辑在一台引擎主机上完成，无需外部服务
4. **复用 v2**：Constraint Solver / VLM Review / 3D 生成直接复用

### 1.3 与 v2 的关系

| 组件 | v2 (现有) | Agent 方案 (新增) |
|------|----------|------------------|
| LLM 推理 | DMXAPI GPT-5.5 | 复用 |
| Constraint Solver | `constraint_solver.py` | 复用 |
| VLM Review | `nodes_tier_review.py` | 复用 |
| 3D 生成 | Hunyuan3D | 复用 |
| 意图理解 | ❌ | **新增** |
| EventBus | ❌ | **新增** (asyncio.Queue) |
| Memory | ❌ | **新增** (2 层) |
| 群协同 | ❌ | **新增** |

---

## 二、简化架构决策

> 原方案涉及 Redis Streams / PostgreSQL / Qdrant / 本地 7B LLM / A100 集群。  
> Workshop 阶段简化为单机内存方案，LLM 全部复用 DMXAPI。

### 2.1 消息总线：asyncio.Queue

```python
class EventBus:
    """极简事件总线 — 单机内存, 不需要任何外部依赖"""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._history: list[dict] = []

    def publish(self, event: dict):
        self._history.append(event)
        for q in self._queues.values():
            q.put_nowait(event)

    def subscribe(self, user_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self._queues[user_id] = q
        return q

    def replay(self, since_index: int = 0) -> list[dict]:
        return self._history[since_index:]
```

### 2.2 Memory：4 层 → 2 层

```
L1 Session Memory:  当前会话对话 + 最近 N 次操作 (内存)
L2 Scene Memory:    Style Bible + 操作日志 (当前场景, dict)

删除:
L3 User Preference: Workshop 不跨项目, 不需要
L4 RAG Knowledge:   设计规范用 Prompt 注入, 不需要向量库
```

### 2.3 对比

| 组件 | 原方案 | 简化版 |
|------|--------|--------|
| 消息总线 | Redis Streams + 持久化 | `asyncio.Queue` (0 依赖) |
| Memory 存储 | PostgreSQL + Qdrant | 内存 dict |
| 本地 LLM | 7B CPU 推理 | DMXAPI GPT-5.5 (已有) |
| 群 Agent | 70B + 2×A100 | DMXAPI GPT-5.5 (已有) |
| 部署 | 5 台服务器 | 1 台引擎主机 |

---

## 三、核心工作流

### 3.1 本地 Agent：单用户场景编辑

```
用户: "在吧台旁边加个金属高脚凳"
  │
  ▼
┌─ 1. 意图理解 (LLM) ──────────────────────────┐
│ 解析动作: add                                  │
│ 提取物体: 高脚凳                                │
│ 空间关系: near → 吧台                           │
│ 推断分区: bar_area                             │
│ 风格检查: 继承 Style Bible                      │
└────────────────────────────────────────────────┘
  │
  ▼
┌─ 2. 操作生成 ─────────────────────────────────┐
│ Constraint Solver:                             │
│   object=高脚凳, relation=near, target=bar_001  │
│   → position={x,y,z}                           │
│                                                │
│ 3D Prompt 融合 Style Bible:                    │
│   "cyberpunk weathered metal bar stool..."     │
└────────────────────────────────────────────────┘
  │
  ▼
┌─ 3. 本地验证 ─────────────────────────────────┐
│ 依赖检查: 无依赖 ✓                             │
│ 空间冲突: 计算 bbox, 无重叠 ✓                   │
│ 风格预判: 继承全局风格 ✓                        │
└────────────────────────────────────────────────┘
  │
  ▼
┌─ 4. 乐观执行 ─────────────────────────────────┐
│ 更新本地场景状态                                │
│ 触发 3D 渲染 (占位符先行, 异步生成高模)         │
│ 发布 add_object 事件到 EventBus                │
└────────────────────────────────────────────────┘
```

### 3.2 群 Agent：讨论总结

```
聊天记录 → 提取场景相关发言 → 积累用户意图 → 计算共识度
  │
  ▼
触发条件 (满足任一):
  - 所有人都发言
  - 核心要素 >60% 一致
  - 超时 3 分钟
  │
  ▼
LLM 方案总结:
  - Style Bible: {theme, colors, materials, mood, avoid}
  - 场景骨架: {scene_name, type, zones}
  - 输出到群聊, 等待用户确认
```

### 3.3 群 Agent：风格守护

```
操作事件流 → 累计偏离计数
  │
  ▼
巡检触发 (满足任一):
  - 操作累计 10 次
  - 偏离计数 ≥ 3
  - 用户主动请求
  │
  ▼
VLM 批量评估 → 风格一致性评分 → 报告 + 建议 → 等待决策
```

---

## 四、Agent 增强设计

### 4.1 多 Agent 编排 (Harness 模式)

```
┌────────────────────────────────────────────┐
│              Agent Coordinator             │
│   任务分解 → Sub-Agent 调度 → 结果聚合      │
└────────────────┬───────────────────────────┘
                 │
   ┌─────────────┼─────────────┐
   ▼             ▼             ▼
Intent Agent  Spatial Agent  Style Agent
(意图理解)    (空间推理)     (风格校验)
   │             │             │
   └─────────────┼─────────────┘
                 ▼
           Tool Layer
   ┌─────────┬─────────┬─────────┐
   │Solver   │VLM      │3D Gen   │
   └─────────┴─────────┴─────────┘
```

**Coordinator 流程**：

```python
class AgentCoordinator:
    def handle(self, user_text: str):
        # 1. 并行: 意图 + 记忆 + 风格预检
        intent, context, style = await gather(
            self.intent_agent.analyze(user_text),
            self.memory.recall(),
            self.style_agent.precheck(user_text),
        )
        # 2. 串行: 空间推理 (依赖意图结果)
        spatial = self.spatial_agent.solve(intent, scene, context)
        # 3. 冲突检测
        if conflicts := self.check(spatial):
            return self.ask_user(conflicts)
        # 4. 构建 + 执行 + 广播
        op = self.build(intent, spatial, style)
        self.execute_and_broadcast(op)
```

### 4.2 Chain-of-Thought 推理

```
用户: "在吧台和沙发之间放个茶几，但不要挡住走道"

传统: {position: {x: 5, y: 0, z: 3}}  ← 可能不合理

CoT:
  步骤1: 识别参照物 — 吧台{2,0,1}, 沙发{8,0,5}, 走道{x:4-6,z:2-4}
  步骤2: 计算中点 — {5,0,3}, 但中点在走道内 ❌
  步骤3: 偏移 — 候选A{3,0,3}(靠吧台), 候选B{7,0,3}(靠沙发)
  步骤4: 选择 — B, 茶几应靠近沙发
  → {position: {x: 7, y: 0, z: 3}}
```

### 4.3 Self-Reflection 自我反思

```
操作生成后, 执行前:

  ├─ 这个操作符合用户真实意图吗?
  ├─ 位置在物理上合理吗? (悬空/穿模/超界)
  ├─ 会破坏现有场景吗? (依赖/遮挡)
  ├─ 风格是否一致? (vs Style Bible)
  └─ 是否有更好的替代?

  置信度 > 90% → 直接执行
  置信度 60-90% → 执行但标记
  置信度 < 60% → 询问用户
```

### 4.4 Multi-Step Planning 多步推理

```
用户: "把酒吧布置得更有氛围感"

Step 1: 需求分解 — "氛围感" → 光照 + 装饰 + 空间层次
Step 2: 评估现状 — 仅顶灯, 无装饰, 平面化
Step 3: 子任务 — 壁灯/灯带 → 墙面装饰 → 小装饰 → 优化现有物
Step 4: 优先级 — 光照(最大影响) → 墙面 → 细节 → 优化
Step 5: 逐步执行 — Task1 → 预览 → 确认 → Task2 → ...
```

### 4.5 CoT vs Multi-Step 决策逻辑

```
用户输入 → 复杂度判断
  ├─ 简单指令 (单一物体, 单一关系)
  │   "加个椅子", "把灯往右移"
  │   → CoT 深度推理 → 直接执行
  │
  └─ 复杂需求 (多物体 / 模糊意图 / 跨区域)
      "把酒吧布置得更有氛围感"
      → Multi-Step 分解 → 子任务规划 → 逐步执行
```

### 4.6 歧义处理

**常见歧义场景**：

| 用户说 | 可能含义 | 歧义来源 |
|--------|---------|---------|
| "旁边" | 左/右/前/后 ? | 方向模糊 |
| "大一点" | 放大 10%? 50%? 2倍? | 量级模糊 |
| "那种风格" | 哪种? 需要上下文 | 指代不明确 |
| "这里" | 空间位置? 物体附近? | 空间参照模糊 |

**处理策略**：

```python
class DisambiguationHandler:
    def resolve(self, intent, confidence):
        if confidence > 0.9:       # 高置信度 → 直接执行
            return intent
        elif confidence > 0.6:     # 中等 → 执行但标记, 事后可撤销
            intent.metadata.needs_review = True
            return intent
        else:                       # 低置信度 → 追问用户
            return self.ask_clarification(intent.ambiguities)
```

**示例**：

```
用户: "把这个放大一点"
Agent: "当前物体 scale=[1,1,1], 建议放大到 [1.3, 1.3, 1.3] (增加30%),
       还是 [2.0, 2.0, 2.0] (翻倍)?"
       → 提供候选选项让用户快速确认
```

---

## 五、协同感知

**核心问题**：用户 A 如何感知用户 B 正在做什么？多人同时操作时如何避免"盲操作"？

### 5.1 操作意图预览

```
用户A 输入: "在吧台旁边加个高脚凳"
  │
  ▼
意图理解阶段 → 提取: action=add, target=高脚凳, near=吧台
  │
  ▼
在用户B/C 的视图中显示半透明预览:
  ┌─────────────────────────────────────┐
  │ 🔵 用户A 正在吧台旁放置 "高脚凳"      │
  │    目标位置预览: [半透明轮廓]         │
  └─────────────────────────────────────┘
```

### 5.2 协同状态广播

```python
# EventBus 发布轻量状态事件
{
  "event_type": "user_intent",
  "user_id": "user_a",
  "status": "placing_object",     # typing | placing | moving | confirming
  "tooltip": "正在吧台旁放置高脚凳",
  "preview_position": {"x": 3.5, "y": 0, "z": 1.2}
}
```

### 5.3 冲突前移

```
用户A: "把椅子往左移"    → 椅子 #chair_03
用户B: "删除这把椅子"    → 同一把 #chair_03

传统方案: 各自执行 → 冲突后回滚
改进方案: 用户B 选中 #chair_03 时,
         引擎检测到用户A 正在操作该物体,
         → 显示 "⚠️ 用户A 正在移动此物体, 请稍候"
```

### 5.4 最小实现 (Workshop)

```
1. 物体选中态: 引擎侧高亮, 显示操作者名字
2. 操作意图预览: 半透明占位符 + 用户标签
3. 冲突锁: 操作中的物体短暂锁定 (自动释放)
4. 状态栏: "用户A: 添加高脚凳 | 用户B: 移动吧台"
```

---

## 六、评估方案

### 6.1 Workshop Demo 场景

```
任务: 3 人 5 分钟内协同生成一个 "赛博朋克酒吧"

用户角色:
  - 用户A: 负责大件布局 (吧台/桌椅/沙发)
  - 用户B: 负责灯光氛围 (霓虹灯/壁灯/灯带)
  - 用户C: 负责装饰细节 (酒瓶/挂画/植物)

流程:
  1. 群Agent 讨论总结 → Style Bible 确认 (1min)
  2. 用户A 放置锚点物体 → 冲突协同测试 (2min)
  3. 用户B/C 并行添加 → 风格守护触发 (2min)
  4. 群Agent 巡检报告 → 用户确认/调整 (1min)
```

### 6.2 评估指标

| 指标 | 测量方法 | 目标 |
|------|---------|------|
| **意图理解准确率** | 人工标注: Agent 执行是否匹配用户意图 | >85% |
| **冲突检出率** | 并发操作冲突被检测 / 实际冲突总数 | >90% |
| **风格一致性评分** | VLM 整体评分 (复用 v2 的 0-100) | >75 |
| **操作响应时间** | 输入 → 预览出现 | <3s |
| **用户满意度** | 5 点 Likert 量表 (事后问卷) | >4.0 |
| **协同效率** | 3 人完成任务时间 vs 单人完成 ×3 | >40% 节省 |

### 6.3 对比基线

| 基线 | 方法 |
|------|------|
| Baseline A | 无 Agent 辅助，纯手动操作 |
| Baseline B | 单用户 + Agent (无协同) |
| Proposed | 3 用户 + Agent 协同 |

预期结果：Proposed 在效率和满意度上显著优于 Baseline A，在风格一致性上优于 Baseline B。

---

## 七、Memory 系统

```
┌──────────────────────────────────────┐
│ L1: Session Memory (内存)            │
│  - 当前会话对话历史                    │
│  - 最近 N 次操作                      │
│  - 待解决冲突                         │
│  会话结束清空                         │
├──────────────────────────────────────┤
│ L2: Scene Memory (dict)              │
│  - 当前场景完整状态                    │
│  - Style Bible                        │
│  - 操作日志 (本场景)                   │
│  场景级持久化 (可选: 存到 scene.json)   │
└──────────────────────────────────────┘
```

**Memory-Augmented 示例**：

```
用户第1次: "加个椅子" → 放 seating_area 中心
用户第2次: "加个椅子" → 记忆中上次放了桌子旁 → 推断同样的桌子旁
用户第3次: "加个椅子" → 连续3把围绕同张桌子 → 推断在布置就餐区
                                 → 主动问: "继续围绕这张桌子布置?"
```

---

## 八、数据模型

### 6.1 Style Bible

```json
{
  "theme": "cyberpunk wasteland",
  "color_palette": ["#1a1a2e", "#16213e", "#0f3460", "#e94560"],
  "materials": ["weathered metal", "neon glass", "concrete"],
  "lighting": "low ambient + colored neon",
  "mood": "dystopian, gritty, vibrant",
  "avoid": ["pastoral", "bright", "medieval"]
}
```

### 6.2 Scene IR

```json
{
  "scene_id": "scene_001",
  "scene_name": "cyberpunk_bar_01",
  "scene_type": "indoor",
  "style_bible": { /* 继承或覆盖 */ },
  "zones": [
    {"zone_id": "bar_area", "function": "service"},
    {"zone_id": "seating_area", "function": "social"}
  ],
  "objects": {
    "bar_001": {
      "name": "吧台",
      "zone": "bar_area",
      "role": "anchor",
      "position": {"x": 2, "y": 0, "z": 1},
      "dependencies": []
    }
  }
}
```

### 6.3 Event

```json
{
  "event_id": "uuid",
  "event_type": "add_object | delete_object | move_object | modify_object | init_project | style_alert",
  "timestamp": 1234567890.123,
  "user_id": "user_a",
  "scene_id": "scene_001",
  "data": {
    "object_id": "stool_001",
    "object_data": { "name": "高脚凳", "position": {...}, "zone": "bar_area" }
  },
  "metadata": {
    "confidence": 0.87,
    "style_deviation": false
  }
}
```

---

## 九、室内外统一方案

### 7.1 Adapter 模式

```
ISceneAdapter (统一接口)
  ├─ IndoorAdapter:  墙体约束 / 天花板 / 家具规则 / 人工光源
  ├─ OutdoorAdapter: 地形约束 / 环境物体 / 自然光
  └─ HybridAdapter:  协调室内外边界 (门窗、视线)

意图识别 → 自动分区:
  "室内" / "墙上" / "天花板" → indoor
  "室外" / "门口" / "街道" → outdoor
  无明确提及 → 根据物体类型推断
```

### 7.2 风格一致性：三层防护

```
第一层: Prompt 注入 (生成时)     → 源头控制, ~90% 符合
第二层: VLM Review (生成后)      → 捕获剩余偏离
第三层: 群 AI 巡检 (定期)        → 发现累积的风格漂移
```

### 7.3 场景命名

```
规则: {风格}_{功能}_{序号}

讨论: "做个赛博朋克酒吧, 有室内和门口"
  → scene_name: cyberpunk_bar_01
  → partition_1: indoor_main
  → partition_2: outdoor_entrance
```

---

## 十、开发路线图

### Phase 1：单用户增强（2-3 周）

| 周 | 任务 |
|----|------|
| W1 | 意图理解 Agent + EventBus + L1/L2 Memory |
| W2 | Self-Reflection + CoT 推理集成 + Style Bible Prompt 注入 |
| W3 | 联调测试, 单用户自然语言场景编辑 |

### Phase 2：多人协同（2-3 周）

| 周 | 任务 |
|----|------|
| W4 | 群 Agent 讨论总结 + 共识计算 |
| W5 | 风格守护巡检 + 冲突检测 |
| W6 | 多人联调, Workshop demo 准备 |

### Phase 3：完善（可选）

- Multi-Step Planning
- 室内外 Adapter
- 性能优化

---

## 十一、风险与应对

| 风险 | 概率 | 应对 |
|------|------|------|
| LLM 意图理解错误 | 中 | Self-Reflection + 用户确认 |
| 并发冲突 (多人编辑同一物体) | 中 | 冲突检测 + 用户提示 |
| 风格漂移 | 中 | 三层防护 + 定期巡检 |
| 推理延迟 (多次 LLM 调用) | 中 | 并行调用 + 缓存常见模式 |
| 截图卡顿 (引擎 bug) | 高 | 4 角度 + 延迟 + 超时跳过 |

---

## 十二、与现有 v2 管线的关系

```
/sc_v2 --test (现有, 继续维护)
  └─ 离线批处理: Prompt → 模型生成 → 场景组装 → VLM 审查

/sc_agent (新增, Workshop 目标)
  └─ 在线交互: 自然语言 → 意图理解 → Solver → 实时预览
                 ↑                        ↑
            复用 Constraint Solver    复用 _apply_corrections
            复用 VLM Review           复用 3D 生成 API
            复用 _apply_default_scale  复用 _apply_physics_settlement
```

**关键区分**：
- v2 管线解决的是"从零生成一个场景"（批处理，~5 分钟）
- Agent 方案解决的是"用自然语言编辑场景"（交互式，<3 秒）

两者共用底层的 Solver / VLM / 3D 生成 / 物理沉降，上层流程不同。

---

*文档完成。基于 CoronaEngine v2 管线，面向 UbiComp Workshop 多人联机场景生成。*
