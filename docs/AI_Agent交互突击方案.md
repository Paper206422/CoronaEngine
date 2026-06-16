# AI Agent 交互突击方案（单人/AI助手 → 多人/多agent）

> 配套：[后续计划_渐进式与用户介入.md](后续计划_渐进式与用户介入.md)（上位框架）、[实施修改记录.md](实施修改记录.md)（改动溯源）
> 定位：这是一份**重点突击执行文档**，不是百科式规划。范围锁定"今天单人+AI助手三功能 / 明天多人+GM"，在已锁定的通用 Zone+phase+anchor 框架上叠加交互层。
> 原则：**保住当前通用组装效果（草原零回归）的前提下，叠加交互能力。**

---

## ⭐ 0. 自动化执行打标规约（automode 阅读契约 — 先读这节）

本文档每个任务都带机读标记。**在 automode（自主连续执行）下，这些标记是我的执行合同**——决定我能自己跑多远、何时必须停下交回给你。

| 标记 | 含义 | 对 automode 的作用 |
|------|------|-------------------|
| `⟦T-x.y⟧` | 稳定任务 ID | 进度跟踪 / TodoWrite 锚点 / 跨文档引用 |
| `⟦REUSE→file:sym⟧` | **复用已有代码，禁止重写** | 防"两套事实源打架"——见到此标直接接驳，不新建平行实现 |
| `⟦NEW→file⟧` | 新建文件/符号 | 明确产出物路径 |
| `⟦EDIT→file:line⟧` | 改已有代码（带锚点） | 直接跳到位置，不全文搜 |
| `⟦DEP:T-x.y⟧` | 前置依赖 | automode 拓扑排序，不跳序执行 |
| `⟦GATE:offline⟧` | 可离线自验（ast.parse/单测） | **automode 可自验自过，继续推进** |
| `⟦GATE:F5⟧` | 需人工 F5 验收 | **automode 必须停，写状态、交回给你** |
| `⟦DONE:...⟧` | 验收标准（尽量机读） | 自检通过条件 |
| `⟦RISK:...⟧` | 已知风险 | 提高谨慎度，改动后立即自验 |
| `⟦DECIDE:...⟧` | **需你拍板才能开工** | automode 遇此停下问，不替你决定 |
| `⟦SKIP⟧` | 本轮明确不做 | 防范围蔓延 |
| `⟦COMMIT:n⟧` | 小步提交分组 | 每组完成即可独立提交/回退 |

<!-- AUTOMODE-CONTRACT
执行优先级：先做所有 ⟦GATE:offline⟧ 且无 ⟦DECIDE⟧ 阻塞的任务（我能自验自过、连续推进），
在 ⟦GATE:F5⟧ 或 ⟦DECIDE⟧ 处停下、写状态交回。每完成一个 ⟦COMMIT:n⟧ 组就 ast.parse 自验。
铁律见 §10 禁止项 + §11 automode 执行协议。
-->

---

## 1. 现状地面真相（codegraph 实测，不是凭记忆）

落地前先钉死哪些已有、哪些全新——这决定了哪些是「接驳」（低风险）哪些是「新建」（高风险）。

### 已有，复用别重写

- `⟦REUSE→data_model/layout.py:SceneLayout⟧` **provenance 七字段全在**（provenance/owner_id/lock_level/touched_by_user/anchor_ref/batch_id/layout_status），自带 `list_by_provenance`/`list_locked`/`clear_agent_instances`。**这就是 G老师 spec 里的 `scene_actor_meta`/`ActorMetaStore`——不要新建平行字典**（违反「唯一事实源」铁律）。
- `⟦REUSE→mcp/tools/set_actor_transform.py⟧` 位/转/缩 工具，已注册。
- `⟦REUSE→mcp/tools/model_import_tools.py⟧` import + remove，已注册（import 时已 `set_physics_enabled(False)`）。
- `⟦REUSE→mcp/tools/place_object_near.py⟧` 相对摆放。
- `⟦REUSE→agent/agent_adapter.py:MasterAgent⟧` `__call__(system, messages)`：`system` 形参**就是 persona**。意图三分类 compose/edit/chat 已就位。
- `⟦REUSE→LANChat/server/room_manager.py:Agent⟧` `{agent_id,name,persona,owner}` + `Room._agents`；`⟦REUSE→chat_server.py:_dispatch⟧` 已按 `agent.owner==HOST` 把执行收口到房主机（**单写者底座半成**）。
- `⟦REUSE→services/ai_hint_service.py⟧` 12-persona-as-system-prompt 先例（role 影响说话风格的现成范式）。

### 全新，本轮新建

- `⟦NEW→agent/scene_session.py⟧` SceneSession 运行时（持有 SceneLayout + zone_tree + batch_id + 介入队列）。
- `⟦NEW→agent/engine_write_gate.py⟧` `_engine_lock` 收口 import/remove/transform/screenshot/settle。
- `⟦NEW→flows/.../incremental_import.py⟧` 只 add 不 clear 的渐进导入（现 `import_to_engine_node` 是清场式）。
- `⟦NEW→agent/scene_diff.py⟧` 轮询式视口 diff（命门解法，见 §2.1）。
- `⟦NEW→agent/role_registry.py⟧` role 模板注册表 + persona 注入。

### 命门（决定今天「用户自己拖拽」落不落地）

> `⟦RISK:viewport-capture⟧` **引擎→Python 没有 actor 变换事件**。`actor.py` 只有创建时 `_broadcast_actor_created`，没有「用户视口拖动→通知 Python」的反向事件；前端 store 只有 dockStore/lanchat，那些 `drag` 全是 Blockly 积木。所以 G老师的 `record_user_op` **今天没有调用者（针对视口拖拽）**。解法见 §2.1 路 A。

### 第二个独立卡死源（别假设没物理就不卡）

> `⟦RISK:vlm-screenshot-deadlock⟧` 物理求解器死循环已修（关物理）。但 **VLM 要截图，截图走引擎渲染同步**，是第二个独立卡死源——`_run_model_retrieval` 至今挂 `skip_six_view_capture=True` 正为绕它。接 VLM 第一件事是验截图路径不占主线程。

---

## 2. 今天：单人 + AI助手 三功能

### 2.1 功能① 渐进生成 + 随时介入（同步双向）

`⟦T-2.1⟧` 目标：生成在 phase 边界 yield，用户/AI 介入随时排队、phase 边界统一 drain 应用。**不做真抢占**（M4 最深、今天高风险），做 **phase 边界交错**——体感几乎一样，工作量差一个数量级。

**介入有两条通道，成熟度不同：**

- **AI 助手调工具**（@小B 把桌子挪开）`⟦GATE:offline⟧`：工具全有（set_actor_transform/remove/place_near）、LANChat 派发有 → 今天直接能做。
- **用户视口自己拖拽** `⟦RISK:viewport-capture⟧`：见命门。今天走 **路 A 轮询 scene-diff**。

**路 A —— 轮询式 scene-diff（命门解法，零 C++、零前端）** `⟦NEW→agent/scene_diff.py⟧` `⟦DEP:T-2.2meta⟧`：
- 每个 phase 边界对全场 `scene.get_actors()` 的 `get_position/scale/rotation` 拍快照，与上一张 diff。
- 变了 → `touched_by_user=True` + provenance=USER；消失 → user_deleted；新增 → provenance=USER。
- 代价：不是实时，是 phase 间粒度（渐进生成本就在 phase 间 yield，体感够）。
- `⟦DONE:offline⟧` 构造两张 actor 变换快照，diff 出移动/删除/新增三类，单测通过。

**主循环** `⟦NEW→agent/scene_session.py:progressive_compose⟧` `⟦DEP:T-2.1diff,T-2.2meta,T-2.4gate⟧`：
```
for phase in PHASE_ORDER:   # GROUND→SHELL→INTERIOR→BOUNDARY→DECORATION→OBJECTS
    generate_and_import_batch(phase)      # 经 EngineWriteGate
    yield_progress_to_ui(phase)           # 功能②的进度反馈复用此边界
    diff = scene_diff.poll()              # 路A：捕获用户视口介入
    drain_intervention_queue()            # AI工具介入 + 视口介入 统一应用
    if dirty: rebuild_prompt_lazily()     # 防抖：不是每次都 re-layout
    settle_current_batch_only()           # 只碰 AGENT && !touched && batch==current
final_review()                            # 只修 AGENT
```
`⟦GATE:F5⟧` `⟦DONE:F5⟧` 生成中拖动沙发→后续 batch 不覆盖；@小B 移物体即时生效；草原全程零回归。

### 2.2 功能① 的灵魂：近因加权保护（不是「碰过就永不能动」）

`⟦T-2.2meta⟧` `⟦REUSE→data_model/layout.py:SceneLayout⟧`（不新建平行字典）。

> **用户新增的关键修正（2026-06-16）**：不是「凡用户动过就永远锁死」，而是「**最近 1-2 轮明确意图强保护，早期/不合理介入允许被新的整体场景目标覆盖**」。明显不合理的早期介入，AI 助手应能重排整场布局。

把二值 `touched_by_user→HARD-forever` 升级成 **保护强度 = f(近因, 合理性)**，机读可判：

```
protection_level(actor) =
    HARD   if intervention_round >= current_round - 1        # 最近1-2轮：强保护，绝不自动动
    SOFT   if 合理(E5检查通过) and round 较旧                 # 早期但合理：尽量保留，冲突可让位
    NONE   if 不合理(E5-a/E5-b 判定穿模/挡门/超Zone/悬空)     # 早期且不合理：允许被整体重排覆盖
```

字段落点（复用 LayoutInstance，新增两个轻量字段，不抽新类）：
- `⟦EDIT→data_model/layout.py:LayoutInstance⟧` 加 `intervention_round: int`（用户介入时记当前轮次）+ 既有 `lock_level` 复用为 HARD/SOFT/NONE 的载体。
- `current_round` 由 SceneSession 持有，每轮渐进 batch / 每次显式「重新整理」自增。

**判定合理性** `⟦DEP:T-2.3aabb⟧`：复用功能②的 E5-a/E5-b 几何检查——介入后的物体若触发穿模/挡门/超 Zone/悬空，标 `不合理`→可被覆盖；通过则 `合理`→至少 SOFT。

`⟦DONE:offline⟧` 三档单测：最近轮 HARD 不被 settle 碰；早期+合理 SOFT 冲突时让位；早期+不合理 NONE 被整体重排覆盖。`⟦RISK:覆盖误伤⟧` 覆盖前必须产出报告（§2.5 FinalReview「需你确认」），不静默重排用户物体。

### 2.3 功能② AABB + VLM 防穿模 / 一致性 / 摆放合理

`⟦T-2.3⟧` **两个回路，绝不混在一条热路径**：

- **AABB = 内回路**（确定性、便宜、每次摆放都跑）`⟦T-2.3aabb⟧` `⟦GATE:offline⟧` `⟦NEW→agent/consistency_check.py⟧`：
  - E5-a 基础设施层：shell 落平台 / interior_surface 在 footprint 内 / boundary 围对 anchor / connector 通畅。
  - E5-b 家具层：AABB 穿模 / 挡门 / 超 Zone / 放错 Zone / 用户锁定物被移。
  - 放置前检查→不过就 nudge/夹回→再 commit。无 API、可单测、不烧 token。**这是防穿模主力。**
  - `⟦DONE:offline⟧` 构造重叠 AABB / 挡门洞 / 超 zone 三组，检查器各报对应 issue，单测通过。
- **VLM = 外回路**（语义、贵、异步、审查队列）`⟦T-2.3vlm⟧` `⟦DECIDE:vlm-tonight⟧` `⟦RISK:vlm-screenshot-deadlock⟧`：
  - 抓 AABB 抓不到的：朝向（兽头朝外）、语义摆放（电视朝沙发）、整体「看起来对不对」。
  - **产出修正建议，不阻塞放置**。生成后一遍 review。
  - **接入前必须先验截图路径不占主线程**——否则重蹈卡死。`⟦DECIDE⟧` 今晚是否接 VLM 取决于此验证；不通过则今晚只上 AABB 内回路，VLM 留明天。

### 2.4 功能③ 多 agent（注入 role）

`⟦T-2.4⟧` `⟦GATE:offline⟧` 几乎全是加法、不碰生成管线、低风险、demo 价值高。

- `⟦NEW→agent/role_registry.py⟧` role 模板注册表：内置 N 个（长者/小女孩/山贼/学者…）每个一段 persona system prompt；+ 用户自定义入口（文本框写 persona → 存成模板）。`⟦REUSE→services/ai_hint_service.py⟧` 的 12-persona 范式照搬。
- **role 注入点已通**：`⟦REUSE→LANChat/room_manager.py:Agent.persona⟧` → `chat_server` 派发带 persona → `⟦REUSE→agent_adapter.py:MasterAgent.__call__(system=persona)⟧`。但当前 persona 只用于**路由**（`_router.route`），**没进对话 LLM 的 SystemMessage**。
- `⟦EDIT→agent/agent_adapter.py:_handle_chat⟧` `⟦DEP:none⟧` 把 persona 线程进 chat 的 SystemMessage → role 真正影响**说话风格**（现在只影响路由）。
- `⟦DECIDE:role-depth⟧` role 只影响说话风格，还是也影响生成内容？**推荐今晚只做风格 + 一句场景倾向，不接进 decompose**（接进去与 M2 缠死）。
- `⟦DONE:offline⟧` 注册 3+ 模板 + 1 自定义；persona 注入 chat SystemMessage 的单测（同一问题不同 role 出不同语气）。

### 2.5 功能① 收尾：FinalReview（只修 AGENT，不静默覆盖用户）

`⟦T-2.5⟧` `⟦NEW→agent/scene_session.py:final_review⟧` `⟦DEP:T-2.2meta,T-2.3aabb⟧`

最后一轮只修 AGENT 物体；对用户物体按 §2.2 近因加权分档处理，**覆盖前必产报告**：

```
preserved（HARD/近因强保护用户物体）：只检查不动
adjusted（AGENT 物体）：穿模/挡门 → 自动 nudge / 让位
needs_confirm（早期+不合理用户物体）：报告给用户，问是否保留/允许重排
```

输出文案（给用户的，不是日志）：
```
已保留你最近的调整：沙发角度、地毯位置。
系统自动调整了：茶几前移 0.4m，避开沙发。
需要你确认：你早先放的落地灯挡住了门洞，是否允许我重新安排？
```

`⟦DONE:offline⟧` 三类分桶单测（preserved/adjusted/needs_confirm）；`⟦GATE:F5⟧` 报告文案在群聊正常显示。

---

## 3. 明天：多人 + 多agent（GM）

### 3.1 模型 + 操作 LAN 同传

`⟦T-3.1⟧` `⟦GATE:F5⟧` `⟦RISK:cjk-path-P0⟧`

- 模型同传：引擎 `_broadcast_actor_created` 已自动广播（任务 D-3）。host 分层节奏 = peer 到达节奏，**渐进传输几乎免费**。
- `⟦RISK:cjk-path-P0⟧` **中文模型路径 FILE_REQUEST 打不开**（`file_transfer.h:14` `std::filesystem::path(std::string)` 按 GBK 解码 UTF-8 中文字节）。同传一上来就撞它。**demo 临时绕过：用英文物体名**；正式修需重编引擎（`u8path`）。
- 操作同传：用户介入 = 改 Actor → 同样走广播。

### 3.2 GM 治理 —— 把两个被搅在一起的问题拆开

`⟦T-3.2⟧` `⟦DECIDE:gm-model⟧`

> **核心洞察：你把两个本质不同的问题搅在了一起，拆开后一个有干净答案、另一个才是真开放题。**

**问题(a) 写入串行化/冲突 —— 你的想法已经解决了：**
- 「用户A→指令→走房主渠道→小B执行」**就是单写者模型**。所有写入串行经房主机这一个点 → **真并发竞争（race）根本不发生**。
- 前后冲突（A移B删同一物体）→ 串行后是普通有序操作 + 锁检查。
- 同时冲突（A、B 同瞬间抓同物体）→ 经房主队列后**不存在「同时」**。
- **所以 GM 不负责解决 race（队列已解决）**，GM 只负责**语义冲突**（A刷红墙、B刷蓝墙这种互相矛盾的请求）。职责缩小一大圈。

**问题(b) 决策仲裁权 —— 真开放题，用桌游隐喻解：**

> 你在做的本质是 **TRPG / 桌游**。顺着这个隐喻，权限本来就不平等，玩家也不期待平等：
> - **GM = 地下城主**：编排、裁定、推进。最高「规则权威」。
> - **房主 = 桌主**：拥有这张桌、能掀桌拍板。最高「行政权威」。
> - **用户 = 玩家**：通过 role-agent 行动/提议，不期待与 GM/桌主平权。
>
> 隐喻一立，「所有人都想决定 GM」的焦虑消失——**玩家本来就不投票决定 DM 怎么裁定**。

| 决策模型 | 谁拍板 | demo 代价 |
|---------|-------|----------|
| 房主独裁 | 房主 | 非房主像观众 |
| GM 自治（DM）| GM 启发式自裁 | 用户可能觉得被牵着走 |
| 投票 | 全体 | **对 demo 最毒**：慢、平票死锁、拖垮节奏 |
| **混合（推荐）** | 无冲突直接跑；冲突时 GM 提案→房主确认；投票仅咨询 | 实现稍复杂，体验最佳 |

`⟦DECIDE:gm-model⟧` **推荐：GM 提案 + 房主确认，默认无冲突直接跑，投票只咨询不裁决。**
- 绝大多数请求不重叠（A东B西）→ 串行执行，GM 不出场。
- 真语义冲突（罕见）→ GM 给合并/排序提案 → 房主一个「确认/改」按钮拍板。
- 权限写死 GM > 房主 > 玩家，不做动态仲裁。**投票是 demo 最毒选项，先别做。**

`⟦DONE:F5⟧` 两用户分别 @小B 摆不冲突物体→都执行；制造语义冲突→GM 提案、房主确认。

---

## 4. 执行顺序 + 小步提交分组

> 原则（沿用昨晚锁定）：**先 adapter 后 prompt**、**生成器只读结构不读 legacy 字段**、**phase 不可乱序**、**F5 是唯一真验收**、**每组可独立回退**。
> 标 `⟦GATE:offline⟧` 的我可在 automode 连续自验自过；标 `⟦GATE:F5⟧` 的我必须停下交回。

```
═══ COMMIT 1：元数据 + 写入收口（零视觉变化，可连续自验）═══
⟦COMMIT:1⟧ ⟦GATE:offline⟧
  T-2.2meta  SceneLayout 接驳 + LayoutInstance 加 intervention_round/current_round   ⟦REUSE⟧
  T-2.4gate  EngineWriteGate（_engine_lock 收口 import/remove/transform/screenshot/settle）  ⟦NEW⟧
  → ast.parse + 三档保护单测 + 收口单测

═══ COMMIT 2：AABB 内回路 + role 注册表（独立、零 F5）═══
⟦COMMIT:2⟧ ⟦GATE:offline⟧
  T-2.3aabb  consistency_check E5-a/E5-b（防穿模主力）   ⟦NEW⟧
  T-2.4      role_registry + persona 注入 _handle_chat   ⟦NEW⟧+⟦EDIT⟧
  → 几何检查单测（穿模/挡门/超zone）+ role 语气单测

═══ COMMIT 3：渐进导入 + scene-diff（命门）═══
⟦COMMIT:3⟧ ⟦GATE:offline⟧→⟦GATE:F5⟧
  T-2.1diff  scene_diff 轮询式视口捕获（路A）   ⟦NEW⟧
  incremental_import（只add不clear）            ⟦NEW⟧
  → diff 三类单测；F5：第二批不清第一批

═══ COMMIT 4：主循环 + FinalReview（拼装，需 F5）═══
⟦COMMIT:4⟧ ⟦GATE:F5⟧
  T-2.1  progressive_compose phase 间 yield + drain 介入队列   ⟦NEW⟧
  T-2.5  FinalReview 三分桶 + 报告                              ⟦NEW⟧
  → F5：草原零回归 + 生成中拖动不被覆盖 + 报告显示

═══ COMMIT 5（条件）：VLM 外回路 ═══
⟦COMMIT:5⟧ ⟦DECIDE:vlm-tonight⟧ ⟦RISK:vlm-screenshot-deadlock⟧
  先验截图路径不占主线程 → 通过才接，否则留明天

═══ 明天 ═══
⟦COMMIT:6⟧ T-3.1 LAN 同传（⟦RISK:cjk-path-P0⟧ 用英文名绕）
⟦COMMIT:7⟧ T-3.2 单写者 + GM 语义冲突提案 + 房主确认
```

---

## 5. 借鉴 docs/后续计划 的可用部分（不重复造）

本文档**只取能直接落地的**，框架性内容仍以 [后续计划](后续计划_渐进式与用户介入.md) 为准：
- `PHASE_ORDER`（GROUND→SHELL→INTERIOR→BOUNDARY→DECORATION→OBJECTS）→ 本文 progressive_compose 的 yield 边界直接复用。
- E5-a/E5-b 两层一致性检查 → 本文 T-2.3aabb 直接复用。
- provenance 七字段 + SceneLayout → 本文 T-2.2meta 直接复用（不新建）。
- 任务 E 的 demo 必做子集（E1降级/E2进度/E6房主authority）→ 散入本文功能①②③。
- 单写者 + GM 桌游隐喻 → 本文 §3.2。

---

## 10. 禁止项（本轮铁律，automode 不得违反）

```
1. 不新建平行 actor 元数据字典——复用 SceneLayout（唯一事实源）
2. 不做真抢占式中断——只做 phase 边界交错
3. 不做完整 Command Bus / 多级优先级调度器
4. 不做 Portal / 动态透明 / 双渲染 / 全局物理沉降
5. 不让 review 阻塞主链路；VLM 是外回路，产建议不阻塞放置
6. 不让 prompt 成为事实源——prompt 从 SceneState 投影
7. 不让后续生成静默覆盖用户物体——覆盖前必产 needs_confirm 报告
8. 不每次用户编辑都触发 LLM/VLM——防抖 + phase 边界 drain
9. 不新增绕过 EngineWriteGate 的引擎写入口
10. 不改 decompose prompt 动摇草原（先 adapter 后 prompt）
11. 不碰 ai_setting.py / Quasar submodule pointer
```

## 11. automode 执行协议（怎么帮我更好地自主执行）

<!-- AUTOMODE-PROTOCOL -->
**自主推进的边界：**
1. **可连续做**：所有 `⟦GATE:offline⟧` 且无 `⟦DECIDE⟧` 阻塞、依赖已满足的任务。每个 `⟦COMMIT:n⟧` 组完成即 `ast.parse` + 跑该组单测自验。
2. **必须停下交回**：遇 `⟦GATE:F5⟧`（我验不了视觉/运行时）或 `⟦DECIDE:*⟧`（你的决定改变后续走向）。停下时写：已完成项 / 自验结果 / 卡在哪个 gate / 需你做什么。
3. **拓扑序**：按 `⟦DEP⟧` 排序，不跳序。COMMIT 1→2 可连做（都 offline），3 末尾撞 F5 停，4 起需 F5。
4. **每次改动后**：立即 `ast.parse` 自验；改 `⟦REUSE⟧` 标的代码前先确认没破坏既有调用方。
5. **范围闸**：`⟦SKIP⟧`/§10 禁止项是硬墙，宁可少做不可蔓延。

**三个 `⟦DECIDE⟧` 已拍板（2026-06-16 锁定）：**
- `⟦DECIDE:vlm-tonight⟧` → **今晚直接接 VLM**。⚠️ 我仍会把截图路径做防御性隔离（VLM 截图走渲染同步，是独立于物理的第二个卡死源；物理没了不代表渲染同步不卡）——接入时第一步验它不占主线程，超时即 skip 兜底。
- `⟦DECIDE:role-depth⟧` → **只影响说话风格 + 轻偏好**，不接进 decompose（避免与 M2 缠死）。
- `⟦DECIDE:gm-model⟧` → **GM 提案 + 房主确认，投票只咨询不裁决**。权限 GM>房主>玩家写死。

**我可以现在就开工的（零决策依赖、零 F5、纯上行）：** COMMIT 1（T-2.2meta + T-2.4gate）+ COMMIT 2 的 role_registry。你同时去 F5 收口昨晚两个 demo bug（AITool 容错 + P1 存库竞态），在干净基线上汇合。
<!-- /AUTOMODE-PROTOCOL -->
