# Codex 攻坚修改记录

## 2026-06-17 追加：室内 skin 自动派生兜底

- 回应 F5 反馈“房间不是应该自动派生皮肤吗”：上一轮只把 `floor/wall/ceiling` 三套材质槽位接通，但缺字段时仍回落到 `neutral`，视觉上仍可能单一。
- 新增 `_derive_room_skin_materials(surface_params, style_context)`：优先尊重 `interior_surface.floor_material/wall_material/ceiling_material/accent_material`，缺失时从开放式 `style_context.material_palette/materials/surface_palette` 和材质词派生，不按“教堂/书房/卧室”等场景身份写死分支。
- `_generate_room_box()` 改为使用派生结果写入 `box.mtl`，因此纯室内 5 面盒子在 LLM 只给材质调性或只给地板材质时，也会自动形成基础地面/墙面/顶面组合。
- 新增 `test_room_box_skin_is_derived_from_open_material_context`，覆盖 `wood+fabric` 自动派生和 `floor_material=marble` 自动补墙/顶的兜底。
- 验证：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py` 通过；相关 AST 检查通过。

> 维护规则：每次关键接线、语义修正、测试结果都记录到本文档，便于后续 AI 接手时快速判断当前状态。

## 执行计划（置顶）

### 总目标

本轮不是做“一句话一次性 AI 生成场景”，而是实现：

> 用户、AI 助手、Role Agent、GM/静默监听 Agent 共同维护同一个 SceneState，并在生成过程中持续磋商、介入、修正和确认。

UbiComp 叙事重点：

- 人机交互：用户可在生成过程中持续介入，而不是等待最终结果。
- 开放场景生成：任意需求拆成 `AssetPool + Zone/Anchor + SceneLayout`，不依赖固定模板。
- 通用混合环境：地形外皮由主建筑/场景语义驱动，建筑尺度决定平台和地形范围，避免只服务草原蒙古包特例。
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

5. 通用混合环境地形/建筑链路
   - `ZoneTree` 的 terrain zone 必须携带或推导 `TerrainProfile`。
   - `TerrainProfile` 包括 `type/material/scatter/style_tags`，由主建筑/场景语义驱动。
   - 主建筑 shell/box 的 footprint 决定 terrain 中心平台和地形范围。
   - terrain 材质和散布层不得写死草地；蒙古包、木屋、帐篷、沙漠建筑、山寨营地等都走同一套 profile 映射。
   - F5 验收重点：主建筑不埋入/悬空于地形，门洞 clearance 不被物体挡住。

6. Role Agent
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
- 地形能根据主建筑/场景语义生成对应 profile、材质和散布层，并为主建筑保留平台。
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
- 已完成通用混合环境增强：`TerrainProfile` 支持主建筑/场景语义驱动的地形类型、材质、散布层；离线测试覆盖蒙古包/木屋/沙漠等 profile 映射。
- 尚未完成 F5 引擎实机验收、前端房主确认 UI、Actor version/lock、SceneDelta 标准化广播。

## 下一步推进

1. F5 验收单人渐进生成
   - 验证真实 `import_model` envelope 是否被 `parse_import_result` 正确解析。
   - 验证第二批导入不清第一批。
   - 验证用户中途移动后不会被后续 batch 误覆盖。
   - 验证地形 profile 材质/散布层是否在引擎中正确显示。
   - 验证 shell/box 主建筑与 terrain 平台贴合，不悬空、不埋地、不穿模。

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

### 2026-06-16 追加：地形跟随主建筑风格生成

> **【Claude 校对追加 2026-06-16】本段为历史记录，已被后续「M2 去特殊化 / 半开放 ZoneAspect 注册表」段修正**：`_infer_terrain_style()` 的关键词地形推导已删除，当前代码不再从 shell/name 关键词推导草地/沙地/雪地；地形风格改由 LLM decompose 输出的 `ground_profile` aspect 驱动，缺失时返回中性 `flat/neutral/none`。下文保留原始记录仅供溯源。

- 更新置顶执行计划：新增“通用混合环境地形/建筑链路”，把 `TerrainProfile` 作为 terrain zone 的语义外皮，要求跟随主建筑/场景风格。
- 扩展 `TerrainProfile`：
  - 新增 `material`、`scatter`、`style_tags`。
  - 继续保留 `type/amplitude/frequency/seed` 作为确定性高度场参数。
- 更新 `ZoneTree` 分解 prompt：
  - 要求 terrain zone 输出 `terrain_profile`。
  - 明确示例：蒙古包/游牧/草原、森林木屋、雪地帐篷、沙漠建筑、山寨/营地/岩地。
- 新增本地兜底推导：
  - `_terrain_profile_from_spec()`
  - `_infer_terrain_style()`
  - 即使 LLM 没有输出 `terrain_profile`，也会从 `shell_asset/name` 推导草地、沙地、雪地、林地、岩地等。
- 地形生成接入 profile-driven material/scatter：
  - `_generate_terrain()` 不再写死 `grass.mtl`，改为根据 `profile.material` 写 terrain MTL。
  - 散布层根据 `profile.scatter` 输出草/花、灌木、岩石、雪斑等不同颜色倾向的 billboard 材质。
- 新增离线测试 `test_terrain_style_profile.py`，覆盖：
  - 蒙古包/游牧语义 -> rolling grass flowers。
  - 森林木屋语义 -> noise dirt shrubs。
  - 沙漠语义 -> dunes sand shrubs。
  - LLM 显式 terrain_profile 优先于本地推导。
  - terrain OBJ/MTL 使用 profile-driven material。
- 验证结果：
  - `python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py` 通过。
  - `python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py` 通过。
  - `ast.parse` 检查 `scene_composer.py`、`zone_tree.py`、`test_terrain_style_profile.py` 通过。

风险/下一步：

- 目前 scatter 几何仍复用 billboard 草簇结构，只通过材质区分灌木/岩石/雪斑；F5 可接受，但后续如有时间应补不同 scatter mesh。
- 真实引擎材质加载是否读取同目录 `mtllib terrain_style.mtl` 仍需 F5 验证。

### 2026-06-16 追加：LANChat C++ Network 合并后的 Agent/GM 重接

- 接受远端架构：LANChat 房间、消息、成员、agent roster、trigger、lock、intent 由 C++ `NetworkSystem` 作为唯一事实源。
- 不恢复旧 Python `chat_server.py / summary_service.py`。
- 新增 AITool 侧 Python 语义层：
  - `services/lanchat_summary_service.py`
  - `services/lanchat_agent_orchestrator.py`
- `LANChatAgentWorker` 从直接调用 role agent 改为调用 `LanChatAgentOrchestrator`：
  - 更新静默监听摘要；
  - 普通请求走 role agent；
  - GM/冲突/大操作请求生成 GM proposal；
  - 房主回复“确认/拒绝/按方案A”消费 pending proposal。
- C++ Python binding 新增最小桥接：
  - `network_lanchat_history_snapshot(limit)`
  - `network_lanchat_agents_snapshot()`
  - `network_send_system_message(sender_id, sender_name, text)`
- `editor/plugins/LANChat/server/gm_arbiter.py` 改为历史兼容 no-op，不再尝试集成已删除的 Python chat server。
- 验证结果：
  - `python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py` 通过。
  - Python AST 检查 `lanchat_agent_worker.py`、`lanchat_agent_orchestrator.py`、`lanchat_summary_service.py`、`test_lanchat_agent_orchestrator.py` 通过。

风险/下一步：

- C++ binding 尚需完整 C++ 编译验证。
- 前端房主确认当前仍是“聊天室文字确认”v1，后续再补按钮 UI。
- GM proposal 当前只回写聊天消息，尚未真正串到场景工具执行队列；下一步要接 host single-writer 的场景 command。

### 2026-06-16 追加：boundary 从开关升级为参数化边界能力

- 修正 boundary 半通用问题：
  - 之前已做到“无 `boundary` aspect 不生成围栏”，但生成器内部仍只会木栏。
  - 现在 `boundary.params.kind/material/height/style` 都进入 manifest 与 decompose prompt。
- 生成器改造：
  - `_build_fence_obj()` 继续作为环形边界纯函数，但新增 `kind` 和 `height` 参数。
  - 当前支持 `fence`、`wall`、`hedge` 三类基础几何分流。
  - 新增 `_boundary_mtl_text(kind, material)`，支持 `wood/stone/greenery/neutral` 等材质倾向。
  - `_generate_fence()` 改为读取 `boundary` aspect 参数；无 aspect 不调用，有 aspect 才按参数生成 `__terrain_boundary`。
- 测试补充：
  - `test_boundary_params_drive_kind_material_and_height()` 验证 `wall/stone/1.8` 和 `hedge/greenery/0.8` 参数真正影响 OBJ/MTL。
- 自测结果：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`ast.parse` 检查 3 个关键文件。
  - 通过：`git diff --check`，仅剩 Windows LF/CRLF 提示。

### 2026-06-16 追加：style_context 支撑开放场景动态参数选择

- 将“根据开放式场景主建筑和地形风格动态确定类型/材质/需求”收口到规划层：
  - `Zone` 新增 `style_context: Dict`。
  - decompose prompt 新增 `style_context` schema：`main_building`、`terrain_mood`、`material_palette`、`functional_intent`。
  - prompt 明确要求 LLM/GM 根据用户需求、主建筑、地形气质、时代/文化/功能意图填写 `ground_profile / ground_cover / boundary / entrance / interior_surface` 的 params。
  - 代码不按 `main_building/terrain_mood` 写 if，只保存上下文并执行 aspect params。
- 运行时接线：
  - `_build_zone_tree()` 将 LLM 输出的 `style_context` 存入 `zone.style_context`。
  - `_shell_generation_hint()` 透传 `material_palette` 和 `terrain_mood` 到 shell 模型生成 prompt，增强主建筑与环境风格一致性。
  - 入口样式仍只来自 `entrance` aspect；无 aspect 不猜毡帘/拱门/木门。
- 测试补充：
  - `test_style_context_is_preserved_without_code_inference()` 覆盖火山口观测站场景：
    - `style_context` 被保存；
    - 未声明 `boundary/ground_cover` 时不生成；
    - `lava_flow` 进入 `unsupported`；
    - shell prompt 透传 metal/concrete/volcanic research site；
    - 不出现毡布/布帘类全局默认。
- 自测结果：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`ast.parse` 检查 3 个关键文件。
  - 通过：`git diff --check`，仅剩 Windows LF/CRLF 提示。

### 2026-06-16 追加：M2 去特殊化 / 半开放 ZoneAspect 注册表

- 按终审放行条件修正上一轮“关键词推导地形”的方向错误：
  - `zone_tree.py` 新增 `ZoneAspect{capability, params}`、`CAPABILITY_MANIFEST`、`GENERATOR_MANIFEST`。
  - manifest 当前覆盖 6 项：`ground_profile`、`ground_cover`、`boundary`、`interior_surface`、`entrance`、`shell_dressing`。
  - `unsupported` 不进入 manifest；未知 capability 统一归入 `ZoneAspect(capability="unsupported")`，记录 requested/reason/params，不崩。
- 删除场景关键词式地形兜底：
  - 移除 `_infer_terrain_style()` 的关键词 if-elif 路线。
  - `_terrain_profile_from_spec()` 只兼容显式 legacy `terrain_profile`；缺失时返回 `flat/neutral/none`。
  - `TerrainProfile` 默认从 `grass/grass` 改为 `neutral/none`，避免 legacy adapter 误生成草覆盖。
- 四个写死点已接入 aspect/manifest：
  - `ground_profile`：terrain 的 type/amplitude/frequency/material/extent_factor 由 aspect params 驱动；`building_extent * 6.0` 改为 `extent_factor`，默认 6.0。
  - `entrance`：删除全局 `_SHELL_ENTRANCE_HINT`，入口提示只来自 `entrance` aspect；无 aspect 时不再默认给蒙古包/帐篷毡帘、拱门等场景身份提示。
  - `interior_surface`：`_generate_interior_floor()` 不再硬编码 `floor_mat="carpet"`；默认 neutral，显式 aspect 可给 stone/wood/carpet。保留 shell footprint 派生和 `INSCRIBE=0.96`，不动几何贴合链路。
  - `ground_cover/boundary`：`ground_cover` 和 `boundary` 都是 opt-in；无 aspect 不调用散布层和 `_generate_fence()`。gate 放在调用边界，生成器本体只保留几何能力。
- 保持 `PHASE_ORDER = ["GROUND", "SHELL", "INTERIOR", "BOUNDARY", "OBJECTS", "DECORATION"]` 不变，未引入装饰提前的回归。
- 测试更新：
  - 替换旧 `test_terrain_style_profile.py`，删除“蒙古包/木屋/沙漠关键词命中 profile”的错误断言。
  - 新增覆盖：manifest shape、PHASE_ORDER 不变、unknown capability -> unsupported、显式 aspect 覆盖 legacy、火山口观测站中性默认、ground_cover/boundary opt-in、entrance/interior_surface aspect 驱动。
- 自测结果：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_consistency_check.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/flows/scene_composition_workflow/test_incremental_import.py`
  - 通过：`ast.parse` 检查 4 个关键文件。
  - 通过：`git diff --check`，仅剩 Windows LF/CRLF 提示，无 whitespace error。
- 合并门仍然是 F5 实机，不以离线全绿替代（**【Claude 校对追加 2026-06-16】三场景→四场景**，第 4 场景专门验 M2-2 的 ZoneVolumeAnchor/PlatformAnchor，前三场景全有 shell 只走 ShellAnchor 验不到）：
  - 草原蒙古包：看 rolling 起伏、草/花覆盖、围栏、入口、地板贴边和主体建筑贴地。
  - 欧式教堂：看无草、无栅栏、非毡帘、石板/中性地面。
  - 火山口观测站：看不崩、unsupported 正确记录、没有 fallback 草地。
- **纯室外营地/集市/广场（有围栏无可进入建筑）**：LLM 输出 boundary aspect + 无 shell → 边界/地表能落地；这是唯一触发 M2-2 纯室外分支的场景。

### 2026-06-16 追加：M2-2 resolve_zone_anchor 接入当前硬编码生成路径

- 实现 `resolve_zone_anchor(composer, zone, capability)`，三态顺序为：
  - `ShellAnchor`：优先使用 `_shell_aabb` 的真实 shell footprint，保持草原蒙古包等已有 shell 场景路径不回归。
  - `PlatformAnchor`：无 shell footprint 但存在 terrain platform 时，使用 `_platform_radius` 作为边界/地表参照。
  - `ZoneVolumeAnchor`：纯室外无 shell、无 platform 时，使用 zone volume 生成边界参照，解决营地/集市/广场这类无可进入建筑场景无法生成 boundary 的断点。
- `_generate_fence()` 已从直接读取 `_shell_aabb` 改为读取 resolved anchor；无有效 anchor 时才跳过。
- `_run_original_workflow()` 的 boundary 调用点已接入 `resolve_zone_anchor()`，即 M2-2 落在当前 `framework -> shell -> interior_floor -> boundary` 硬编码路径上，不依赖已降级的未来 `dispatch_aspects`。
- 离线测试补充：
  - `test_resolve_zone_anchor_preserves_shell_path()`：验证 shell 场景继续使用真实 footprint。
  - `test_resolve_zone_anchor_supports_platform_and_pure_outdoor_volume()`：验证 platform 与纯室外 zone volume 均可作为 boundary anchor。
- F5 合并门保持四场景：草原蒙古包、欧式教堂、火山口观测站、纯室外营地/集市/广场。第四场景专门验 M2-2 的 Platform/ZoneVolume 分支。

### 2026-06-16 追加：M2-2 hardening / boundary anchor 风险收口

- 修正 ShellAnchor center 风险：
  - `resolve_zone_anchor()` 的 ShellAnchor 不再使用 `zone.volume.center` 作为 boundary 落点。
  - 当前 `_place_shells()` 固定将 shell actor 放在世界原点，因此 ShellAnchor 默认 center 为 `[0, 0, 0]`；未来如支持多建筑 offset，可由 `_shell_aabb` 增加 center 字段承接。
  - 新增测试覆盖 shell zone volume center 非原点时，ShellAnchor center 仍不偏移，避免草原蒙古包围栏被 terrain/zone center 带偏。
- 修正 ZoneVolumeAnchor 半径策略：
  - `resolve_zone_anchor()` 新增 `params` 输入。
  - 纯室外 boundary 优先读取 `boundary.params.radius`；无显式 radius 时使用 `min(width, depth) / 2 - margin`，默认 `margin=1.0m`，并保留最小半径保护。
  - 删除测试中 `ring_radius == 7.0` 的裸常数断言，改为验证默认贴近 zone 内缘和显式 radius 覆盖。
- 收窄 M2-2 真实迁移范围：
  - 本轮 anchor 迁移只覆盖 `boundary/_generate_fence`。
  - `_generate_interior_floor()` 仍只服务 shell zone，继续从 shell footprint 派生；这不是本轮 anchor 迁移对象。
  - ground_cover 散布层仍在 `_generate_terrain()` 内按 terrain volume/platform 计算，未走 `resolve_zone_anchor()`。
- F5 必查新增：
  - 草原蒙古包：围栏必须仍套住蒙古包中心，不能因 zone/terrain center 产生平移。
  - 纯室外营地/集市/广场：围栏相对营地物体位置必须合理，不切穿主体物体，也不能只是在空地中央生成一圈。

### 2026-06-16 追加：M2-3 shape-aware fit Tier 1 / interior floor shape

- `interior_surface.params` 增加 `floor_shape`，并加入 `GENERATOR_MANIFEST["interior_surface"].effective_params`。
- decompose prompt 明确：
  - 圆形/帐篷类内皮可输出 `floor_shape=disc`。
  - 矩形/教堂/房间类内皮可输出 `floor_shape=quad`。
  - 代码不按场景关键词判断，只执行 aspect params。
- 新增 `_select_interior_floor_shape(width, depth, surface_params)`：
  - 显式 `floor_shape=disc|quad` 优先。
  - 无显式 shape 时，只用宽深比做几何兜底：明显长条矩形走 `quad`，接近方形保持 `disc`，以保护蒙古包零回归。
- `_generate_interior_floor()` 改为按 `floor_shape` 选择 `_build_disc_obj()` 或 `_build_floor_obj()`；保留 shell footprint 派生和 `INSCRIBE=0.96`，不改贴合缩放链路。
- 离线测试补充：
  - manifest 记录 `floor_shape`。
  - 显式 `quad/disc` 生效。
  - 宽深比兜底只处理明显长条，近方形默认 disc。
- F5 必查：
  - 草原蒙古包：仍为圆/椭圆地面且贴边。
  - 欧式教堂：需要 decompose 输出 `interior_surface.floor_shape=quad`，F5 看方形/矩形地面是否贴合。
  - 本轮仍是 Tier 1；不规则 footprint / convex hull / 多边形地面留深水项。

### 2026-06-16 追加：M2-4 降级说明与 M2-F5 准备

- M2-4 `dispatch_aspects` phase 分桶派发明确降级为深水项，不阻塞 M2-F5：
  - 当前 `framework -> shell -> interior_floor -> boundary` 硬编码路径已覆盖草原蒙古包、欧式教堂、火山口观测站、纯室外营地四个 F5 场景的必要生成顺序。
  - 后续如果增加新的 capability generator，再做 `dispatch_aspects`，并必须按 `PHASE_ORDER` 分桶派发，不能按 LLM 输出的 aspects 数组顺序执行。
  - `unsupported` 只进入 backlog/report，不进入执行派发。
- 补齐 boundary 参数声明：
  - `GENERATOR_MANIFEST["boundary"].effective_params` 新增 `radius/margin`。
  - decompose prompt 的 `boundary.params` schema 新增 `radius/margin`。
  - 纯室外场景中，LLM/GM 可显式给 `radius` 控制围栏范围；未给时由 `zone size - margin` 推导。
- 当前 M2 离线侧剩余工作：
  - 代码路径已到 M2-F5 门口；不继续堆叠未 F5 验证的生成能力。
  - 下一步应进行四场景 F5，重点核查 decompose JSON 与实机场景一致性。

### 2026-06-16 追加：M2-F5 decompose JSON 快照

- `SceneComposer.decompose_zone_tree()` 在成功构建 `ZoneTree` 后，会自动保存一份 F5 用 JSON 快照。
- 快照位置：
  - 系统临时目录下的 `corona_m2_f5_decompose/<scene_name>_<timestamp>.json`。
  - `compose()` 返回结果新增 `zone_decompose_snapshot`，便于从 F5 结果/日志中直接定位。
- 快照内容：
  - `prompt`：原始用户请求。
  - `raw_zones`：LLM 原始 decompose 输出。
  - `normalized_zones`：经过 `normalize_zone_aspects()` 后的 zone/aspects/volume/style_context。
- 用途：
  - 草原蒙古包：核查 boundary 是否来自 aspect，围栏中心 F5 是否套住 shell。
  - 欧式教堂：核查 `interior_surface.floor_shape=quad` 是否真实输出。
  - 纯室外营地：核查 `boundary.radius/margin` 与 `zone.size` 是否能解释围栏位置。

### 2026-06-16 追加：M2-F5 snapshot 字段检查脚本

- 新增只读脚本 `docs/probes/m2_f5_snapshot_check.py`。
- 用法：
  - `python docs/probes/m2_f5_snapshot_check.py <zone_decompose_snapshot> <scene_kind>`
  - `scene_kind` 可取 `grass_yurt / church / observatory / outdoor_market / auto`。
- 作用：
  - 自动打印 snapshot 内 zone/aspect 概览。
  - 草原蒙古包：检查 rolling grass、ground_cover、boundary、disc floor。
  - 欧式教堂：检查无 ground_cover、无 boundary、`floor_material=stone`、`floor_shape=quad`、无毡帘偏置。
  - 火山口观测站：检查非 grass fallback、unsupported 记录。
  - 纯室外集市：检查无 shell、boundary 存在、radius/margin 是否显式。
- 该脚本只读 snapshot，不触引擎、不改仓库状态；用于 F5 后快速判定 decompose JSON 是否过门。

### 2026-06-16 追加：M-Demo 单人渐进链路可观测性

- `run_progressive_workflow()` 现在把 `SceneSession` 的 phase 进度通过 `progress_events` 返回给上层，而不是只写日志。
- 渐进结果新增：
  - `final_report_text`：`FinalReviewReport.to_user_text()` 的用户可读文案，便于 F5/聊天侧直接展示；
  - `operation_log` / `operation_count`：用户介入、视口 diff、AI 工具介入在 phase 边界落账后的可序列化记录；
  - `round`：当前渐进生成轮次。
- 目的：
  - F5 时可以区分“生成阶段未执行”“用户介入未捕获”“FinalReview 未产出文案”“视觉摆放失败”四类问题；
  - 不改变 M2 生成策略、不新增场景特化逻辑，只补 demo 验收和排障所需的观测出口。
- 离线测试补充：
  - `test_scene_session.py` 新增进度 sink + FinalReview 文案可观测断言。

### 2026-06-16 追加：多人 GM proposal 到 confirmed intent 的最小接线

- `AgentOrchestrationResult` 新增 `action_payload`，保持原有 `text/sender/proposal` 行为兼容。
- GM 提案时结构化保存：
  - `proposal_id`
  - `source_user_id`
  - `target_agent_id`
  - `intent_text`
  - `pending`
  - `conflicts`
  - `requires_host_confirm`
  - `execution=host_single_writer`
- 房主文字确认后：
  - `action_payload.status` 从 `pending_host_confirmation` 变为 `confirmed`；
  - 保留真实 `source_user_id`，不把 guest 请求伪装成房主请求。
- `LANChatAgentWorker` 在 C++ binding 提供 `network_broadcast_intent()` 时，广播 `confirmed_gm_action`，让 C++ NetworkSystem/前端能够看到“已确认、待 host 单写执行”的意图。
- 边界：
  - 本轮仍不直接调用场景工具，不绕过 EngineWriteGate；
  - 还没有完成 `confirmed_gm_action -> EngineWriteGate -> SceneDelta` 的最终执行队列。
- 离线测试补充：
  - `test_lanchat_agent_orchestrator.py` 覆盖 GM proposal payload、房主确认 payload、worker 广播 confirmed GM action。

### 2026-06-16 追加：M-Demo 单人结果回传到聊天侧

- `_handle_scene_compose()` 现在会把 `SceneComposer.compose()` 的新增观测字段展示给用户：
  - `progressive/phases_run`：显示渐进阶段；
  - `progress_events`：显示最近阶段进度；
  - `operation_count`：显示本轮捕获到的用户介入数量；
  - `final_report_text`：显示 FinalReview 用户可读检查结果；
  - `zone_decompose_snapshot`：显示 M2-F5 decompose JSON 快照路径。
- 目的：
  - 单人 M-Demo F5 时，聊天侧可以直接看到渐进主循环、介入捕获、FinalReview 和 decompose snapshot 是否接上；
  - 不需要用户翻日志判断链路是否运行。
- 边界：
  - 本轮只补展示和排障信息，不改变生成、布局或引擎写入策略。

### 2026-06-16 追加：M-Demo VLM 外回路接入渐进结果

- `run_progressive_workflow()` 现在在渐进导入完成后调用 `vlm_review_loop.review_models_async()`。
- 接入方式：
  - 使用已有 `model_reviewer._capture_single_model()` 作为截图函数；
  - 使用已有 `model_reviewer._vlm_review_model()` 作为 VLM 审查函数；
  - 截图经 `EngineWriteGate.screenshot()` 收口；
  - 默认最多审查前 4 个导入 actor，可用 `PROGRESSIVE_VLM_MAX_TARGETS` 调整。
- 返回字段新增：
  - `vlm_review`
  - `vlm_review_text`
  - `vlm_review_skipped`
  - `vlm_review_timed_out`
- 聊天侧展示：
  - `_handle_scene_compose()` 会展示 VLM 外审文案；
  - 若截图/VLM 跳过或超时，会显示跳过数和超时数。
- 边界：
  - VLM 仍是外回路 advisory，不阻塞主生成链路；
  - VLM 不直接修改场景，不覆盖用户物体；
  - 工具缺失、截图失败、VLM 异常均 skip，不影响 M-Demo 主链路。

### 2026-06-16 追加：M-Demo 阶段披露 / 进度条数据

- `SceneSession.progressive_compose()` 新增 `progress_timeline`。
- 每个实际执行 phase 会产生两条结构化进度：
  - `status=start`：阶段开始，包含 `phase / percent / message`；
  - `status=done`：阶段完成，包含 `phase / percent / asset_count / imported_count / message`。
- 百分比按本次实际执行的 phase 数计算，单阶段为 `0 -> 100`，多阶段按阶段边界递增。
- `run_progressive_workflow()` 将 `progress_timeline` 返回给上层。
- `_handle_scene_compose()` 在聊天侧展示当前阶段百分比，同时保留完整 timeline 供前端渲染进度条/阶段列表。
- 目的：
  - 生成过程中分阶段披露状态，降低用户等待焦虑；
  - F5 时可确认渐进生成不是黑盒等待，而是能看到 `GROUND/SHELL/INTERIOR/BOUNDARY/OBJECTS/DECORATION` 等阶段推进。

### 2026-06-16 追加：LANChat 添加 Agent 快速模板入口

- `RoomPanel.vue` 的“添加 AI 助手”弹窗新增快速模板按钮：
  - 长者
  - 小女孩
  - 山贼
  - 学者
  - 商人
- 点击模板会自动填充：
  - `agentForm.name = 模板名`
  - `agentForm.persona = 模板名`
- 添加仍复用已有 `lanchat.addAgent({ name, persona })`，不新增 C++/Python binding。
- 后端 `RoleRegistry.resolve(persona)` 已支持按模板名解析，因此 persona 传“长者/小女孩/山贼”等即可命中内置模板。
- 自定义角色仍保留原 textarea：用户可直接输入自定义 persona 文本作为临时自定义人格。
- 验证：
  - 轻量静态检查确认 `roleTemplates/selectRoleTemplate` 已存在；
  - `npm` 被 PowerShell 执行策略拦截，改用 `npm.cmd` 后发现当前前端依赖环境缺少可执行 `eslint`，因此未跑完整 lint。

### 2026-06-17 追加：修复 CAIApp JSON 信封被误过滤导致聊天空回复

- 问题：
  - `_call_caiapp()` 直接把 `AITool._cai_app.chat(req)` 返回的 chunk 当纯文本拼接。
  - CAI stream chunk 实际是 `build_success_response()` 生成的 JSON 信封，顶层固定包含 `session_id/error_code/status_info`。
  - 旧 `_INTERNAL_CHUNK_MARKERS` 包含这些信封字段，导致每个正常 chunk 都被误判为内部工具结果并过滤，最终落到“✅ 已完成你的调整。”兜底。
- 修复：
  - 新增 `_extract_cai_text_chunk()`，逐 chunk `json.loads()` 后提取 `llm_content[].part[].content_text`。
  - `_call_caiapp()` 改为使用该 helper 拼接用户可见文本。
  - 从 `_INTERNAL_CHUNK_MARKERS` 移除 `session_id/error_code/status_info`，保留 `__room_/__shell_/__terrain_/remaining_actors/removed_actor/imported_actor` 等真实内部工具噪声特征。
- 验证：
  - 新增 `test_agent.py` 断言：包含 `session_id/error_code/status_info` 的正常 CAI 信封可提取“真实回复”。
  - 定向 helper 检查通过。
  - 完整 `test_agent.py` 在 Windows 下仍失败于既有 `/tmp/_test_agent_mem.json` 写入权限，不是本次改动引入。
### 2026-06-17 追加：F5 急救修复包（chat / AABB / VLM / general 语义 / 单人操作路由）

- Chat 回复读取：
  - `_extract_cai_text_chunk()` 扩展为同时支持 JSON 字符串、dict、`data/message/payload/response` 包装层。
  - 只抽取 `llm_content[].part[].content_text`、`content_text/text/content/delta` 等自然语言字段，不再把 `session_id/status_info` 当内部工具噪声误过滤。
  - 新增 `test_cai_text_extraction.py` 覆盖标准 CAI 信封、嵌套 stream event、空 status envelope。
- 用户介入 / AABB / FinalReview：
  - `scene_composer_progressive.py` 不再调用不存在的 `scene_manager.get_active_scene()`。
  - 新增 `_get_current_scene()`，按现有公开 API `scene_manager.get("") -> list_all()/get(route)` 获取场景。
  - 快照采集从 `actor.name/get_name()` 兼容读取；AABB 采集从 `actor.get_bounding_box()` 或 `actor._geometry.get_aabb()` 兼容读取。
  - `_collect_aabbs()` 改用 `scene.get_actor()`，避免旧的 `get_actor_by_name()` 断点。
- VLM 外回路：
  - `model_reviewer.py` 修正 helper import 路径为 `..flows.scene_composition_workflow.helpers`。
  - 解决运行时 `No module named 'plugins.AITool.cai_extensions.scene_composition_workflow'` 导致 VLM 全跳过的问题。
- 开放场景 general 语义防线：
  - `normalize_zone_aspects()` 增加 ground_cover 清洗：`stone/marble/slate/pavement/tile/concrete` 等基础铺装材质不再作为散布层生成。
  - 被误放入 `ground_cover` 的基础材质会转入 legacy `ground_profile.material` 兜底；真正的 flowers/grass/snow/debris 等覆盖物不受影响。
  - 新增 `_looks_same_scene_asset()`，用于保守识别 `欧式教堂` vs `教堂`、`yurt shell` vs `yurt` 这类 shell 主建筑重复普通物体。
  - `SceneComposer.compose()` 在 shell 资产补齐后剔除主建筑重复 object，避免“外壳教堂 + 室内普通教堂”重复导入。
- 单人 @AI 增删改路由：
  - `LanChatAgentOrchestrator._needs_gm_proposal()` 调整为：单人/无冲突重大操作不再自动进入 GM proposal，而是回到普通 role agent / MasterAgent 工具通道。
  - 多人冲突、显式 @GM、多人重大操作仍保留 GM 仲裁。
  - `_is_multi_user()` 对 `sender_id` 与 history 中 `sender_name/from` 做归一化，避免同一用户被误判为两人。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`ast.parse` 只读语法检查关键 5 个 Python 文件。
  - 未通过：`python -m py_compile ...` 因 Windows `__pycache__` 目标文件拒绝访问，属于 pyc 写入权限/锁问题；已用只读语法检查替代。
- F5 复测重点：
  - “你好 / 我有一个大计划”这类 chat 必须有自然语言回复。
  - 生成后拖动物体，`operation_count` 应该能增加，FinalReview 不应再因 AABB 空采集而虚假全 0。
  - 教堂广场 snapshot 不应再有 `ground_cover.kind=stone`；引擎不应铺设 stone/grass/flower 散布簇。
  - `欧式教堂` 作为 shell 后，不应再把 `教堂` 当普通 object 放进室内。
  - 单人 @普通 AI 助手执行删除/移动/添加时，不应只出现 GM proposal 空转。

### 2026-06-17 追加：多人 GM/Host Single-writer 执行队列 v1
- 问题：
  - 之前多人 GM 链路已经能生成 `action_payload`，房主文字确认后也能广播 `confirmed_gm_action`。
  - 但确认后的 action 仍停在“网络可见意图”，没有进入 host 侧执行队列，也没有经过 `EngineWriteGate`。
- 本轮推进：
  - 新增 `LanChatHostActionExecutor`：
    - 维护 host 侧 confirmed action 队列；
    - `enqueue()` 广播 `queued_host_action`；
    - `process_next()` 广播 `executing_host_action`，并在 `EngineWriteGate.run()` 内执行已确认 action；
    - 成功后生成 `HostActionExecutionResult(event_type="SceneDelta")`，广播 `host_action_executed`，并通过 `network_send_system_message()` 发出 host 执行结果；
    - 失败时返回 `CommandRejected`，广播 `host_action_failed`，不吞异常。
  - `LANChatAgentWorker` 接入 host executor：
    - 保留原有 `confirmed_gm_action` 广播；
    - 广播失败不再阻塞执行队列；
    - 只有 `payload.status=="confirmed"` 才会入队执行；
    - 保留真实 `source_user_id`，不把 guest 请求伪装成房主。
  - 默认执行策略：
    - 不在 executor 内把自由文本硬解析成删除/移动等危险低层命令；
    - 将已确认 intent 交给 host 侧 agent callback，并把 callback 包在 `EngineWriteGate.run()` 内，保证 host single-writer；
    - 后续可以把 callback 替换成更明确的 SceneDelta/ActorAdded/ActorMoved/ActorDeleted 执行器。
- 边界：
  - 当前 `SceneDelta` 是 Python 执行结果 payload + LANChat intent/system message 可见性，不是新的 C++ typed SceneDelta 协议。
  - C++ binding 已有 `network_broadcast_intent()` / `network_send_system_message()` 可复用；真正的 ActorMoved/ActorDeleted typed 广播仍需后续补 C++/前端协议。
- 验证：
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`ast.parse` 检查 `lanchat_agent_worker.py / lanchat_host_action_executor.py / test_lanchat_agent_orchestrator.py`

### 2026-06-17 追加：多人/多 Agent 与开放场景链路校验
- 校验范围：
  - 用户 @AI 助手 / 不 @ 直接发消息；
  - 单人普通 role agent vs 多人 GM 仲裁；
  - 多 Agent role 模板与软偏好注入；
  - 场景意图分类：`compose / edit / chat`；
  - M2 `ZoneTree + ZoneAspect` 分解；
  - terrain / shell / interior floor / boundary 的锚定链；
  - ground_cover / boundary opt-in；
  - AABB 内回路、VLM advisory 外回路；
  - 渐进阶段披露与进度消息。
- Python 层结果：
  - `LanChatAgentOrchestrator`：单人重大增删改移不再被 GM proposal 吞掉；多人冲突、显式 @GM、多用户重大操作仍进入 GM。
  - `LANChatAgentWorker`：agent 调用期间可通过 `agent_progress_sink()` 发送阶段进度，最终仍发送 summary reply。
  - `LanChatHostActionExecutor`：房主确认后的 payload 进入 host queue，并在 `EngineWriteGate.run()` 内执行，执行状态通过 LANChat intent/system message 可见。
  - `RoleRegistry`：内置长者/小女孩/山贼/学者/商人模板可解析；自定义 persona 可作为 adhoc role 注入；compose path 中 role 只作为软偏好，不作为代码侧场景分类。
  - `SceneComposer`：开放式生成继续走 LLM `decompose_zone_tree()` + manifest/adapter，代码侧没有恢复“按场景关键词推地形参数”的分支。
  - decompose prompt 收紧：
    - `ground_cover.kind` 示例不再包含 `stone`，避免把基础铺装误诱导成散布层；
    - 明确 `stone/marble/slate/pavement/tile/concrete` 属于基础地面材质，不属于 ground_cover；
    - 明确 `RoleAgent 软偏好` 不是用户新增物体清单，`object_bias` 不应自动加入 aspects/items。
  - `scene_composer_progressive`：progressive path 已补 post-shell framework hook，shell 放置后仍生成 interior floor 与 opt-in boundary，避免渐进路径漏掉锚定链。
- 已通过的 Python/离线测试：
  - `python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - `python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - `python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - `python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - `python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - `python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - `python editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
  - `python editor/plugins/AITool/cai_extensions/flows/scene_composition_workflow/test_incremental_import.py`
  - `ast.parse` 检查关键 Python 文件通过。
- 底层边界：
  - `LANChatState` 现在有“单个本地 agent 时，无 @ 消息隐式触发；多个 agent 时必须显式 @”的 C++ 代码尝试与 C++ test 变更。
  - 但按当前推进策略，不运行 C++/Ninja 构建验证；该能力必须在 F5/底层专项中确认，不作为 Python 层已闭环能力。
- F5 仍需确认：
  - 草原蒙古包：围栏中心套住主建筑，地形起伏/草地/入口/地板贴合合理；
  - 欧式教堂：无 grass/boundary，`interior_surface.floor_shape=quad`，非毡帘；
  - 火山口观测站：无 grass fallback，unsupported 正确记录；
  - 纯室外集市/营地：无 shell 时 boundary 可落地，围栏不切穿主体物；
  - 多 agent 房间：单 agent 可测试不 @ 触发；多个 agent 必须 @ 指定，否则不应误触发所有 agent；
  - 多人 GM：confirmed action 应显示 `confirmed_gm_action -> queued_host_action -> executing_host_action -> host_action_executed` 状态链。

### 2026-06-17 追加：RoleAgent 模板增强与可见注入

- Role 模板从“说话风格 + 一句轻偏好”扩展为结构化字段：
  - `object_bias`
  - `layout_bias`
  - `forbidden_bias`
- 内置模板补强：
  - 长者：木桌、石灯、书卷、茶具、传统屏风；强调秩序、安全、主轴/对称。
  - 小女孩：小花、玩偶、彩色灯、软垫、小摆件；强调明亮、可爱、开阔活动区。
  - 山贼：篝火、木栅栏、酒坛、战利品、武器架；强调防御边界、营地动线。
  - 学者：书架、书桌、卷轴、仪器、台灯；强调研究/阅读/展示分区。
  - 商人：摊位、货箱、招牌、展示架、钱箱；强调迎客入口、展示和交易动线。
- Chat 注入：
  - `RoleTemplate.inject()` 会把偏好物件、布局偏好、避免倾向写入 system prompt，增强“遵守模板”的可观测性。
- Compose 注入：
  - 新增 `RoleTemplate.to_compose_context()` 和 `resolve_role_template()`。
  - `MasterAgent._handle_scene_compose()` 将 role context 作为“RoleAgent 软偏好”追加到 compose 文本，并在完成回复中显示 `RoleAgent：xxx（软偏好已注入）`。
  - 为避免污染开放场景物体抽取，`object_bias` 在 compose context 中标记为 `object_bias_reference_only`，并明确 “do not add these as new objects unless the user requested them”。
- GroupAgent 收口：
  - `_group_ai_chat()` 复用 `_extract_cai_text_chunk()`，避免总结/巡检路径再次出现 CAI JSON 信封空回复问题。
- 多人测试适配：
  - 当前 worker 已接入 `LanChatHostActionExecutor`，确认后会广播 `confirmed_gm_action -> queued_host_action -> executing_host_action -> host_action_executed`。
  - `test_lanchat_agent_orchestrator.py` 改为检查状态链中包含 `confirmed_gm_action` 和 `host_action_executed`，不再错误假设最后一条就是 confirmed。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`ast.parse` 只读语法检查 `agent_adapter.py / role_registry.py / test_lanchat_agent_orchestrator.py`。
- F5 复测重点：
  - 添加“小女孩/山贼/长者”等模板后，聊天回复和场景完成回执里应能看到 role 注入。
  - Role 偏好只能作为软偏好，不应凭空增加用户未请求的玩偶、武器架等物体。
  - 复杂多人确认后，日志/广播中应能看到 host action 状态推进；但强类型 SceneDelta 命令队列仍是后续深水项。

### 2026-06-17 追加：生成中阶段披露 / 进度条式聊天提示

- 问题：
  - 之前 `progress_timeline/progress_events` 主要在最终结果里展示，用户在长时间生成中仍然像黑箱等待。
  - `_handle_scene_compose()` 还会显示 `GROUND/SHELL/...` 等内部 phase 枚举，不适合作为面向用户的中途提示。
- 修复：
  - `SceneSession.format_progress_message()` 统一生成脱敏用户文案，包含百分比、10 格进度条、阶段中文名和简短说明。
  - `SceneSession.progressive_compose()` 在每个真实执行 phase 的 start/done 边界发布 `user_message`。
  - `run_progressive_workflow()` 新增 `progress_sink` 入参，向上层实时冒泡阶段消息。
  - `SceneComposer.compose()` 新增可选 `progress_sink`，默认不影响旧调用。
  - 新增轻量模块 `services/agent_progress_context.py`，用 thread-local 在一次 agent 调用内传递进度回调，避免 worker 导入重型 `agent_adapter` 触发 `Quasar` 依赖。
  - `LANChatAgentWorker.process_once()` 在调用 agent 时包住 `agent_progress_sink()`，收到阶段消息后立即通过 `network_send_agent_reply()` 发到聊天室；最终总结仍正常发送。
  - `_handle_scene_compose()` 最终汇报里的“阶段披露”改为复用脱敏 `user_message`，不再显示内部 phase/status。
- 隐私/安全边界：
  - 中途消息不包含 prompt、batch_id、tool 名称、模型供应商、raw phase id。
  - 只披露用户可理解的状态，例如“生成进度 50% [█████░░░░░] 完成：摆放物件...”。
  - start 消息提示“你可以继续提出调整，我会在阶段边界吸收”，强化渐进生成 + 用户介入的交互预期。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`ast.parse` 检查 `scene_session.py / scene_composer_progressive.py / scene_composer.py / agent_adapter.py / lanchat_agent_worker.py / agent_progress_context.py / test_lanchat_agent_orchestrator.py`
- F5 复测重点：
  - 长生成过程中，聊天室应逐条出现阶段提示，而不是只在最终结果里出现。
  - 阶段提示应为中文用户文案和进度条，不应出现 `GROUND/SHELL/OBJECTS`、`batch`、`prompt`、工具名等内部信息。
  - 最终完成消息仍包含完整导入/FinalReview/VLM/snapshot 信息。

### 2026-06-17 追加：单人 + 多 Agent 链路横切排查修复

- 排查范围：
  - 用户 @AI 助手 / 不 @ 直接发消息；
  - 多 Agent role 模板、persona 注入、GM proposal 分流；
  - 场景意图分类、compose 入口、ZoneTree / aspects；
  - 地形与主建筑、边界、内部地面、室外附属物的组合；
  - AABB / VLM / FinalReview 可观测性。
- 结论与修复：
  - `LANChatState` 当前 C++ 事实源仍以 `@agentName` 触发 Python worker；“单 agent 不 @ 自动触发”的底层规则已做代码尝试，但 C++/Ninja 验证按用户要求暂停，移入 `docs/突击底层bug记录.md`。
  - Python 单人/多 Agent 主路径确认：单人重大增删改移不再被 GM proposal 吞掉；只有 @GM、多人冲突或多人重大操作进入 GM。
  - Role 模板确认：长者/小女孩/山贼/学者/商人模板可解析；chat 走 `inject_persona_voice()`，compose 走 `_role_compose_context()` 软偏好，不直接覆盖 SceneState。
  - 修复渐进链路漏框架问题：`run_progressive_workflow()` 在 `_place_shells()` 后新增 post-shell framework hook，补回 shell interior floor 和 opt-in boundary，保持与旧 workflow 的 anchor chain 一致。
  - 修复混合场景室外物件分流：喷泉、雕像、天使、长椅、路灯、树、摊位等默认归 outdoor zone；mixed outdoor + shell 场景下未知主体物优先 outdoor，避免被塞进主建筑内部。
  - 修复渐进导入原点堆叠风险：`_distribute_assets_to_phases()` 后新增保守确定性初始布局。室内物件走室内小网格；室外物件绕主建筑外圈或广场区域摆放，避免全部 `[0,0,0]` 导入导致挤压穿模。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
  - 通过：`ast.parse` 检查相关 Python 文件。
- F5 复测重点：
  - 默认按 `@AI助手 ...` 测主路径；不 @ 自动触发属于底层待验项，暂不作为 Python 单人闭环阻塞。
  - “欧式教堂广场 + 喷泉 + 天使雕像”中，喷泉/雕像应在 outdoor/plaza，不应进教堂内部。
  - 渐进路径中，shell 放置后应能看到 interior floor / opt-in boundary，不应因 progressive 默认路径漏掉。
  - 新导入物体不应全部堆在原点；若仍挤压，下一步看真实 actor AABB 采集和 nudge/relayout，而不是再怀疑 zone 分流。

### 2026-06-17 追加：F5 对话日志二次诊断（JSON 泄漏 / 当前 Agent 身份 / 介入卡顿）

- 本次日志结论：
  - `@学者 你好`、`@小D 你好`、`@学者 生成...` 已能触发对应 Python worker，说明显式 `@agent` 主路径可用。
  - `/help` 和不带 `@` 的普通房主消息仍依赖 C++ LANChat trigger 规则；Python 层不再把它作为当前单人闭环阻塞项，底层记录见 `docs/突击底层bug记录.md`。
  - 生成链路能跑通并落地 snapshot，但首批只披露 `OBJECTS`，且用户反映生成时 UI 卡住，说明“阶段消息可见”不等于“输入框可用”。真正随时介入仍需要前端/CEF/host 线程把长任务与输入解耦。
- 已修复：工具 JSON 泄漏到聊天文本。
  - 症状：`{"actor":"喷泉","position":...,"scene_json_updated":false}已将...` 直接显示给用户。
  - 根因：CAI/tool stream 中的可见文本前缀包含工具结果 JSON，旧抽取逻辑只过滤完整内部 chunk，没有清洗“JSON + 自然语言”混合文本。
  - 修复：`agent_adapter._strip_visible_tool_json()` 会扫描并移除 actor/position/scale 等工具结果 JSON，只保留用户可读自然语言。
  - 覆盖：`test_cai_text_extraction.py::test_strip_tool_json_from_visible_text`。
- 已修复：多 Agent 历史导致当前被点名助手身份漂移。
  - 症状：用户 `@小D` 时，小D 回复“这是给 @小D 的，我不越位”，实际像继承了 `@学者` 的历史判断。
  - 根因：history 中其他 `@agent` 的消息权重过高，role agent 没有明确收到“本轮被点名对象就是你”的上下文。
  - 修复：`LanChatAgentOrchestrator._run_role_agent()` 在消息最前注入“当前点名上下文”，明确当前 `agent_name` 和最新用户消息。
  - 覆盖：`test_lanchat_agent_orchestrator.py::test_current_mentioned_agent_identity_overrides_history_mentions`。
- 仍需专项：编辑后的 AABB 落地复核。
  - 症状：雕像/喷泉缩放后需要用户反复说“底座穿模”，Agent 只是猜测 y 值上移。
  - 当前判断：agentic 增删改移路径已经可执行，但 scale/move 后没有统一读取缩放后的 actor AABB，并按地面/平台/terrain 高度做 bottom snap。
  - 下一步建议：对 `scale/move` 工具结果增加 `EngineWriteGate + get_actor_aabb + ground_y resolver + y = y + (ground_y - aabb_min_y) + epsilon` 的后处理；用户 HARD 最近操作仍只修 Agent/目标物体，不整体重排。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`

### 2026-06-17 追加：编辑 AABB 自动贴地 + 语义阶段进度 + 非阻塞输入 v1

- 编辑后 AABB 自动贴地：
  - 新增 `mcp/tools/transform_grounding.py`。
  - 核心策略：读取 actor `_geometry.get_aabb()` 的 local AABB、当前 `get_position()` 和 `get_scale()`，只修正 Y：
    - `bottom_y = position_y + local_min_y * scale_y`
    - `target_bottom = ground_y + clearance`
    - `new_y = position_y + (target_bottom - bottom_y)`
  - 接入 `set_actor_transform`：
    - 新增 `snap_to_ground=True`
    - 新增 `ground_y=0.0`
    - 新增 `ground_clearance=0.02`
    - 当设置 `position` 或 `scale` 后，默认做一次 bottom snap。
  - 接入旧 `transform_model`：
    - `scale/move` 后默认做一次 bottom snap。
  - 目的：
    - 解决本轮 F5 中“喷泉/雕像放大后底座穿模，需要用户反复要求上移”的问题。
    - 不改变 X/Z，避免覆盖用户“调远一点”的空间意图。
  - 边界：
    - 悬挂物、桌面物、墙面物后续应由工具显式传 `snap_to_ground=False` 或传入对应 `ground_y`。
    - 当前 v1 默认地面高度为 0；复杂地形/平台高度后续需要接 `zone/platform/terrain ground resolver`。
- 语义阶段进度：
  - `SceneComposer.compose()` 在 SceneSession 之前补充高层语义进度：
    - `开始理解场景需求`
    - `完成空间拆分/完成空间判断`
    - `准备所需模型`
    - `检查候选模型`
    - `开始组装场景`
    - `完成自动检查`
  - 目的：
    - 覆盖模型检索/生成这段最长等待时间，不再只在 `OBJECTS` 导入阶段才提示。
    - 不暴露 prompt、工具名、provider、raw phase id。
- 生成任务非阻塞输入 v1：
  - `LANChatAgentWorker` 新增可选异步执行模式：
    - 构造参数 `async_agent_execution=True`
    - 或环境变量 `LANCHAT_AGENT_ASYNC=1`
  - 行为：
    - `process_once()` pop 到 trigger 后立即开后台 `LANChatAgentTask` 执行 agent/compose，并立刻返回。
    - 后台任务仍按原路径发送进度消息和最终回复。
  - 目的：
    - 降低 UI/调用方被 Python agent 长任务阻塞的概率。
  - 边界：
    - 若 CEF/前端输入框或引擎写入本身被底层主线程阻塞，该开关不能单独解决，需要底层专项。
- VLM 位置判断：
  - 保留 VLM，但只作为外回路 advisory：
    - 看风格一致性、语义摆放、朝向、整体“像不像”。
    - 不负责硬防穿模。
  - 穿模/悬空/挡门必须由 AABB 内回路和编辑工具贴地实时解决。
  - VLM 不阻塞主链路，不直接改场景，不覆盖用户最近操作。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/mcp/tools/test_transform_grounding.py`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`

### 2026-06-17 追加：LANChat @AI 助手候选支持键盘选中

- 问题：
  - 用户输入 `@AI助手` 时，候选列表只能鼠标点击。
  - 上下键 + Enter 不能直接选中候选，需要再次用鼠标点击，打断高频多 Agent 对话节奏。
- 修复：
  - `RoomPanel.vue` 新增 `mentionActiveIndex`。
  - 输入框从 `@keyup.enter="onSend"` 改为统一 `@keydown="onDraftKeydown"`。
  - 候选列表打开时：
    - `ArrowDown`：下移高亮候选；
    - `ArrowUp`：上移高亮候选；
    - `Enter` / `Tab`：选中当前高亮候选并补全 `@名字 `；
    - `Escape`：关闭候选列表。
  - 候选列表关闭时：
    - `Enter` 仍发送消息。
  - 鼠标路径保留，并增加 `@mousedown.prevent`，避免输入框失焦影响候选点击。
- 用户体验预期：
  - 用户输入 `@` 后可用键盘完成 `@学者` / `@小D` 选择，再继续输入指令，不需要鼠标。
- 验证：
  - CodeGraph/只读核对确认 `@keydown`、`mentionActiveIndex`、候选高亮和 pickMention 接线存在。
  - 尝试运行 `npm.cmd run lint -- src/views/sidebar/lanchat/RoomPanel.vue`，当前前端环境缺少可执行 `eslint`，未完成 lint；这与此前前端依赖状态一致，不是本次改动引入。

### 2026-06-17 追加：多人 / 多 Agent Python 链路专项收口

- 范围边界：
  - 本轮只推进多人 / 多 Agent 链路。
  - 单人链路只做影响校验：progressive 输出、EngineWriteGate、RoleAgent 软偏好是否可被多人复用；不接管单人 F5。
- 当前链路确认：
  - `LANChatAgentWorker` 已支持：
    - `LANCHAT_AGENT_ASYNC=1` 或构造参数 `async_agent_execution=True` 的异步 agent 执行；
    - `agent_progress_sink()` 阶段披露消息；
    - agent 异常兜底回复，不杀 worker。
  - `LanChatAgentOrchestrator` 已支持：
    - 当前 `@agent` 身份注入，避免历史中其他 `@` 污染本轮目标；
    - GM proposal；
    - 房主文字确认；
    - `source_user_id` / `target_agent_id` / `execution=host_single_writer` 保留。
  - `LanChatHostActionExecutor` 已支持：
    - `confirmed_gm_action -> queued_host_action -> executing_host_action -> host_action_executed/host_action_failed` 状态链；
    - confirmed payload 进入 host queue；
    - 执行时包在 `EngineWriteGate.run()` 内；
    - 执行结果通过 `network_broadcast_intent()` 和 `network_send_system_message()` 可见。
- 本轮加固：
  - `LanChatHostActionExecutor` 新增 executor 级 `_process_lock`。
  - 目的：即使 async worker 同时收到多个 confirmed GM action，Python host executor 层也只允许一个 action 处于 executing / semantic execution 中。
  - 这不是替代 `EngineWriteGate`，而是补齐 host single-writer 在“状态链 + 语义执行”层面的串行语义；`EngineWriteGate` 继续负责实际引擎写入锁。
  - 新增测试 `test_host_action_executor_serializes_parallel_confirmed_actions()`，在没有 EngineWriteGate 兜底时验证两个并发 confirmed action 不会并行执行。
- C++/底层接口静态核对：
  - 已只读核对 `engine_bindings.cpp` 存在：
    - `network_send_agent_reply()`
    - `network_pop_lanchat_agent_trigger()`
    - `network_lanchat_history_snapshot()`
    - `network_lanchat_agents_snapshot()`
    - `network_send_system_message()`
    - `network_lock_object()`
    - `network_broadcast_intent()`
  - 已只读核对 `LANChatState` 中 `@agent` 触发规则：
    - 显式 mention 只触发目标 local agent；
    - 单个 local agent 且无 mention 时允许隐式触发；
    - 多个 local agent 且无 mention 时不触发全部。
  - 按当前要求未运行 C++/Ninja 编译验证。
- 验证：
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - 通过：`python -B -c "import ast, pathlib; ..."` 对多人关键 Python 文件做只读 AST 校验。
  - `python -m py_compile ...` 曾因 Windows `__pycache__` 写入权限失败；改用 `python -B` + AST 校验规避 pyc 写入，不判定为语法失败。
- 明天多人联机 F5 必查：
  - 单 agent 房间：不 `@` 消息应触发唯一 agent。
  - 多 agent 房间：不 `@` 消息不应触发全部 agent。
  - 显式 `@小B`：只触发小B，不能被历史中其他 `@agent` 污染。
  - GM 冲突：产生 proposal，房主文字确认后应看到 `confirmed_gm_action -> queued_host_action -> executing_host_action -> host_action_executed`。
  - 若执行状态可见但 peer 端 actor 不同步，归入 typed SceneDelta / actor sync 底层缺口。

### 2026-06-17 追加：多人 LANChat worker 默认异步与 orchestrator 串行保护

- 问题：
  - `LANChatAgentWorker` 虽支持 `async_agent_execution=True` / `LANCHAT_AGENT_ASYNC=1`，但运行态 `AITool.main` 未传参时仍可能同步执行。
  - 同步执行会让长场景生成/agent 调用拖住 LANChat worker 调用链，削弱多人“生成中继续发消息/介入”的体验。
  - 直接默认异步又会带来新风险：多个 trigger 并发进入同一个 `LanChatAgentOrchestrator`，可能污染 GM pending proposal / confirmation 状态。
- 修复：
  - `AITool.main` 启动 `_lanchat_agent_worker` 时显式传 `async_agent_execution=True`，F5 不再依赖手动设置环境变量。
  - `LANChatAgentWorker` 新增 `_agent_call_lock`，异步模式下同一个 worker 内的 agent/orchestrator 调用仍串行进入。
  - host action executor 已有 `_process_lock`，因此 confirmed action 的语义执行与状态链也保持串行。
- 边界：
  - 这能降低 Python agent 长任务阻塞 LANChat worker 的概率。
  - 如果 CEF/前端输入框或引擎主线程本身被阻塞，仍属于底层调度问题，需要明天联机 F5 记录到 `docs/突击底层bug记录.md`。
- 验证：
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 新增覆盖：`test_worker_async_agent_calls_are_serialized_per_worker()`，验证两个异步 trigger 不会并发进入 agent/orchestrator。
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - 通过：`python -B -c "import ast, pathlib; ..."` 对 `main.py / lanchat_agent_worker.py / lanchat_host_action_executor.py / test_lanchat_agent_orchestrator.py` 等做只读 AST 校验。

### 2026-06-17 追加：LANChat 添加 Agent 后立即可 @

- 问题：
  - `RoomPanel.vue` 的 `@` 候选列表读取 `state.agents`。
  - `lanchat.addAgent()` 成功后只写入 `state.myAgents`，若 C++ `agent_roster` 事件没有立刻回到前端，用户刚添加的 AI 助手不会马上出现在 `@` 候选里。
- 修复：
  - `lanchat.js` 新增 `upsertAgent()` 和 `removeAgentFromRoster()`。
  - `addAgent()` 成功后同时写入 `myAgents` 和 `agents`，让本机立即可 `@` 新 agent。
  - `removeAgent()` 成功后同步移除本地 roster。
  - 后续 `agent_roster` 事件仍作为 C++ 权威快照覆盖 `state.agents`，本地更新只用于消除交互延迟。
- 验证：
  - 通过：`node editor/Frontend/scripts/test-lanchat-roster.mjs`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`

### 2026-06-17 追加：多人 GM proposal_id 级确认 v1.5

- 问题：
  - 旧 GM proposal 只提示房主回复“确认 / 拒绝 / 按方案A”。
  - Orchestrator 只要看到确认词就消费唯一 pending proposal，无法确认“确认的是哪个 proposal”。
  - 多 proposal、重复冲突或误输确认时，容易误伤当前 pending proposal。
- 修复：
  - `LanChatAgentOrchestrator` 的 GM proposal 文案改为明确携带 `proposal_id`：
    - `@GM 确认 gm-xxx`
    - `@GM 拒绝 gm-xxx`
  - `_consume_confirmation()` 新增 `gm-xxx` 编号校验：
    - 文本中带了错误 proposal id 时，不消费 pending proposal，并提示当前待确认编号；
    - 文本中带了正确 id 时，才确认 / 拒绝；
    - 裸“确认 / 拒绝”仍保留为 F5 应急兼容路径。
  - `RoomPanel.vue` 在 Host 端 GM proposal 消息下方显示“确认 / 拒绝”按钮。
  - 按钮复用 LANChat message 路径，发送 `@GM 确认 gm-xxx` / `@GM 拒绝 gm-xxx`。
- 边界：
  - 当前只做前端 host 视角按钮显示和 Python proposal_id 校验。
  - 还没有 C++/Python 结构化 host 身份校验；非房主手打确认文本的风险已记录到 `docs/突击底层bug记录.md`。
- 验证：
  - 新增 `test_host_confirmation_rejects_wrong_proposal_id()`。
  - `test_host_confirmation_consumes_pending_proposal()` 改为使用显式 proposal_id。
  - `test-lanchat-roster.mjs` 增加 GM proposal 按钮静态约束。

### 2026-06-17 追加：多人 / 多 Agent @ 规则文档统一

- 问题：
  - `docs/LANChat_AI_使用说明.md` 仍写“大部分场景指令不需要 @”。
  - 这与 C++ `LANChatState` 的多 Agent 规则冲突：多个 local agent 时，不 `@` 不应触发全部 agent。
- 修复：
  - 文档改为：多人 / 多 Agent 房间默认显式 `@助手名`。
  - 单 Agent 房间可尝试不 `@`，作为增强体验，不作为主链路依赖。
  - 多 Agent 不确定目标时使用 `@GM`，由 GM 整理冲突、排序、确认项。
- F5：
  - 单 agent 不 `@` 触发作为底层待验项。
  - 多 agent 不 `@` 不群发作为主链路验收项。
  - 添加“学者/山贼”后无需刷新即可出现在 `@` 候选。
### 2026-06-17 追加：地形 / 主建筑基座 / 全场景比例关系 v1

- 目标：
  - 地形范围不再统一套草原式超大默认，而由 `ground_profile.params` 的 `extent_factor/min_extent/max_extent/padding/openness` 驱动。
  - 地形材质与细节由 `material/secondary_material/detail_pattern/detail_strength` 驱动，避免欧式教堂广场误长草簇。
  - `ground_cover` 只表示 opt-in 的散布覆盖：`grass/flowers/rocks/shrubs/debris/paving_marks`，不再承载 stone/marble/concrete 这类基础铺装材质。
  - 新增 `foundation_surface` 能力，用于 shell 放置并测得真实 footprint 后，在 objects 导入前生成外部基座/铺装垫层。
  - progressive objects 根据 `layout_role`、主建筑 AABB、terrain extent、foundation extent 给出保守初始位置和 scale，喷泉/雕像默认进入 outdoor activity zone。
- 实现：
  - `zone_tree.py`
    - `CAPABILITY_MANIFEST` 新增 `foundation_surface`。
    - `GENERATOR_MANIFEST.ground_profile.effective_params` 扩展 terrain extent/detail 参数。
    - `ground_cover` 描述收敛为散布覆盖，不再写 sand/stone 这类基础材质。
  - `scene_composer.py`
    - 新增 `_resolve_terrain_extent()`，公式为 aspect 参数驱动的 `max(zone.size, building_extent * extent_factor) + padding`，再受 `min_extent/max_extent` clamp。
    - legacy `TerrainProfile` 兜底的 `extent_factor` 从草原式 6.0 收敛为中性 3.0；草原宽大必须由 decompose 显式给 `extent_factor/min_extent`。
    - `_generate_terrain()` 接入 `secondary_material/detail_pattern/detail_strength`，写出 `terrain_detail` 材质和程序化地表细节。
    - `_build_grass_obj()` 扩展为通用 ground scatter，支持 `rocks/shrubs/debris/paving_marks`。
    - 新增 `_generate_foundation_surface()`，按 shell 真实 footprint + padding 生成 `disc/quad` 外部基座，记录 `_foundation_extent`。
    - 原始 workflow 在 shell 后依次生成 interior floor + foundation surface，再进入 boundary/objects。
  - `scene_composer_progressive.py`
    - post-shell framework 同步生成 foundation surface，保证 F5 progressive 路径不漏基座。
    - `_distribute_assets_to_phases()` 为资产写入 `layout_role`。
    - 新增 `_scene_scale_context()` / `_outdoor_default_scale()`，用主建筑和地形尺度给 fountain/statue/foreground/decorations 保守 scale。
    - `_outdoor_default_pos()` 改为考虑 foundation extent，室外物件围绕主建筑外部活动区，不默认堆原点或进 shell。
- 边界：
  - 仍不在生成代码里写死“教堂/蒙古包/火山”等场景身份分支；场景差异必须来自 decompose aspects。
  - 当前 scale 是基于 actor 导入倍率的保守 v1，并不等于真实目标米制尺寸；F5 若发现具体模型资产本身尺度异常，下一步要接入导入后真实 actor AABB normalization。
  - foundation_surface 只解决主建筑与地形/广场的承接，不替代 interior_surface。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
- F5 必查：
  - 欧式教堂广场：ground_profile 应为 stone/marble/concrete/pavement 一类铺装材质，ground_cover 不应是 grass/flowers；应有 foundation_surface；喷泉和天使雕像在 outdoor/plaza，比例不明显失真。
  - 草原蒙古包：若要宽大草原，decompose 必须显式给 `min_extent/extent_factor`；围栏/草簇/基座仍需围绕 shell。
  - 纯室外营地/广场：无 shell 时继续依赖 zone volume/platform 作为尺度基准，boundary 与物体相对位置仍需截图确认。
### 2026-06-17 追加：室内 5 面盒子默认展示 + 单人/多 Agent 链路审查

- 室内盒子：
  - `_build_room_box_obj()` 新增 `open_face` 参数。
  - 默认 `open_face="front"`，生成前墙开放的 5 面盒子：地面、左墙、右墙、后墙、顶面。
  - `open_face="none"` 保留旧 6 面封闭盒子；带 `door` 时继续生成门洞三块前墙。
  - `open_face="front_and_ceiling"` 生成 4 面展示盒：地面、左墙、右墙、后墙。
  - `_generate_room_box()` 读取 `CORONA_ROOM_BOX_OPEN_FACE`，默认 `front`；非法值回退 `front`。
- 设计边界：
  - 5 面盒子只是展示/可观察性策略，不把 open_face 交给 LLM 决定。
  - 去掉前墙 mesh 不等于取消空间约束；后续越界仍由 Zone AABB / door clearance / consistency check 管。
  - 若 F5 需要旧封闭视觉，可设置 `CORONA_ROOM_BOX_OPEN_FACE=none`。
- 单人/多 Agent 链路审查：
  - `LanChatAgentOrchestrator` 当前规则符合单人优先：单人明确增删改移不被 GM proposal 吞掉；GM 主要处理 @GM、语义冲突、多人重大操作。
  - Role 模板仍是 chat voice + compose soft context；`object_bias_reference_only` 明确不自动新增物体，不直接写引擎。
  - 当前 @agent 身份注入在 history 前，避免历史中其他 @对象 污染本轮目标 agent。
  - `run_progressive_workflow()` 有 progress sink、post-shell framework、VLM advisory 外回路；AABB/FinalReview 仍走 SceneSession。
  - 编辑 scale/move 的贴地链路在工具层已有 v1；本轮未改底层 C++/CEF/ninja。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`python -B` AST 检查改动 Python 文件。
- F5 必查：
  - 室内书房/卧室默认应能从前方直接看到内部家具，顶面仍保留房间感。
  - 设置 `CORONA_ROOM_BOX_OPEN_FACE=none` 后应回退 6 面封闭盒子。
  - 多 Agent 场景中 `@学者` / `@小D` 不能串身份；单人编辑操作不应被 GM 提案阻断。
  - 如果生成中输入框仍卡住，优先记录为 CEF/主线程/底层调度问题，而不是继续改 Python worker。

### 2026-06-17 追加：多人 / 多 Agent P0 非底层收口

- 本轮约束：
  - 不修改 C++。
  - 不运行 Ninja。
  - 不实现 typed SceneDelta / actor version / peer actor apply。
  - 只推进 Python / Frontend / 文档记录中能落地的部分。
- Orchestrator 加固：
  - `_consume_confirmation()` 改为接收 trigger。
  - 继续校验 `proposal_id`。
  - 新增 `_processed_proposals`，重复确认已 confirmed/rejected/mismatched 的 proposal id 时返回“已处理”，不再产生 `action_payload`，避免重复入队。
  - 若 trigger 显式携带 `sender_role/room_role/role/is_host/is_room_host/sender_is_host`，非 host 确认会被拒绝。
  - 若 trigger 没有可信 host 字段，不用 sender name 猜房主；剩余风险记录到底层身份字段缺口。
  - 裸“确认/拒绝”仍保留为 fallback，并在 confirmed payload 中写入 `confirmation_mode=bare_text_fallback`。
- Host executor 加固：
  - 空结果或明显失败结果不再广播 `host_action_executed`，改为 `host_action_failed` + `CommandRejected`。
  - 无 executor agent / 未产生 typed actor delta 的结果改为 `accepted_no_delta`，不伪装成完整 actor 同步。
  - 成功结果文案明确标注：“语义执行完成；peer actor sync 以底层 SceneDelta 为准。”
- F5 文档：
  - `docs/F5测试轮次_项目链路使用说明书.md` 新增多人 P0 判定性实验：
    - 基础连通与 agent roster；
    - 多 agent 不 @ 不误群发；
    - GM proposal + Host 按钮确认状态链；
    - Host executed 后 Guest 场景是否同步；
    - 非房主手打确认绕过；
    - proposal_id 过期 / 乱序 / 重放；
    - 生成中继续输入；
    - 同 actor 双人冲突。
  - 每个实验都标注失败指向层和第一检查文件。
- 底层记录：
  - `docs/突击底层bug记录.md` 新增“多人 P0 暂不处理底层项”。
  - 明确 typed SceneDelta、actor version/lock/owner、host identity 可信字段、peer delta apply、C++/Ninja protocol tests 全部留给底层专项。
- 验证：
  - 通过：`python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - 通过：`node editor/Frontend/scripts/test-lanchat-roster.mjs`
### 2026-06-17 追加：Bug-first AABB hard loop + VLM 审查定位

- 目标：
  - 先修 F5 暴露的穿模、堆叠、缩放后底座埋地、GM 内部提示泄漏。
  - 保留 VLM，但定位为组装合理性/风格一致性/最后 1-2 轮审查，不作为硬几何 solver。
- AABB 几何闭环：
  - `transform_grounding.py` 新增 `actor_world_aabb()`，修正 local geometry AABB 被误当 world AABB 的风险。
  - 新增 `resolve_actor_overlaps()`，对当前 actor 做 XZ nudge，跳过地毯/地板 surface 和 `__room_ / __interior_ / __terrain_ / __foundation_` 基础设施。
  - `transform_model` 和 `set_actor_transform` 在默认 `snap_to_ground=True` 后继续尝试 overlap resolve，并返回 `overlap_resolved`。
  - `SceneSession.progressive_compose()` 新增 `post_import_hook`，`run_progressive_workflow()` 在每个 phase 导入后立刻执行贴地 + 解叠，再更新 diff baseline。
- GM 降噪：
  - `LanChatHostActionExecutor` 不再把 host executor 内部指令作为最后一条消息送入 MasterAgent；最后一条改为 `用户确认意图：...`，避免内部协议被当成普通 chat trigger。
- 边界：
  - 本轮只做 Python 层 hardening，不改 C++/CEF/ninja。
  - AABB 是防穿模主路径；VLM 只做 advisory/review，截图失败或超时不得阻塞主链路。

### 2026-06-17 追加：室内 5 面盒子基础 skin

- 目标：
  - 在 AABB/介入 bug 修复后，补室内视觉基础层，让 5 面盒子不再只有单一灰墙。
  - 墙/地/顶风格来自 `interior_surface` aspect params，不在代码里写死“商人/学者/卧室”等场景身份。
- 实现：
  - `_build_room_box_obj()` 增加 floor/wall/ceiling material slots，OBJ 内按面写 `usemtl floor/wall/ceiling`。
  - 新增 `_room_box_mtl_text()`，根据 `floor_material/wall_material/ceiling_material/accent_material` 输出基础 MTL。
  - `_generate_room_box()` 读取当前 room zone 的 `interior_surface`，缺失时使用 neutral fallback。
  - 纯室内单 box 退化路径保留 LLM decompose 的 raw aspects，避免返回 None 后丢失 room skin 参数。
  - `GENERATOR_MANIFEST["interior_surface"].effective_params` 扩展 wall/ceiling/accent/detail 参数。
- 验证：
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_terrain_style_profile.py`
  - 通过：`python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - 通过：`python -B` AST 检查相关 Python 文件。
## 2026-06-17 add: LANChat message v2 multiplayer alignment

- Goal:
  - Align multiplayer GM / progress / host confirmation / action status with LANChat message v2.
  - Keep typed SceneDelta / actor sync as a separate lower-layer protocol.
- C++ / binding:
  - `LanChatAgentTrigger` carries `sender_type`, `message_kind`, `target_agent_id`, `source_user_id`, `correlation_id`, `metadata_json`.
  - `network_pop_lanchat_agent_trigger()` exposes those fields at trigger top level.
- Python:
  - `LanChatAgentOrchestrator` consumes structured confirmation first:
    - `message_kind=confirmation`
    - `correlation_id=<proposal_id>`
    - `metadata_json.decision=confirm|reject`
  - `LANChatAgentWorker` sends `progress`, `gm_proposal`, `agent_reply` through structured message kinds when `_ex` bindings exist.
  - `LanChatHostActionExecutor` sends `action_status` for queued/executing/executed/failed/accepted_no_delta while preserving legacy intent broadcast.
- Frontend:
  - `normalizeMessage()` preserves v2 fields and parses `metadata_json`.
  - GM host buttons send structured `confirmation` with `correlation_id=<proposal_id>`.
- Verification:
  - PASS: `python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: `node editor/Frontend/scripts/test-lanchat-roster.mjs`
  - PASS: Python AST check for LANChat Python services.
- Not done:
  - C++/Ninja build not run in this pass.
  - typed SceneDelta / actor version / peer actor apply remain lower-layer items.

## 2026-06-17 add: F5 bug convergence - layout/AABB/VLM/intervention/speed

- Scope:
  - Python-side F5 convergence only.
  - No C++/Ninja build or protocol test was run in this pass.
- Indoor layout:
  - Replaced the indoor fixed seven-point fallback with a semantic room slot planner in `scene_composer_progressive.py`.
  - Beds prefer the rear wall; desks/bookcases/wardrobes prefer side walls; chairs follow desks; lamps follow desks or beds.
  - Rugs/carpets are classified as `surface`, not normal furniture, so they do not compete with large furniture in the first-pass layout.
  - Outdoor planning (`_outdoor_default_pos/_outdoor_default_scale`) was intentionally left unchanged for grassland/yurt and church/plaza regression safety.
- AABB hard loop:
  - `resolve_actor_overlaps()` now reports `remaining_overlap` when it cannot fully clear an actor.
  - Progressive post-import repair uses a larger iteration budget and logs unresolved overlaps as warnings instead of silently implying success.
- VLM trust boundary:
  - `_capture_single_model()` no longer treats failed/empty screenshot writes as successful captures.
  - VLM user text now reports skipped/timeout targets instead of saying "no obvious issue" when screenshots failed.
  - VLM remains advisory; hard geometry remains AABB-driven.
- Intervention responsiveness:
  - `LANChatAgentWorker` now defaults to async execution so long compose calls do not block trigger polling.
  - For generate/edit-like messages, the worker sends a fast `progress` ack before entering the serialized agent lock.
  - This is a Python-side improvement only; if UI input still freezes, classify it as CEF/render/main-thread lower-layer blocking.
- Generation time:
  - `_retry_failed_images()` now uses bounded parallel retries. Default `CORONA_IMAGE_RETRY_MAX_WORKERS=3`.
  - Hunyuan 3D generation concurrency now defaults to 3 via `CORONA_HUNYUAN_MAX_CONCURRENCY` / `CORONA_GENERATION_MAX_WORKERS`, instead of the previous 12-worker default.
  - Retrieval task order is still preserved by downstream sorting/task indices.

## 2026-06-17 add: F5 interaction lag mitigation - LANChat send / ResourceSearch

- Latest F5 log diagnosis:
  - LANChat worker is already async, but edit/chat requests still enter the serialized `LANChatAgentTask` path.
  - Simple edit messages such as moving/scaling actors still route to `integrated stream`, taking roughly 9-48s per request in the latest log.
  - ResourceSearch background rebuilds also run during the same interaction window, with observed 10s+ rebuilds.
  - Therefore the lag is not caused by "too many Python threads" alone; it is combined CEF/main-thread wait, serialized AI execution, and background indexing pressure.
- Frontend mitigation:
  - `RoomPanel.onSend()` no longer awaits the CEF send promise before returning to the input box.
  - Send failures are logged asynchronously; message ordering is still server/history driven, no optimistic duplicate bubble is inserted.
- ResourceSearch mitigation:
  - Added `CORONA_RESOURCESEARCH_DISABLE_AUTO_REBUILD=1` and `CORONA_F5_DEMO_MODE=1`.
  - When enabled, `ResourceIndexService.prepare()` / `request_refresh()` use the cached index if available and do not start a background rebuild.
  - This is intended for F5/demo runs where interaction responsiveness matters more than live resource-index freshness.
- Edit fast path:
  - Added a deterministic fast path in `MasterAgent._handle_edit()` for common scale/grounding commands.
  - Commands such as `放大儿童床`, `喷泉底座穿模了`, `把雕像贴地` can now adjust actor scale, snap bottom to ground, and run AABB overlap repair without entering `integrated stream`.
  - More complex spatial planning such as `靠左墙`, `重新规划`, `移到窗边` still falls back to the existing agentic tool channel.
- Verification:
  - PASS: `node editor/Frontend/scripts/test-lanchat-roster.mjs`
  - PASS: inline ResourceSearch env check proved disabled prepare/refresh does not call `ResourceIndex.rebuild()`.
  - PASS: `python editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - PASS: `python editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - PASS: `python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - Full `test_index_service.py` could not run under the sandbox because Python `tempfile` still resolved to the user Local Temp directory and hit `PermissionError`.
- Remaining:
  - Need to extend the edit fast path from scale/grounding to common wall/side placement commands.
  - If input still freezes after the frontend change and ResourceSearch disable flag, classify as CEF/render/main-thread lower-layer blocking.

## 2026-06-17 add: A-level intervention v1 - confirmation, micro-batch, pending plan

- Scope:
  - Python-side implementation only.
  - No C++/Ninja/CMake build or protocol tests were run in this pass.
- Planning confirmation:
  - Added `services/lanchat_scene_runtime.py` as a lightweight runtime side-channel.
  - Plan-like messages such as "I have a plan / build a ..." now return a short confirmation proposal instead of directly starting compose.
  - Explicit commands such as "confirm start / direct generate / start generating" bypass the gate and enter compose.
  - Supplements before confirmation are merged into the compose text, so they can affect item extraction/model preparation.
- Inventory expansion:
  - `SceneComposer.extract_items()` now calls `_ensure_minimum_scene_inventory()`.
  - If an open scene extracts fewer than the configured minimum items, the system asks an LLM to expand to a 6-10 item inventory.
  - Fallback expansion is generic functional props only; no code-side "forest=..." or "church=..." scene identity mapping was added.
- Real micro-batch:
  - `scene_composer_progressive.py` now splits `INTERIOR`, `OBJECTS`, and `DECORATION` into 2-3 item micro-batches.
  - `SceneSession.progressive_compose()` now accepts `phase_sequence` and `phase_metadata`, so progress can report batch index and cumulative imported count.
  - Progress text now says "next batch" instead of only "phase boundary".
- Generation-time pending notes:
  - `LANChatAgentWorker` checks `LanChatSceneRuntime` before entering `_agent_call_lock`.
  - If a scene compose is active, other agents can send a lightweight reply and record pending generation/layout/edit notes without waiting for the long agent call.
  - Pending "do not generate X" notes can filter a future batch.
  - Pending additions are recorded and reported, but v1 does not spawn new text-to-image/Hunyuan jobs mid-compose; use the pre-generation confirmation/supplement path for additions that must affect the current run.
- Edit fast path:
  - Extended deterministic fast edit path from scale/grounding to simple delete/hide and relative position commands:
    - center, move farther/nearer, left/right/front/back.
  - Fast edits still run ground snap and overlap repair after position/scale changes.
- Verification:
  - PASS: Python AST parse for edited files.
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - PASS: `python -B editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
- Remaining for true A-level:
  - Mid-compose additions are recorded but not yet dynamically model-generated inside the same run.
  - If frontend typing itself still freezes, classify as CEF/UI/render main-thread blocking, not Python worker lock.

## 2026-06-17 add: Multiplayer GM first-class mention entry

- Goal:
  - Make `@GM` a visible and routable first-class collaboration entry.
  - Stop ordinary `@Agent` questions from being hijacked by GM proposals.
  - Let structured host confirmations reach GM without reopening progress/action_status trigger loops.
- Frontend:
  - `RoomPanel` injects a virtual `GM` candidate at the top of the `@` mention list.
  - Sending `@GM ...` now includes `target_agent_id=gm`.
  - GM proposal buttons send `message_kind=confirmation`, `target_agent_id=gm`, `correlation_id=<proposal_id>`, and structured decision metadata.
- C++ LANChat:
  - Added a narrow virtual GM trigger path in `LanChatState::enqueue_agent_triggers_for_message()`.
  - `@GM` / `target_agent_id=gm` creates a virtual trigger with `agent_id=gm`, `agent_name=GM`.
  - `message_kind=confirmation` is allowed only through the GM target path; `progress`, `gm_proposal`, `action_status`, and normal agent replies remain non-triggering.
- Python orchestrator:
  - `LANChatSummaryService` now only monitors user chat messages, filtering out agent replies, progress, GM proposals, confirmations, and action status messages.
  - `@GM 整理/总结` returns a sanitized GM summary instead of a proposal.
  - `@GM 暂停/继续/先讨论` enters a control path and does not accidentally reject pending proposals.
  - Normal `@学者/@山贼/...` messages stay on the role-agent path even when recent history contains old GM/agent messages.
- Verification:
  - PASS: `python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: Python AST parse for modified LANChat Python services.
  - PASS: `node editor/Frontend/scripts/test-lanchat-roster.mjs`
  - PASS: `git diff --check` on this change set.
- Not run:
  - C++/Ninja build and `test_network_protocol` binary were not run in this pass.
  - A C++ protocol test was added for virtual GM trigger / structured confirmation, but it still needs the normal C++ build/test lane.

## 2026-06-17 add: Multiplayer A-level intervention runtime mode + pending plan closure

- Scope:
  - Python-side multiplayer / multi-agent intervention loop only.
  - No C++/Ninja/CMake build, typed SceneDelta, actor version, or peer actor apply work in this pass.
- Runtime mode:
  - `LanChatSceneRuntime` now tracks room-level mode: `DISCUSSING`, `PLANNING`, `EXECUTING`, `PAUSED`.
  - Planning confirmation moves the runtime to `PLANNING`; confirmed compose/start moves it to `EXECUTING`; compose end returns to `DISCUSSING`.
  - `@GM 暂停`, `@GM 继续`, and `@GM 先讨论/不要生成` now write this runtime mode instead of only returning text.
- Micro-batch boundary control:
  - `SceneSession.progressive_compose()` accepts a `runtime_mode_provider`.
  - Before each phase/micro-batch, `PAUSED` or `DISCUSSING` stops further import and returns `paused`, `paused_mode`, and `paused_before_phase`.
  - Paused runs do not execute FinalReview, avoiding a false "finished" state.
  - Progress messages now expose a user-visible paused state such as waiting for `@GM 继续`.
- Pending plan application:
  - Generation-time messages from non-executing agents still use the fast busy path and do not enter the heavy agent lock.
  - `generation_delta` notes are recorded as `pending_for_planner` and attached to the next batch metadata as `runtime_generation_context`.
  - `layout_constraint` notes are recorded as `applied_to_batch_context` and attached to batch assets as `runtime_layout_constraints`.
  - `edit_existing` notes are recorded as `queued_edit_or_waiting_for_actor`.
  - "Do not generate X" generation notes can remove matching future assets from the current remaining batch.
- Verification:
  - PASS: `python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: `python editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - PASS: `python editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
- Remaining:
  - Positive mid-compose additions are visible to planner/context but still do not spawn new model-generation jobs inside the same running compose.
  - True multiplayer visual sync after host execution still depends on typed SceneDelta / actor sync bottom-layer work.

## 2026-06-17 add: Single-user multi-agent A-level intervention closure pass

- Scope:
  - Continue the single-user + multi-role-agent line to A-level demo behavior.
  - No C++/Ninja/CMake work in this pass.
- Pending plan now affects the next batch instead of only being recorded:
  - `layout_constraint` notes can mutate not-yet-imported batch positions for central-clear, entrance-clear, wall-aligned, and fountain-axis style constraints.
  - `generation_delta` notes now distinguish:
    - `applied_removed_from_remaining`
    - `already_in_remaining_plan`
    - `pending_next_generation`
  - `edit_existing` notes remain queued until the actor exists or the user repeats the command after import.
- AABB repair visibility:
  - Post-import AABB repair now appends unresolved overlaps/conflicts into `pending_tasks` with `status=needs_confirm`.
  - This avoids reporting a clean success when overlap resolution could not finish.
- Fast edit path:
  - Added deterministic fast rotation and basic color edit attempts.
  - Clear fast-edit requests with no actor match now return candidate actor names instead of falling into the slow integrated stream.
  - Position/scale edits still run bottom snap + overlap repair.
- Final user report:
  - Compose summary now groups absorbed interventions into visible buckets:
    - applied
    - recorded for follow-up
    - needs confirmation
- Verification:
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - PASS: `python -B editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
- Remaining:
  - Positive brand-new mid-compose additions are still follow-up-generation tasks unless already present in the pre-generated asset list.
  - Frontend input freeze during heavy engine/render work remains a C++/CEF/UI-thread issue if it reproduces with Python async enabled.

## 2026-06-17 add: Rotation unit closure for single-user multi-agent F5

- Problem:
  - Engine `set_rotation/get_rotation` directly reads/writes Euler values.
  - The runtime expects radians, but the AI edit prompt, layout prompt, and tool schema still described rotation as degrees.
- Fix:
  - Fast edit path now parses user-facing degree text and converts it with `math.radians()` before writing actor yaw.
  - Fast edit reply explicitly marks the written rotation as radians.
  - Agentic edit prompt now tells the executor to convert user degrees to radians before calling `set_actor_transform`.
  - `set_actor_transform` schema/tool description now documents radians.
  - `compose_scene` layout prompt now asks for radian rotations, with 90/180 degree examples.
  - `model_reviewer` VLM correction schema now reports rotation corrections in radians.
- Verification:
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - PASS: `python -B editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - PASS: AST parse for modified Python files.
  - PASS: `git diff --check` (line-ending warnings only).

## 2026-06-17 add: Single-user multi-agent F5 handoff guardrails

- Goal:
  - Turn the remaining single-user + multi-agent plan into a repeatable F5 handoff.
  - Keep the first F5 pass focused on interaction smoothness and AABB geometry, not VLM screenshot cost.
- VLM F5 guardrail:
  - `scene_composer_progressive._vlm_max_targets()` now defaults to 0 when `CORONA_F5_DEMO_MODE=1` and `PROGRESSIVE_VLM_MAX_TARGETS` is not explicitly set.
  - Normal non-demo behavior keeps the previous default of 4 targets.
  - Explicit `PROGRESSIVE_VLM_MAX_TARGETS=1` still enables the second-pass VLM paper-point check.
- F5 handoff doc:
  - Added `docs/单人多Agent_F5验收手册.md`.
  - The doc contains the three fixed demo scripts:
    - forest fantasy market
    - children bedroom
    - European church plaza
  - It also records environment variables, pass criteria, failure attribution, and the VLM second-pass rule.
- Verification:
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - PASS: `python -B editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - PASS: AST parse for modified progressive files.
  - PASS: `git diff --check` (line-ending warnings only).

## 2026-06-17 add: VLM independent review camera

- Problem:
  - F5 logs showed VLM review moving the main viewport camera 16 times (4 models x 4 angles).
  - The viewport could turn black/freeze during review, then recover after VLM stopped.
  - Logs also showed a PNG timing race: Python checked for the file before C++ finished writing it.
- Fix:
  - Added `vlm_review_camera` in `model_reviewer.py`.
  - VLM capture now reuses or creates this hidden camera with `view_open=False`, `deletable=False`, `render_backend="native"`, and `512x512` resolution.
  - The new camera is added through `scene.add_camera_to_scene(camera)` and does not call `scene.set_camera()`.
  - `_capture_single_model()` now defaults to the independent review camera path.
  - Main-camera capture is disabled by default; the legacy path only runs when `CORONA_VLM_ALLOW_MAIN_CAMERA_CAPTURE=1`.
  - Screenshot success now waits for the PNG file to exist and settle briefly, avoiding the "future returned before file is on disk" false skip.
- Verification:
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_vlm_review_loop.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_composer_progressive_geometry.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_scene_session.py`
  - PASS: `python -B editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_role_registry.py`
  - PASS: `python -B editor/plugins/AITool/cai_extensions/agent/test_cai_text_extraction.py`
  - PASS: AST parse for modified Python files.
- Remaining:
  - This pass stops main viewport camera movement.
  - It does not yet provide a fully independent offscreen render target, so GPU readback contention can still require a C++/Optics follow-up.

## 2026-06-17 add: Multiplayer demo-grade ActorTransformUpdated sync

- Goal:
  - Push the LANChat + multi-agent line past L3 semantic execution status.
  - Add the minimum L4 actor transform sync needed for tonight's demo:
    Host moves/scales/rotates an already-synced actor, Guest applies the same transform by `actor_guid`.
- Existing ActorAdded path kept:
  - Reused Python `actor-sync-broadcast` -> frontend `Network.vue` -> CEF `broadcast_actor_create` -> C++ `ACTOR_CREATE` -> peer pending create.
  - No duplicate ActorAdded protocol was introduced.
- New demo-grade transform path:
  - Added `ACTOR_TRANSFORM_UPDATE` protocol packet with:
    - `actor_guid`
    - `scene_name`
    - transform `[position(3), rotation(3 radians), scale(3)]`
    - `source_user_id`
    - `correlation_id`
  - Added `NetworkSystem::broadcast_actor_transform_update()`.
  - Added peer-side pending transform queue and `pop_pending_actor_transform_update()`.
  - Added CEF fast-path functions:
    - `broadcast_actor_transform`
    - `poll_pending_actor_transform`
  - Added frontend bridge methods:
    - `networkService.broadcastActorTransform()`
    - `networkService.pollPendingActorTransform()`
  - Added frontend `Network.vue` handling:
    - local `actor-transform-sync-broadcast` -> C++ transform broadcast
    - pending remote transform -> `SceneTools.apply_actor_transform_internal()`
  - Added `SceneTools.apply_actor_transform_internal()`:
    - finds actor by `actor_guid`
    - applies position/rotation/scale with `if_init=True`
    - avoids re-broadcast loops
  - Added Actor-side transform event:
    - local `set_position/set_rotation/set_scale`
    - local `translate/rotate_delta/scale_delta`
    - `on_move()`
    - remote/init writes do not rebroadcast.
- Tests / checks run in this thread:
  - PASS: `python editor/plugins/AITool/services/test_lanchat_agent_orchestrator.py`
  - PASS: `python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_local_transform_setters_emit_actor_transform_sync editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_remote_transform_apply_does_not_rebroadcast editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_actor_move_emits_ownership_claim`
  - PASS: `node editor/Frontend/scripts/test-lanchat-roster.mjs`
  - PASS: AST parse for modified Python files.
  - PASS: `git diff --check` on transform sync files (line-ending warnings only).
- Not run by instruction:
  - No C++/Ninja/CMake build in this Codex thread.
  - `corona_network_protocol_tests` build/run is deferred to the designated bottom-layer environment.
- F5 gate:
  - Host creates/imports actor -> Guest sees actor via existing ActorAdded path.
  - Host moves/scales/rotates the same actor -> Guest updates same `actor_guid`, without duplicate actor creation.
  - If this fails after C++ build passes, inspect CEF event dispatch and frontend pending transform polling first.
