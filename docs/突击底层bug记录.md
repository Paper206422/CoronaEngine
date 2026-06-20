# 突击底层 bug 记录

> 用途：记录当前突击主线中遇到、但暂不在 Python/交互层继续深挖的 C++、CEF、Ninja、底层构建或引擎协议问题。
> 原则：主线优先保证 Python 层、单人/多人交互链路和 F5 可观测性；底层问题集中记录，后续专项处理。

## 2026-06-17：多人 GM/Host Single-writer 的 C++ 编译验证暂缓

- 背景：
  - Python 层已推进 `confirmed_gm_action -> host action queue -> EngineWriteGate.run()` 的 v1 接线。
  - 当前 v1 使用已有 C++ binding：
    - `network_broadcast_intent()`
    - `network_send_system_message()`
  - 尚未新增 C++ typed `SceneDelta / ActorAdded / ActorMoved / ActorDeleted` 协议。
- 触发点：
  - 曾尝试执行 `cmake --build build --target corona_network_protocol_tests --config Debug` 检查 C++ NetworkSystem/binding 侧验证路径。
  - 该方向会进入 C++/Ninja 构建链，当前用户明确要求暂不陷入底层回归测试。
- 当前观察：
  - `build/` 目录存在，但未找到已构建的 `corona_network_protocol_tests.exe`。
  - `src/systems/network/CMakeLists.txt` 中存在 `corona_network_protocol_tests` target。
  - 现场曾观察到后台残留 `cmake` / `ninja` 进程，CPU 近 0；本轮未继续追踪、未擅自终止。
- 影响：
  - Python 层 host single-writer queue 可离线验证。
  - C++ 编译验证、typed SceneDelta 协议和前端真实 Actor delta 同步仍未闭环。
- 后续专项建议：
  - 在底层专项轮次中确认 CMake preset/target 是否可稳定构建。
  - 补 C++/CEF/NetworkSystem 层的 typed scene event：
    - `SceneDelta`
    - `ActorAdded`
    - `ActorMoved`
    - `ActorDeleted`
    - `CommandRejected`
  - 明确 Python `HostActionExecutionResult(event_type="SceneDelta")` 如何映射到 C++ NetworkSystem 广播协议。
  - 构建验证只在底层专项或明确授权时执行，避免阻塞当前 Python/交互主线。

## 2026-06-17：LANChat 不 @ 隐式触发规则存在 C++ 改动但未构建验证

- 背景：
  - 交互目标要求用户可以 `@AI助手` 指定 agent，也希望单 agent 房间里用户不 @ 直接发场景指令时能自然触发。
  - 当前 Python worker 只消费 `network_pop_lanchat_agent_trigger()`，是否触发由 C++ `LANChatState` 决定。
- 当前代码状态：
  - `src/systems/network/lanchat_state.cpp` 已有改动：
    - 收集本机拥有的 local agents；
    - 显式 mention 任一 local agent 时只触发被 mention 的 agent；
    - 无 mention 且 local agent 数量为 1 时，隐式触发唯一 agent；
    - local agent 数量超过 1 且无 mention 时，不自动触发，避免多 agent 误抢话。
  - `src/systems/network/tests/test_network_protocol.cpp` 已新增对应测试：
    - 单 local agent 可被无 @ 消息触发；
    - 第二个 local agent 注册后，无 @ 消息不触发。
- 未验证项：
  - 按当前策略未运行 C++/Ninja 构建和 `corona_network_protocol_tests`。
  - 因此“不 @ 隐式触发”只能算代码路径存在，不能算底层验证闭环。
- F5/专项建议：
  - 单 agent 房间：用户直接发“生成一个广场”应触发该 agent。
  - 多 agent 房间：用户不 @ 发“再加一个喷泉”不应触发所有 agent；应提示用户 @ 指定对象或由 GM 整理。
  - 显式 @ 时：`@小B ...` 只触发小B，不被历史中其他 @ 对象污染。
  - 底层专项再执行 C++ network protocol tests 与编译验证。

## 2026-06-17：生成过程中 UI 卡顿，用户无法输入介入

- 背景：
  - Python 层已实现阶段披露：`SceneSession.progress_timeline`、`progress_sink`、`LANChatAgentWorker.network_send_agent_reply()`。
  - F5 对话中用户能看到“生成进度 0% / 100%”消息，但用户反馈生成过程中界面完全卡顿，无法在输入框里继续介入。
- 当前判断：
  - 这不是单纯的 progress 文案问题，而是 UI/CEF/host 调度问题。
  - 生成、模型检索/下载、混元 3D 轮询、引擎写入或 Python worker 调用链仍可能阻塞房主侧 UI 事件循环。
  - 后端 phase-boundary intervention queue 已有雏形，但前端输入若被主线程卡住，用户无法真正把介入消息提交进去。
- Python 层已做缓解：
  - `LANChatAgentWorker` 新增 `async_agent_execution` 开关。
  - 可通过环境变量 `LANCHAT_AGENT_ASYNC=1` 启用。
  - 启用后 `process_once()` 在拿到 trigger 后立即开后台 `LANChatAgentTask` 执行 agent/compose，自身尽快返回，降低调用方被 Python 长任务阻塞的概率。
- 影响：
  - 当前体验只能证明“生成过程可披露”，不能证明“用户可在长生成中真实随时输入介入”。
  - UbiComp demo 的交互性叙事会被削弱，需要在底层/前端调度层补齐。
- 后续专项建议：
  - 将长耗时 compose/model retrieval/import 从 UI-affine 调用链移到后台任务或独立 worker。
  - 前端输入框与消息发送必须不等待生成任务完成；用户消息先入 LANChat history / intervention queue，生成在 phase 边界 drain。
  - progress 消息只做状态反馈，不应占用输入通道。
  - F5 若启用 `LANCHAT_AGENT_ASYNC=1` 后仍卡输入，优先检查 CEF/前端事件循环和引擎写入同步点，而不是继续改 Python 文案。
  - 若短期无法改调度，demo 侧使用短 batch / 分段命令作为兜底，但需要明确这只是演示降级，不是最终方案。
- 验证状态：
  - 未跑 C++/CEF/Ninja 验证；按当前突击要求只记录，不在本轮深入底层构建链路。

## 2026-06-17：不带 @ 的 LANChat 消息触发规则仍需底层确认

- 背景：
  - 本轮 F5 对话里 `/help` 是房主直接发送，未见 agent 回复。
  - 显式 `@学者` / `@小D` 消息可以触发 Python worker。
- 当前判断：
  - C++ `NetworkSystem/LANChatState` 仍是 agent trigger 的事实源。
  - Python 层无法凭空消费未下发的 trigger。
- 当前代码尝试：
  - 已尝试在 C++ 侧调整为：当房间只有一个本地 agent 且消息未显式 @任何本地 agent 时，允许隐式触发；多 agent 房间仍要求显式 @，避免多助手同时抢答。
  - 该改动尚未经过 C++/Ninja 编译和协议测试验证。
- 后续专项建议：
  - 明确产品规则：多 agent 房间中 `/help` 是否由 GM/默认助手响应，还是要求 `@助手 /help`。
  - 补 C++ network protocol test 后再确认是否进入 F5 主线。

## 2026-06-17：底层接口需求清单（多人/多 Agent + 开放场景 F5）

> 这部分是 Python/交互层对 C++ NetworkSystem、CEF/前端、Scene/Actor API 的接口需求。
> 当前 Python 层已有 host action queue、EngineWriteGate、AABB/VLM、RoleAgent/GM 逻辑；但要形成真正多人闭环，需要底层提供稳定事件和同步协议。

### P0 必须接口：F5 闭环强依赖

1. **Typed SceneDelta 广播**
   - 需求：
     - `network_broadcast_scene_delta(delta_json)` 或等价 C++ binding。
     - 事件类型至少覆盖：
       - `SceneDelta`
       - `ActorAdded`
       - `ActorMoved`
       - `ActorScaled`
       - `ActorRotated`
       - `ActorDeleted`
       - `ActorMaterialChanged`
       - `CommandRejected`
   - 最小 payload：
     ```json
     {
       "event_id": "...",
       "room_id": "...",
       "source_user_id": "user-a",
       "executor_peer_id": "host",
       "actor_id": "...",
       "actor_name": "...",
       "operation": "move|scale|rotate|delete|add|material",
       "before": {"position": [], "rotation": [], "scale": []},
       "after": {"position": [], "rotation": [], "scale": []},
       "actor_version": 18,
       "timestamp_ms": 123456
     }
     ```
   - 当前替代：
     - Python v1 只能用 `network_broadcast_intent(status="host_action_executed")` + `network_send_system_message()` 做可见性。
   - 风险：
     - 没有 typed delta 时，客户端只能“看到执行结果消息”，不能可靠复现移动/删除/缩放。

2. **Actor version / lock / owner 元数据接口**
   - 需求：
     - `network_actor_version(actor_id) -> int`
     - `network_update_actor_version(actor_id, expected_version, source_user_id, operation) -> result`
     - 现有 `network_lock_object / network_unlock_object / network_locked_by` 需要明确 TTL、失败原因、owner。
   - 最小规则：
     - 用户拖拽 actor 时软锁；
     - 删除、批量布局、GM confirmed action 执行时短硬锁；
     - version mismatch 返回 `CommandRejected` 或 `ConflictDetected`，不要静默覆盖。
   - 风险：
     - 当前 Python GM 只能语义仲裁，不能解决两个用户同时动同一 actor 的底层 race。

3. **用户视口介入事件**
   - 需求：
     - C++/前端在用户直接拖拽、缩放、旋转、删除 actor 后发事件给 Python 或 LANChat：
       - `record_user_operation(op_json)`
       - 或 `network_broadcast_scene_delta(ActorMoved/ActorDeleted...)`
   - 最小 payload：
     ```json
     {
       "source": "USER",
       "source_user_id": "...",
       "actor_id": "...",
       "operation": "move|scale|rotate|delete",
       "before": {},
       "after": {},
       "actor_version": 19
     }
     ```
   - 当前替代：
     - Python 在 phase 边界做 scene-diff 轮询。
   - 风险：
     - phase 边界轮询只能“事后发现”，不能实时处理冲突，也不能区分拖拽过程中的多个用户竞争。

4. **非阻塞 LANChat 输入与生成后台化**
   - 需求：
     - 生成过程中前端输入框必须可用；
     - 用户消息必须先进入 LANChat history / intervention queue，不等待 compose 完成；
     - Python/AI 长任务不能阻塞 CEF/UI 主线程。
   - 当前风险：
     - 已观察到生成过程中 UI 卡顿，用户无法输入介入；这会直接破坏“渐进生成 + 随时介入”的交互叙事。

5. **Actor 世界 AABB 与 transform 的稳定读取接口**
   - 需求：
     - `actor.get_world_aabb()` 或 Scene API 批量返回所有 actor 的世界 AABB；
     - AABB 必须反映当前 position/rotation/scale；
     - 对生成模型、shell、terrain、boundary、decor 都一致可用。
   - 当前替代：
     - Python 兼容尝试 `actor.get_bounding_box()` / `actor._geometry.get_aabb()`，但不同 actor 类型不完全一致。
   - 风险：
     - AABB 为空或是 local-space 时，比例、贴地、穿模、挡门检查会误判。

### P1 建议接口：提升体验和排障效率

1. **Host confirmation UI binding**
   - 需求：
     - 前端显示 `GMProposal` 卡片，提供 `确认 / 拒绝 / 修改顺序` 按钮；
     - 点击后发送结构化确认，不依赖房主输入“确认”文本。
   - 当前替代：
     - 文字确认 v1。

2. **Progress event channel**
   - 需求：
     - 与聊天消息分离的进度事件通道：
       - `ProgressStarted`
       - `ProgressUpdated`
       - `ProgressCompleted`
       - `ProgressFailed`
   - 当前替代：
     - Python worker 通过 `network_send_agent_reply()` 插入进度文本。
   - 风险：
     - 聊天流会被进度刷屏；前端难以渲染真正进度条。

3. **Scene snapshot / restore / demo_mode**
   - 需求：
     - 保存 `.scene` 或等价 snapshot；
     - F5/答辩可一键加载 baseline；
     - 实时 LLM 失败时用 demo_mode 兜底。

4. **Network message schema version**
   - 需求：
     - SceneDelta、GMProposal、HostAction、ProgressEvent 都带 `schema_version`；
     - C++/前端/Python 任一侧升级时可拒绝不兼容 payload。

### P2 深水接口：投稿后继续完善

1. **Typed ActorMoved/ActorDeleted 真正同步到 peer 端**
   - 当前只有 actor create broadcast 较明确；
   - move/delete/scale/material 需要补完整协议。

2. **Server/host side operation replay**
   - 基于 OperationLog 重放；
   - 支持撤销/恢复/新用户加入后状态补齐。

3. **空间查询服务**
   - C++ 提供 actor overlap query、nearest free slot、door clearance query；
   - Python 不再自己拼 AABB list 做全部几何判断。

## 2026-06-17：风险分析一——生成场景比例问题

- 表现：
  - 主建筑过小或过大；
  - 家具与 shell 比例不匹配；
  - terrain 太大导致主体空旷，或太小导致 boundary/装饰切穿；
  - 用户 scale 后物体悬空/陷地；
  - 纯室外 boundary 半径合理但营地物体摊开范围不匹配。
- 当前已有措施：
  - shell path 使用实测 `_shell_aabb` 派生 interior floor / boundary；
  - `resolve_zone_anchor()` 对 shell / platform / zone volume 分层；
  - `boundary.params.radius/margin` 可显式控制纯室外围栏范围；
  - `transform_grounding.py` 已有 scale 后 ground snap 计算测试；
  - AABB/VLM 可发现明显穿模和语义不合理。
- 仍缺：
  - 统一的“目标真实尺寸”接口或元数据：
    - yurt/帐篷/小木屋/教堂/观测站等主建筑应有推荐真实宽深高；
    - 人尺度家具应有推荐范围；
    - terrain extent 应由主建筑 footprint + 功能意图推导，而不是只依赖 LLM size。
  - scale/move 后统一后处理：
    - 读取 transform 后世界 AABB；
    - bottom snap 到 ground/platform；
    - 再跑 AABB overlap / door clearance。
- 建议规则：
  - 主建筑优先：先确定主建筑真实 footprint，再派生 terrain/platform/boundary。
  - 人尺度约束：
    - 桌椅/灯/床等按人体尺度范围 clamp；
    - 主建筑与家具比例不满足时，优先调整家具/agent 物体，不动用户 HARD 操作。
  - terrain extent：
    - shell 场景：`extent = max(min_extent, shell_radius * extent_factor)`；
    - 纯室外：优先使用 `boundary.radius` 或 zone.size，但 F5 必查物体分布是否被围住。
  - 用户 scale：
    - 最近 1-2 轮用户 scale 是 HARD，系统只报告比例风险；
    - Agent 自动 scale 可被 FinalReview / AABB 修正。
- F5 检查：
  - 截图中主体建筑、人物尺度家具、边界、地形之间比例不能失真；
  - 用户放大/缩小后不悬空、不陷地；
  - 纯室外营地围栏不切穿物体、不空包一大圈。

## 2026-06-17：风险分析二——用户介入冲突问题

- 冲突类型：
  1. 用户 vs Agent：
     - 用户移动桌子，Agent 后续 relayout 又想移动桌子。
     - 规则：最近 1-2 轮用户操作 HARD，Agent 让位。
  2. 用户 vs 用户：
     - A 和 B 同时移动同一 actor。
     - 规则：actor soft lock + version check；后到者进入 `ConflictDetected`。
  3. 用户删除 vs Agent 依赖：
     - 用户删除桌子，Agent 正准备围绕桌子加椅子。
     - 规则：依赖任务 cancel/replan，不复活用户删除对象。
  4. GM confirmed action vs 视口拖拽：
     - 房主确认 GM 提案时，某用户正在拖同一 actor。
     - 规则：执行前检查 lock/version；冲突则 `CommandRejected` 并让 GM 重新提案。
  5. 旧用户软约束 vs 新整体布局：
     - 早期用户移动可被后续整体重排覆盖。
     - 规则：结合 `intervention_round`、AABB 合理性、用户最近性判断，不把 `touched_by_user=True` 永久锁死。
- 当前已有措施：
  - `SceneSession` 有 operation log、round、intervention queue；
  - `LayoutInstance` 有 lock/provenance/intervention 相关字段；
  - Python GM 能做语义层 proposal；
  - host action queue 已经把 confirmed action 串行化。
- 仍缺底层：
  - 视口操作事件；
  - actor version；
  - lock TTL 与失败原因；
  - typed conflict broadcast；
  - 前端 pending/冲突状态展示。
- F5 建议：
  - 单人：生成中移动桌子，后续椅子围绕新桌子，不覆盖最近操作。
  - 多人：A/B 同时操作同一物体，必须出现冲突提示或锁提示，不能无声以后到覆盖。
  - GM：房主确认后状态链可见；若 actor 被锁，应广播 rejected/needs_replan。

## 2026-06-17：风险分析三——其他高概率问题

1. **VLM / screenshot 卡顿**
   - VLM 不阻塞主链路，但截图可能卡渲染线程；
   - 继续保持 timeout/skip；
   - F5 如卡顿，优先设置 `PROGRESSIVE_VLM_MAX_TARGETS=0` 验主链路。

2. **RoleAgent 风格越权**
   - 风险：山贼模板自动加武器/栅栏，小女孩模板自动加玩偶，破坏用户原始需求。
   - 已修：decompose prompt 明确 RoleAgent 软偏好不是新增物体清单。
   - F5：同一场景切换 role 应主要影响语气/轻风格，不应凭空塞入大量未请求物体。

3. **ground_cover / material 混淆**
   - 风险：stone 被当 ground_cover，导致教堂广场生成石头散布簇或草覆盖。
   - 已修：normalize 清洗基础铺装材质；prompt 去掉 ground_cover.kind=stone 示例。
   - F5：教堂无 grass/boundary，石板应作为 surface/profile material，而非散布簇。

4. **进度消息刷屏**
   - 当前进度走聊天消息；
   - 后续应改 typed progress event；
   - F5 时关注聊天可读性，不要让最终结果被进度淹没。

5. **Host executor 语义执行仍偏软**
   - 当前 `LanChatHostActionExecutor` 把 confirmed intent 交给 host agent callback，并包在 `EngineWriteGate.run()` 内；
   - 这保证单写，但不等于已经有强类型工具命令；
   - 后续应把 GM proposal 的 action_payload 扩展为明确 command list：
     ```json
     {"commands":[{"type":"ADD|MOVE|DELETE|SCALE","actor_id":"...","payload":{}}]}
     ```

6. **C++ 进程残留 / 构建状态不明**
   - 现场曾有 cmake/ninja 残留；
   - 当前不处理；
   - 底层专项前先清理构建环境和进程状态，避免误判编译失败。

## 2026-06-17：多人 / 多 Agent 底层接口静态核对与仍缺项

- 本轮策略：
  - 用户要求先把 Python 层多人 / 多 Agent 链路收口，不陷入 C++/Ninja 回归测试。
  - 因此本轮只做 CodeGraph / 只读静态核对，不运行 C++ build。
- 已确认存在的 C++ binding：
  - `network_send_agent_reply()`：Python agent 回复与 progress 文本回写聊天室。
  - `network_pop_lanchat_agent_trigger()`：Python worker 消费 C++ 触发。
  - `network_lanchat_history_snapshot()`：供静默监听 / GM 读取最近聊天上下文。
  - `network_lanchat_agents_snapshot()`：供 Python 获取 agent roster。
  - `network_send_system_message()`：GM / Host 执行结果作为系统消息回写聊天室。
  - `network_lock_object()` / `network_unlock_object()` / `network_locked_by()`：对象锁接口存在，但还缺 typed conflict / version 协议。
  - `network_broadcast_intent()`：当前用于 `confirmed_gm_action`、`queued_host_action`、`executing_host_action`、`host_action_executed` 等状态可见性。
- 已确认存在的 C++ 触发规则代码：
  - 显式 `@agentName` 只触发被 mention 的 local agent。
  - 单个 local agent 且消息未 mention 任何 local agent 时，隐式触发唯一 agent。
  - 多个 local agent 且无 mention 时，不触发全部 agent。
- 仍未闭环：
  - 上述 C++ 改动尚未经过 Ninja/C++ protocol tests。
  - 仍缺 typed `SceneDelta / ActorAdded / ActorMoved / ActorDeleted / CommandRejected`。
  - 仍缺 actor version / expected_version / owner metadata 的可靠协议。
  - 仍缺前端房主确认按钮 UI；当前 v1 依赖房主文字回复“确认/拒绝/按方案A”。
  - 仍缺真实 peer 端 Actor move/delete/scale/material 的强同步验收。
- Python 层替代状态：
  - `LanChatHostActionExecutor` 已把 confirmed action 串入 host queue，并在 `EngineWriteGate.run()` 内执行。
  - 新增 executor 级执行锁，确保 async worker 并发 confirmed action 时，Python host executor 语义执行仍串行。
  - 执行状态通过 `network_broadcast_intent()` 可见，但这不是 typed actor delta。
- 明天联机实验记录要求：
  - 若聊天室状态链完整但场景不同步，优先记录为 typed SceneDelta / actor sync 缺口。
  - 若不 `@` 触发规则不符合预期，优先检查 C++ `LANChatState::enqueue_agent_triggers_for_message()` 与 CEF 调用路径。
  - 若输入仍卡住，优先检查 CEF/UI 事件循环和引擎写入同步点，而不是继续改 Python worker 文案。

## 2026-06-17：LANChat worker 已默认异步后仍可能卡输入的底层判定

- Python 层当前状态：
  - `AITool.main` 已以 `async_agent_execution=True` 启动 `LANChatAgentWorker`。
  - `process_once()` pop 到 trigger 后会启动后台 `LANChatAgentTask`，自身快速返回。
  - 同一个 worker 内的 agent/orchestrator 调用已用 `_agent_call_lock` 串行保护，避免异步触发污染 GM pending 状态。
  - host confirmed action 执行也已通过 `LanChatHostActionExecutor._process_lock` 串行保护。
- 因此明天 F5 若仍出现“生成中不能继续输入 / 聊天框卡住”：
  - 不应继续优先改 Python worker；
  - 优先检查 CEF / 前端事件循环是否等待 Python 调用返回；
  - 优先检查引擎写入、模型导入、截图、渲染主线程同步点；
  - 检查 `network_send_agent_reply()` / history broadcast 是否在主线程做了阻塞操作。
- 建议记录证据：
  - 触发长任务后，输入框是否能聚焦；
  - 能否输入但不能发送；
  - 能否发送但 history 不广播；
  - Python 是否已经发送 progress/final reply；
  - C++/CEF 是否仍在处理上一条消息。

## 2026-06-17：Host Confirmation v1.5 后仍需底层支持

- Python / Frontend 本轮已推进：
  - GM proposal 文本包含 `proposal_id`，格式如 `gm-178...`。
  - Host 端前端可显示“确认 / 拒绝”按钮。
  - 按钮通过 LANChat message 发送 `@GM 确认 gm-xxx` / `@GM 拒绝 gm-xxx`。
  - Python Orchestrator 会校验文本中的 `proposal_id`，错误编号不会消费当前 pending proposal。
- 仍缺底层强校验：
  - C++ / Frontend 没有把“当前用户是否房主”的身份签名传给 Python confirmation payload。
  - 当前按钮 UI 只在前端按 `s.role === 'host'` 显示；恶意或误操作用户仍可能手打确认文本。
  - 后续结构化确认 payload 应包含：
    - `proposal_id`
    - `host_user_id`
    - `decision`
    - `timestamp_ms`
    - `room_id`
  - Python 消费确认时应校验 `proposal_id` 与 host 身份，而不是只校验文本。
- 联机 F5 判定：
  - 如果非房主手打 `@GM 确认 gm-xxx` 也能触发 confirmed action，记录为“host identity verification 缺口”，不要误判为 GM 语义失败。
  - 如果按钮点击后消息没有进入 LANChat history，优先查 Frontend -> CEF/C++ send path。
  - 如果 confirmed 状态链完整但 actor 不同步，继续归入 typed SceneDelta / actor sync 缺口。

## 2026-06-17：多人 P0 暂不处理底层项

- 本轮执行约束：
  - 不修改 C++。
  - 不运行 Ninja / C++ protocol tests。
  - 不实现 typed SceneDelta。
  - 不实现 actor version / lock / owner 全链路。
  - 不实现 peer 端 actor delta apply。
- 已在 Python / Frontend 侧做的前置防线：
  - GM confirmation 继续要求 `proposal_id` 匹配。
  - 如果 trigger 已携带可信 `sender_role/room_role/role/is_host`，Python 会拒绝非 host 确认。
  - 如果 trigger 没有可信 host 字段，Python 不用 sender name 猜房主；该风险归入底层身份字段缺口。
  - proposal replay guard 会拒绝重复确认已处理的 proposal id。
  - Host executor 不再把空回复、失败回复、无执行器回复误报为完整 `host_action_executed`。
- 后续底层必须补的字段 / 协议：
  - `typed SceneDelta / ActorAdded / ActorMoved / ActorDeleted / ActorUpdated`
  - `actor_id / expected_version / actor_version`
  - `owner_user_id / lock_owner / lock_expire_at`
  - `host_user_id / sender_user_id / room_role` 可信身份字段
  - peer 端 actor delta idempotent apply
  - C++/Ninja protocol tests
- 触发实验映射：
  - F5 实验 3：状态链完整但 Guest 场景不同步 -> `typed SceneDelta / actor sync`
  - F5 实验 4：Guest 手打确认能触发执行 -> `host identity verification`
  - F5 实验 7：同一 actor 并发操作静默覆盖 -> `actor version / lock`
- 记录原则：
  - 如果失败属于以上底层项，明天 F5 只记录证据，不在 Python 侧继续绕补。
  - 如果状态链在 `confirmed_gm_action / queued / executing / executed / failed` 之前断掉，才回到 Python worker / orchestrator / executor 修复。
## 2026-06-17: LANChat message v2 lower-layer boundary

- Completed in Python/Frontend/C++ source wiring:
  - `gm_proposal`, `confirmation`, `progress`, `action_status` use LANChat message v2 fields.
  - `correlation_id` is the proposal/action thread id.
  - Text fallback remains for manual F5 and compatibility.
- Still lower-layer / not solved here:
  - C++/Ninja compile and runtime protocol validation.
  - Trusted `host_user_id / sender_user_id / room_role` identity propagation.
  - typed SceneDelta and peer actor application:
    - `ActorAdded`
    - `ActorMoved`
    - `ActorDeleted`
    - `ActorUpdated`
    - `CommandRejected`
    - `ConflictDetected`
  - actor version / expected_version / lock owner / lock expiry.
- F5 classification:
  - `action_status` visible but guest actor state unchanged -> typed SceneDelta / actor sync.
  - guest structured confirmation executes host action -> missing trusted host identity field.
  - progress/gm_proposal/action_status triggers another agent -> LANChat v2 routing gate regression.

## 2026-06-17: LANChat message v2 compile/test boundary

- User instruction:
  - Do not run C++ / Ninja / CMake build or protocol tests in this Codex pass.
  - Keep bottom-layer build verification as a separate专项, not part of the current Python/frontend interaction push.
- Aborted command:
  - `cmake --build build --target corona_network_protocol_tests --config Debug`
  - The command was intentionally interrupted by the user before completion.
  - Do not infer pass/fail from this aborted run.
- Current verification status:
  - Python LANChat orchestrator/worker/host executor tests passed.
  - Python AST check for LANChat Python services passed.
  - Frontend LANChat roster script passed.
  - C++ source wiring and C++ protocol tests were edited, but not compiled or executed in this pass.
- Bottom-layer专项待验:
  - `corona_network_protocol_tests` target builds successfully.
  - Legacy LANChat packets still parse.
  - LANChat v2 packets roundtrip `sender_type/message_kind/target_agent_id/source_user_id/correlation_id/metadata_json`.
  - `progress/gm_proposal/action_status/error` do not enqueue agent triggers.
  - Structured confirmation carries trusted host/user identity once C++/CEF identity fields are available.

## 2026-06-17: VLM screenshot pipeline lower-layer issue

- F5 symptom:
  - During VLM review the viewport can freeze or turn black for a noticeable period.
  - Logs may show screenshot write failures while Python still continues the review loop.
- Current diagnosis:
  - The VLM screenshot path uses the main camera and the main presented render target.
  - `_capture_single_model()` repeatedly moves the main camera and requests screenshots.
  - C++ screenshot processing reads back the render target through the GPU queue.
  - This can stall the visible viewport and can leave the user seeing a stale/black frame until the queue drains.
- Python-side mitigation implemented:
  - Failed/empty screenshot writes are now treated as capture failure.
  - VLM reports skipped/timeout instead of false "no obvious issue".
  - F5 can set `PROGRESSIVE_VLM_MAX_TARGETS=0` to disable VLM while testing AABB/layout.
- Required lower-layer fix:
  - Add an independent offscreen VLM camera and independent render target.
  - VLM capture must not move the user's viewport camera.
  - VLM capture must not read the main presented target.
  - Add C++/Optics protocol tests after implementation.
- Not done in this pass:
  - No C++/Ninja/CMake build or protocol test.
  - No offscreen render target implementation.

## 2026-06-17: VLM independent camera mitigation status

- Python-side fix implemented:
  - VLM review now uses a dedicated scene camera named `vlm_review_camera`.
  - The review camera is hidden (`view_open=False`) and is added without switching the active/main viewport camera.
  - Main-camera fallback is disabled by default.
  - Legacy main-camera capture is only allowed when `CORONA_VLM_ALLOW_MAIN_CAMERA_CAPTURE=1`.
  - Python now waits for the screenshot PNG to exist and stabilize before treating capture as successful.
- Expected F5 improvement:
  - VLM review should no longer visibly jump the user viewport camera or leave the main camera inside a wall.
  - If capture setup fails, VLM should report skipped/warn instead of disturbing the viewport.
- Still bottom-layer:
  - The screenshot path still calls camera screenshot APIs that can share GPU readback/render scheduling.
  - A true no-stall solution needs C++/Optics support for an independent offscreen render target and a completion signal that fires only after the PNG is fully written.
- No C++/Ninja work was run in this pass.

## 2026-06-17: F5 generation-time input lag after async worker

- Latest F5 symptom:
  - After scene generation starts, the frontend becomes noticeably delayed.
  - The user can barely type or send intervention commands, so "progressive generation + intervention" is not convincing yet.
- Current evidence:
  - `LANChatAgentWorker` is already asynchronous, so the polling loop itself is not the only blocker.
  - Latest logs show simple edit requests still going through `integrated stream` and taking about 9-48 seconds each.
  - Latest logs also show `ResourceSearchIndex` rebuilding during the same window, with 10s+ rebuilds.
  - Earlier VLM freezes are a separate screenshot/render-target issue; latest lag can happen even without clear VLM log lines.
- Python/frontend mitigation implemented:
  - Frontend `RoomPanel.onSend()` no longer awaits the CEF send promise before returning control to the input box.
  - `ResourceIndexService` now supports `CORONA_RESOURCESEARCH_DISABLE_AUTO_REBUILD=1` or `CORONA_F5_DEMO_MODE=1` to stop background index rebuilds during F5.
  - Common scale/grounding edit requests now have a Python fast path and do not need the full `integrated stream`.
- Required lower-layer / next engineering work:
  - CEF send path should not synchronously wait on heavy engine/Python work.
  - Extend the lightweight direct transform path to side-wall / front-back / delete / color commands.
  - Engine/CEF should keep input processing responsive while model generation/import and ResourceSearch work are active.
- F5 classification:
  - If typing is responsive but AI replies are slow -> Python agent serialization / missing edit fast path.
  - If typing itself freezes -> CEF/UI/render main-thread blocking.
  - If lag spikes align with ResourceSearch logs -> run F5 with `CORONA_RESOURCESEARCH_DISABLE_AUTO_REBUILD=1`.

## 2026-06-17: A-level intervention v1 lower-layer boundary

- Python-side mitigation implemented:
  - `LANChatAgentWorker` can reply to busy-scene messages before entering `_agent_call_lock`.
  - Other agents can record pending scene notes while the active agent is composing.
  - Progress is now micro-batch based for `INTERIOR/OBJECTS/DECORATION`.
  - `@GM 暂停/继续/先讨论` now writes Python runtime mode, and `SceneSession` can stop at the next micro-batch boundary.
  - Pending generation/layout/edit notes are now visible to the next-batch Python context.
- Still lower-layer if reproduced:
  - If the user cannot type or the input box does not regain focus during generation, inspect CEF/UI/render main-thread scheduling.
  - If a sent message does not enter LANChat history until compose ends, inspect C++ LANChat send/history broadcast path.
  - If progress/agent replies are emitted by Python but appear late in the UI, inspect C++/CEF dispatch and frontend store rendering.
  - If host reports `host_action_executed` but guest actors do not change, inspect typed SceneDelta / actor sync, not GM intelligence.
  - If two users edit the same actor and the final actor state is ambiguous, inspect actor version / lock / owner metadata.
- Not done in this pass:
  - No C++/Ninja/CMake build.
  - No C++ protocol tests.
  - No offscreen VLM render target.
  - No dynamic mid-compose Hunyuan generation for newly added items.
  - No typed SceneDelta, actor version, or peer actor delta apply implementation.

## 2026-06-17: Codex execution constraint for C++/Ninja/CMake

- User instruction:
  - Do not run C++/Ninja/CMake build or compile commands in this Codex thread.
  - Record required build/protocol verification here instead.
- Immediate context:
  - `cmake --build build --target corona_network_protocol_tests --config Debug` was started for the multiplayer actor sync protocol check.
  - The user intentionally interrupted the turn and instructed not to run build/compile here.
  - Do not infer pass/fail from the aborted build.
- Allowed in this thread unless separately blocked:
  - CodeGraph inspection.
  - Python unit tests.
  - Node/frontend lightweight scripts.
  - AST/static checks.
  - Source edits and project documentation updates.
- Bottom-layer verification now deferred to a designated build environment:
  - Build `corona_network_protocol_tests`.
  - Run protocol tests for `ACTOR_TRANSFORM_UPDATE`.
  - Confirm CEF `broadcast_actor_transform` and `poll_pending_actor_transform` compile.
  - F5 verify Host actor transform changes apply on Guest.

## 2026-06-17: VLM review camera / main viewport isolation hardening

- Latest F5 symptom:
  - Main viewport can flicker heavily when VLM review camera is created or used.
  - Extra user-opened CameraView is expected behavior and should remain allowed; the issue is main camera vs `vlm_review_camera` isolation.
- Python-side mitigation implemented:
  - `vlm_review_camera` is now forced to `view_open=False`.
  - `vlm_review_camera` is forced to surface `0`; if the engine cannot confirm surface `0`, VLM capture is skipped.
  - Main-camera fallback is ignored even if `CORONA_VLM_ALLOW_MAIN_CAMERA_CAPTURE=1`.
  - VLM capture snapshots the active main camera state before screenshots and restores it if any leak is detected.
  - VLM camera is marked `internal/transient/syncable=False/show_in_ui=False` on the Python object.
- Bottom-layer verification still required:
  - Confirm `Camera.set_surface(0)` is a valid offscreen/no-presented-surface path in C++.
  - Confirm camera state changes for `vlm_review_camera` do not enqueue camera sync / dirty viewport updates.
  - Confirm camera roster / CameraView UI respects internal/transient flags or filters `vlm_review_camera` by name.
  - Confirm GPU screenshot readback from the VLM camera does not use the main presented render target.
- Not done in this pass:
  - No C++/Ninja/CMake build.
  - No C++ offscreen render-target implementation.
  - No CameraView UI roster filtering beyond Python-side object flags.
