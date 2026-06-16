# Codex 攻坚修改记录

> 维护规则：每次关键接线、语义修正、测试结果都记录到本文档，便于后续 AI 接手时快速判断当前状态。

## 执行计划（置顶）

### 总目标

本轮不是做“一句话一次性 AI 生成场景”，而是实现：

> 用户、AI 助手、Role Agent、GM/静默监听 Agent 共同维护同一个 SceneState，并在生成过程中持续磋商、介入、修正和确认。

UbiComp 叙事重点：

- 人机交互：用户可在生成过程中持续介入，而不是等待最终结果。
- 开放场景生成：任意需求拆成 `AssetPool + Zone/Anchor + SceneLayout`，不依赖固定模板。
- 协作治理：多人不同时乱写引擎，由 GM 整理意图、房主确认、host 单写者执行。
- 可靠性：放弃物理主路径，用 `AABB + VLM` 分层保证穿模、摆放和语义一致性。

### 全局原则

```text
SceneState 是唯一事实源
Prompt 只是 SceneState 的投影
生成可以并行
规划可以异步
引擎写入必须串行
用户介入不是打断流程，而是更新 SceneState
GM 不是替用户拍板，而是整理冲突、提出方案、请求确认
```

AI 执行铁律：

- 不允许 LLM/VLM/Role Agent 直接操作引擎。
- 所有引擎写入必须经过 `EngineWriteGate`，多人阶段经过 host single-writer。
- 不维护历史 prompt 作为状态；布局、审查、重排时从 SceneState 懒重建 prompt。
- 不把 `touched_by_user=True` 解释成永久锁死，必须结合 `intervention_round` 和 AABB 合理性。

### Day 1：单人优先

1. 元数据与写入收口
   - 复用 `SceneLayout/LayoutInstance`。
   - 保留 `intervention_round`、`protection_level`、`lock_level`。
   - `SceneSession` 持有 `current_round/pending_tasks/intervention_queue/operation_log/silent_gm_state`。
   - `EngineWriteGate` 收口 import/remove/transform/material/screenshot/settle。

2. 渐进生成与用户介入
   - 渐进路径默认启用，旧路径仅作为 `USE_PROGRESSIVE_COMPOSE=0` 回退。
   - 新增/使用 incremental import，只 add，不 clear。
   - phase 顺序：`GROUND -> SHELL -> INTERIOR -> BOUNDARY -> OBJECTS -> DECORATION`。
   - 每个 phase 末采样 viewport，scene-diff 捕获用户 move/add/delete。
   - Agent 导入后必须更新 diff baseline，避免误判为用户新增。

3. 保护策略
   - 最近 1-2 轮用户明确操作为 `HARD`，FinalReview 和 Agent 不自动覆盖。
   - 较早且合理的用户操作为 `SOFT`，尽量保留，冲突时请求确认。
   - 较早且不合理的用户操作为 `NONE`，可进入重排候选，但必须报告。
   - Agent 与用户冲突时 Agent 让位。

4. AABB + VLM
   - AABB 是内回路，检查 overlap、block doorway、out of zone、floating、hard user moved。
   - VLM 是外回路，只产 advisory，不阻塞主链路。
   - VLM 截图必须 timeout，失败 skip。

5. Role Agent
   - 内置长者、小女孩、山贼、学者、商人。
   - 支持用户自定义 persona。
   - 本阶段只影响聊天风格和轻量偏好，不进入深层 decompose。
   - Role Agent 只输出 proposal，不直接写引擎。

### Day 2：多人推进

1. LANChat host single-writer
   - guest 操作/指令发给 host。
   - host 通过 `EngineWriteGate` 执行。
   - 执行后广播 SceneDelta/Actor sync。

2. GM/静默监听
   - 基于 `SummaryService.monitor()` 输出 `DiscussionState`。
   - 结构化字段包括 pending intents、conflicts、constraints、required confirmations。
   - GM 负责语义冲突和顺序建议，不负责底层 race。

3. 权限与确认
   - 小操作自动执行。
   - 中/大操作 GM 提案 + 房主确认。
   - 投票只作为咨询展示，不作为 demo 主裁决路径。
   - guest 请求由 host 执行，但必须保留真实 `source_user_id`。

4. 多人冲突
   - 同一 actor 操作冲突：Actor version / lock 后续补齐。
   - 用户 vs Agent：用户优先，Agent replan。
   - 语义冲突：GM 提案并广播，房主确认。

### 当前成功标准

今天必须达到：

- 单人渐进生成默认可走。
- 用户中途介入能进入 SceneState 和 OperationLog。
- 最近用户操作不会被后续 batch 静默覆盖。
- AABB 能防主要穿模/挡门/越界。
- VLM 可接入且不会卡死主链路。
- Role Agent 可列出模板并注册自定义 persona。
- 静默监听能总结 pending/conflict/confirmation。

明天必须达到：

- LANChat 内模型和操作能同传。
- host 是唯一引擎写入者。
- GM 能识别语义冲突并提案。
- 房主能确认关键操作。
- 多人 provenance 不丢。

### 禁止项

```text
不要恢复物理 settlement 作为主路径
不要让 VLM 阻塞主链路
不要做完整 CRDT
不要做复杂投票裁决
不要让 Role Agent 直接写引擎
不要让 prompt 成为事实源
不要静默覆盖用户物体
不要对每次用户小编辑都调用 LLM/VLM
不要在渐进导入里复用清场式 import_to_engine_node
不要对根目录 E:\corona 建 CodeGraph 全仓索引
```

## 当前推进汇报

- 已完成单人主链路关键接线：渐进路径默认开启、incremental import 接入、scene-diff baseline 修复、OperationLog 落账、FinalReview 三分桶。
- 已完成可靠性底座：AABB 内回路测试通过，VLM 外回路 timeout/skip 测试通过。
- 已完成 Role Agent 最小可用入口：模板列表、自定义 role 注册、persona 注入聊天 system prompt。
- 已完成多人/GM 最小底座：`SummaryService.monitor()` 输出结构化讨论状态，`ChatServer` 能广播 pending intents / confirmation，`GMArbiter` 已接入 @agent 请求的轻量冲突提案路径。
- 尚未完成 F5 引擎实机验收、前端房主确认 UI、Actor version/lock、SceneDelta 标准化广播。

## 下一步推进

1. F5 验收单人渐进生成
   - 验证真实 `import_model` envelope 是否被 `parse_import_result` 正确解析。
   - 验证第二批导入不清第一批。
   - 验证用户中途移动后不会被后续 batch 误覆盖。

2. 补多人 host single-writer 的 SceneDelta
   - 定义最小事件：`ActorAdded/ActorMoved/ActorDeleted/GMProposal/HostConfirmationRequired`。
   - host 执行后广播结果，guest 只接受 confirmed delta。

3. 补房主确认闭环
   - 当前 GM 是“广播提案 + 默认确认”。
   - 下一步要让房主能确认/拒绝/修改顺序。

4. 补 Actor version/lock
   - 每个 actor 维护 `version/owner_user_id/last_touched_by/lock_owner/lock_expire_at`。
   - 后到操作 version 不匹配时进入冲突提示。

5. 继续维护本文档
   - 每轮关键接线、验收结果、风险和下一步都追加到下方日期记录。

## 2026-06-16

### 目标

- 落地“磋商式开放场景生成与多人/多 Agent 协作”方案的两天冲刺主链路。
- 优先保证单人渐进生成、用户介入保护、AABB/VLM 分层审查、Role Agent 注入。
- 继续推进 LANChat 侧 GM/静默监听与 host single-writer 的多人简化闭环。

### 当前接手事实

- `SceneLayout/LayoutInstance` 已有 `intervention_round` 与近因加权 `protection_level`。
- 已存在初版 `SceneSession`、`SceneDiffTracker`、`EngineWriteGate`、`incremental_import`、`consistency_check`、`vlm_review_loop`、`role_registry`、`gm_arbiter`。
- `SceneComposer.compose()` 已有 `USE_PROGRESSIVE_COMPOSE` 环境变量开关，但默认仍走旧的一次性路径。
- 需要优先修复渐进路径接线问题，避免“看似实现、实际跑不通”。

### 修改记录

- 初始化本文档，后续关键修改持续追加。
- 修复渐进导入接线：
  - `incremental_import` 兼容 `model_path/local_path`，避免模型检索产物无法导入。
  - `scene_composer_progressive` 修正 `helpers` 相对导入，并使用 `parse_import_result` 解析工具 envelope。
  - `SceneSession` 在每批 Agent 导入后调用 `SceneDiffTracker.baseline_add`，避免系统导入被误判为用户新增。
- 补齐运行时账本与写入白名单：
  - `SceneSession` 新增 `OperationLogEntry`、`operation_log`、`pending_tasks`、`silent_gm_state`。
  - 用户介入 drain 时记录 MOVE/ADD/SCALE/ROTATE/COLOR/DELETE 操作账本。
  - `EngineWriteGate` 增加 import/remove/transform/material/settle 语义化入口，降低后续工具绕过 gate 的概率。
- 将 `SceneComposer.compose()` 的渐进式路径默认开启；`USE_PROGRESSIVE_COMPOSE=0` 可显式回退旧路径。
- 调整 `PHASE_ORDER` 为 `GROUND -> SHELL -> INTERIOR -> BOUNDARY -> OBJECTS -> DECORATION`，确保装饰件后置。
- 改造 LANChat 静默监听：
  - `SummaryService` 新增 `DiscussionState` 与 `monitor()`，在保留 `compress()` 兼容的同时输出 pending/conflict/confirmation。
  - `ChatServer._maybe_compress()` 优先使用 monitor 结果，并在聊天室中提示待执行场景意图与房主确认项。
- 接入 GMArbiter 最小实际路径：
  - `ChatServer._dispatch_mentions()` 对 @agent/隐式场景请求做轻量 intent/target 抽取并入 GM 队列。
  - 检测到同物体语义冲突时广播 GM 提案；当前无前端确认 UI，demo 路径使用“广播提案 + 默认确认”。
- 暴露 Role Agent 模板入口：
  - `LANChat.list_role_templates()` 返回内置/自定义 role 模板。
  - `LANChat.register_custom_role()` 注册用户自定义 persona，并返回可用于 `add_agent(persona=key)` 的 role key。

### 自测记录

- 通过：`python editor/plugins/AITool/cai_extensions/data_model/test_protection_tiers.py`
- 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_diff.py`
- 通过：`python editor/plugins/AITool/cai_extensions/flows/scene_composition_workflow/test_incremental_import.py`
- 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
- `python -m py_compile ...` 因 Windows 拒绝写入 `__pycache__` 失败，改用无写入 `ast.parse` 检查；第二轮通过 7 个关键文件。
- GM 最小路径接入后复跑以上 4 个离线测试，全部通过。
- Role 模板入口接入后，`LANChat/main.py` 与 `role_registry.py` 的 `ast.parse` 通过，并复跑 `test_scene_session.py` 通过。
- 通过：`python editor/plugins/AITool/cai_extensions/agent/test_consistency_check.py`
- 通过：`python editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
- 最后一轮无写入语法检查通过 12 个关键文件，包括 `SceneSession`、渐进工作流、AABB/VLM、Role、LANChat GM 相关文件。
### 2026-06-16 追加：混合环境地形-建筑装配与穿模硬约束

- 针对通用方案链路新增重点判断：草原蒙古包只是代表 case，本质是 `terrain zone + main shell/box building + indoor/outdoor objects + connector clearance` 的混合环境装配问题。
- 修改 `scene_composer_progressive.reasonable_provider()`：
  - 从 `ZoneTree` 派生 `zone_aabb`，并按 `LayoutInstance.zone_id` 分组做 out-of-zone 检查，避免室外篝火/围栏被室内 zone 误判。
  - 从 `ZoneTree.connectors` 派生 door/passage clearance AABB，接入 `run_furniture_checks(..., door_aabbs=...)`，用于运行时防挡门。
  - 保留全局 overlap/floating 检查，作为防穿模主力。
- 增强 `_distribute_assets_to_phases()`：
  - 室内家具/地毯/桌椅/床默认写入 indoor zone，并把 shell zone 作为 `anchor_ref`。
  - 篝火/木柴/马/围栏等默认写入 outdoor terrain zone。
  - 装饰后置，并优先挂 indoor/shell anchor。
- 新增几何辅助函数：
  - `_infer_primary_zone_ids()`
  - `_collect_zone_aabbs()`
  - `_collect_door_clearance_aabbs()`
  - `_filter_aabbs_by_zone()`
- 新增离线测试 `test_scene_composer_progressive_geometry.py`，覆盖：
  - mixed environment zone 推断；
  - 资产分流写入 `zone_id/anchor_ref`；
  - door clearance AABB 派生；
  - AABB zone 检查按实例 zone 分组。
- 验证结果：
  - `python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py` 通过。
  - `python editor/plugins/AITool/cai_extensions/agent/test_consistency_check.py` 通过。
  - `python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py` 通过。
  - `python editor/plugins/AITool/cai_extensions/flows/scene_composition_workflow/test_incremental_import.py` 通过。
  - `ast.parse` 检查 `scene_composer_progressive.py` 与新测试通过。

风险/下一步：

- 当前地形仍按 flat/platform AABB 处理，尚未对 rolling/noise terrain 做高度采样；F5 前需要确认真实地形 actor 是否能提供可用 bounding box。
- 建筑 shell 与 terrain 的贴地/基座检查还需要进一步接入 infra 层：`check_shell_on_platform()` 已有，但 progressive runtime 尚未把 shell actor AABB 与 terrain/platform y 绑定。
- 下一步优先做 F5 验收：确认真实 `get_bounding_box()`、actor name、shell placement、door clearance 在引擎里是否一致。
