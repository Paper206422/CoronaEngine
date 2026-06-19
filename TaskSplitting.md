# TaskSplitting

## 执行纪律

每次压缩上下文、执行任务、修改任务前，都必须先阅读根目录下的 `implementation.md` 和 `TaskSplitting.md`，确认当前目标、已知差异、执行顺序和最新约束。

每次准备执行 `TaskSplitting.md` 中的下一条任务时，都必须先站在更宏观的层面检查当前方案是否陷入了局部最优解：

- 如果当前做法只是在局部补丁上堆复杂度，而没有让 native、内置 Vision、外部 Vision 的数据源和操作契约更统一，应停止并重选更好的路线。
- 如果当前做法会扩大双写、三写状态，或让 object identity 更不清晰，应优先回到统一 source-of-truth 的方案。
- 如果发现已执行的方案方向错误，应回滚或重做为更稳妥的架构方案，而不是继续沿错误方向补特例。

确定要执行下一条 `TaskSplitting.md` 里的任务前，先 `git commit` 已完成的代码修改，让每一步修改可溯源、可回退、可审查。提交前应确认只提交当前任务相关文件，不混入无关改动。

提交时要把代码修改和个人调查/任务记录类 Markdown 修改分开提交，便于之后在推送前清理不希望公开的文档提交。`implementation.md`、`TaskSplitting.md` 这类过程记录应独立于代码提交；`AGENTS.md` 属于项目协作约定，与任务进度无关，不作提交。

每个任务都必须有足够强度的验证计划和实际执行记录，不能把只是“能编译”“source check 通过”当作行为正确的充分证明：

- 单元测试：覆盖本任务新增或修改的独立逻辑、解析、转换、状态更新、边界条件和回归点。
- 集成测试：覆盖本任务涉及的模块边界、语言边界、进程边界、持久化边界、接口契约和数据同步契约。
- E2E 测试：如果任务实现或改变的是完整用户可见链路，必须做自动 E2E；如果本地环境无法自动化，必须记录可重复的手动 E2E 步骤、预期现象、预期日志或结果、阻塞原因和剩余风险。
- 验证强度要与风险匹配。涉及跨模块数据流、用户可见行为、状态持久化、导入导出、后台任务、外部依赖、运行时初始化或性能/资源生命周期的任务，默认至少需要“单元 + 集成 + E2E/手动 E2E”三层覆盖。

## 最小实施清单里的内容

1. 先修 native 缺口：实现已有 actor 的 `set_model()` 真正替换 geometry/profile，并保留 transform/optics/mechanics。
2. 统一 transform 操作契约：区分 `SetPosition/SetRotation/SetScale` 和 `Translate/RotateDelta/ScaleDelta`。
3. 给 gizmo drag end 补持久化：`saveActor(sceneId, actorName)` 或统一 transform commit 事件。
4. 扩展内置 Vision material adapter 和 signature，至少让 native 已暴露的材质参数有明确支持或明确降级。
5. 已选择 external_live 对齐路线：
   - 导入外部 Vision scene 时创建/复用 Corona proxy actors。
   - Vision viewport 保持外部 Vision pipeline，不切回 `EngineBuilt`。
   - 先做 `actor_guid -> Vision ShapeInstance/group/instance` 稳定映射。
   - transform-only 走 `set_o2w() -> update_geometry() -> invalidate`，不 reload JSON，不替换 pipeline。
   - 增删替换走 runtime topology add/remove/reorganize，并用 overlay 记录重启恢复/撤销/导出意图。
6. 建测试 scene：
   - 单模型：position/rotation/scale/gizmo scale compensation。
   - 多模型：增删顺序、同名对象。
   - 材质：baseColor/roughness/metallic/visible。
   - 替换模型资源。
   - external Vision JSON import 后执行同样编辑，验证 native viewport 与 Vision viewport 是否一致。

## external_live 开工前审计后的调整顺序

本节是沿现有代码管线调查后的执行顺序修正。原清单的大方向成立，但不应把所有 native/EngineBuilt 缺口都挡在 external_live transform-only 之前；应先完成 stable identity、持久化和导入恢复，否则后续 adapter 没有可靠锚点。

调整后的第一阶段顺序：

1. 稳定身份前置：
   - `Scene.save_data()` 必须把 scene-level actor 的 `actor_guid` 写入 `[actors]`。
   - `_build_actor_json()` 必须读回 `actor_guid`。
   - C++ `ActorDevice` 建议增加 `actor_guid`，并通过 Python `Actor` 初始化同步到 engine actor；否则 OpticsSystem 只能依赖一次性 event binding，后续新增/重载 actor 难以恢复。
   - 验证：scene 保存/读取后 `actor_guid` 不变，同名 actor 不混淆。

2. external_live 场景元数据前置：
   - `Scene` 增加并持久化 `vision_overlay_path`、`vision_overlay_guid`。
   - `MainView._apply_vision_source_for_scene()` 必须识别 `import_mode == "external_live"`，不能只认旧的 `"external"`。
   - 旧 `"external"` / `ExternalFile` 行为保留。
   - 验证：切场景/重启恢复 external_live 时不会退回 `EngineBuilt` 或 unload external pipeline。

3. Python import + overlay：
   - `import_vision_scene_into_current_scene()` 解析 Vision JSON `scene.shapes`。
   - phase 1 只支持 `type == "model"`；`quad/cube/sphere` 等 primitive 必须记录 unsupported 或后续生成 proxy mesh，不能静默丢失。
   - 为 model shape 创建/复用 Corona proxy actor，写 `actor_guid -> shape_guid/json_path/shape_index` binding。
   - overlay 不驱动当前帧渲染，只用于 binding、恢复、撤销/导出。

4. C++ load request 与 source mode：
   - pybind 目前只有 `load_vision_scene(path)`，建议新增 external_live 专用 API，或扩展 API 但保持旧调用默认 `ExternalFile`。
   - `VisionSceneLoadEvent` / pending request 从 path 扩展为 mode + overlay path/guid。
   - `OpticsSystem::apply_pending_vision_scene_load()` 新增 `ExternalLive` 分支。

5. `ExternalVisionSceneAdapter` skeleton：
   - 初始化时读取 overlay bindings。
   - 通过 `actor_guid` 找 Corona actor handle，通过 `shape_index/json_path` 找 Vision group/instances；不使用 shape name 匹配。
   - Vision runtime 当前没有 shape guid metadata，phase 1 可用 JSON shape index / group import order 作为 binding 输入，但必须在 overlay 中显式记录并测试同名对象。

6. transform-only 同步：
   - factor 出 built-in Vision 已使用的 Corona->Vision matrix helper。
   - 每帧 diff proxy actor transform，更新 mapped `ShapeInstance::set_o2w()`。
   - 调用 `renderPipeline->update_geometry()` 和 `invalidate_all_view_contexts()`。
   - 验证没有 JSON reload、没有 pipeline replacement、没有 clear/rebuild。

7. 再处理 native 与 topology 前置：
   - `Actor.set_model()` 修复应在 external_live 替换模型阶段之前完成；它不阻塞 transform-only。
   - gizmo drag end 持久化应在 overlay 重启恢复/撤销之前完成；它不阻塞当前帧 transform sync。
   - 内置 Vision material adapter 扩展可后移；external_live first stage 只复用现有 `create_vision_material()` / `setup_vision_lights()`。

8. runtime topology 与 material：
   - 新增/删除/替换必须走 Vision Scene-level add/remove/reorganize API，不能散落直接改 `groups()` / `instances()`。
   - topology/material refresh 复用 runtime safe sequence，不调用 initialized pipeline 上的 full `renderPipeline->prepare()`。

审计结论：

- external_live transform-only 的真正阻塞项是 stable identity 和 import/recovery plumbing，不是 `set_model()`、gizmo 持久化或完整 material matrix。
- 替换模型、删除残留、material/emission 属于第二阶段，必须在 adapter skeleton 和 transform-only 路径可验证后再做。
- 如果实现中开始依赖 name matching、重载 JSON 或重新创建整个 pipeline 来响应 transform，说明方向偏离，应停止并回到本顺序。

## 分任务实现方法概括

### 1. 修复已有 actor 的模型资源替换

目标：让 native 自身先正确支持“已有 actor 替换模型资源”，否则 Vision 兼容层无法可靠同步。

实现概括：

- 阅读 `Actor.set_model()`、`Actor._create_and_add_profile()`、C++ `Actor::add_profile/remove_profile`、`Geometry`/`Optics`/`Mechanics` 生命周期。
- 明确替换语义：`set_model(route)` 对已有 `_geometry` 时也要替换 engine geometry，而不是只改 `model_path`。
- 替换前保存旧状态：position、rotation、scale、visible、Optics 参数、Mechanics 参数、follow_camera、碰撞/物理开关等。
- 构造新 `Geometry(route)`，并创建或重绑引用新 geometry 的 `Optics`、`Mechanics`、`Acoustics`。
- 用现有 profile 移除 API 或新增安全的 replace-profile API，确保 `ActorDevice.profile_handles` 指向新 profile。
- 恢复旧 transform 和必要组件参数，保存新 route。
- 验证 native viewport 使用新 mesh，内置 Vision signature 能看到 `model_resource_handle` 变化并 rebuild。

宏观检查：

- 不要只改 Python 路径字段。
- 不要让旧 profile 和新 profile 同时挂在 actor 上造成重复渲染。
- 不要依赖对象析构时机来“碰巧”释放旧 geometry；需要明确断开 SharedDataHub 引用。

### 2. 统一 transform 操作契约

目标：消除 `Move/Rotate` 在不同入口中 absolute 和 delta 混用的问题，为 native、内置 Vision、external Vision 统一编辑语义。

实现概括：

- 梳理所有 transform 入口：Object 面板快速通道、gizmo、Python `Actor.move/rotate/scale`、AITool/MCP 工具、Scratch wrapper。
- 定义明确操作名：
  - `SetPosition(pos)`、`SetRotation(rot)`、`SetScale(scale)` 表示 absolute。
  - `Translate(delta)`、`RotateDelta(delta)`、`ScaleDelta(delta_or_factor)` 表示 relative。
- 保留兼容旧入口时，应在边界层转换到新契约，避免下游按名称猜语义。
- C++ `ActorTransformFast` operation enum 应与新契约对齐，前端调用也同步改名。
- 文档和测试覆盖 absolute 与 delta 的差异。

宏观检查：

- 不要只把前端字符串改名而不改后端语义。
- 不要在 external Vision 适配时继续使用含糊的 `Move` 名称。
- 统一契约应服务后续所有渲染后端，而不是只修当前 UI。

### 3. 给 gizmo drag end 补持久化

目标：让 gizmo 拖拽不仅实时写入 `SharedDataHub`，也能可靠写回 scene/actor 数据，避免切场景或重启后丢失。

实现概括：

- 阅读 `viewportGizmo.js`、`MainPage.vue`、`Object.vue`、`SceneDatas.save_actor()` 的事件链。
- 在 drag end 成功后触发统一 transform commit：
  - 简单方案：调用 `sceneService.saveActor(sceneId, actorName)`。
  - 更稳方案：新增 `transform-commit` 事件，由 Object 面板或统一服务层负责写盘。
- 确保只在 drag end 保存，drag move 不高频写盘。
- 如果当前选中对象是 model tab 或 actor tab，都要能定位正确 scene/actor。
- 失败时记录错误，不影响实时 transform。

宏观检查：

- 不要把保存逻辑散落到多个 UI 组件造成重复保存。
- 不要在每帧拖拽时写盘。
- 最好让 Object 面板数值输入和 gizmo 共用同一个 commit 语义。

### 4. 扩展内置 Vision material adapter 和 signature

目标：让 native 已暴露的材质编辑在内置 Vision 中有明确同步能力或明确降级规则。

实现概括：

- 阅读 `OpticsDevice` 字段、native `optics_pipeline()` material 收集、`compute_vision_scene_signature()`、`vision_material_adapter.cpp`。
- 扩展 signature，把 Vision 可表达且用户可编辑的 Optics 字段 fold 进去。
- 扩展 `create_vision_material()`，将 native Optics 参数映射到 Vision `principled_bsdf` 支持的字段。
- 对 Vision 不支持或语义不同的字段，写清降级策略：
  - 例如 `bEnableLighting=false` 是否映射为 unlit/emission 材质。
  - legacy 参数是否转换为 principled 参数，还是明确不支持。
- 增加验证样例，确认 roughness/metallic/baseColor/visible 之外的参数不会静默失配。

宏观检查：

- 不要只扩展 signature 而不扩展 material adapter，否则会 rebuild 但结果不变。
- 不要承诺 Vision 无法表达的材质完全一致。
- 优先建立“支持/降级/不支持”的明确矩阵。

### 5. 实现 external_live 外部 Vision 对齐路线

目标：保留外部 Vision pipeline，同时让 native proxy actor 的编辑实时投递到 external Vision runtime scene。当前路线已经确定为 `external_live`，不再把导入后的 Vision viewport 切回 `EngineBuilt`。

实现原则：

- 外部 Vision pipeline 是实时渲染对象，不因 transform 编辑 reload JSON 或 replace pipeline。
- Corona proxy actors 是 native 编辑、选择、UI、保存入口。
- overlay 只用于保存 native 编辑意图、重启恢复、撤销/重做、导出，不驱动当前帧实时渲染。
- mapping 必须基于 `actor_guid -> shape_guid/json_path/instance refs`，不能靠 name 猜测。
- topology/material 变化使用安全 runtime refresh 边界，不调用 initialized pipeline 上的完整 `renderPipeline->prepare()`。

分任务：

1. `external_live` 模式和事件载荷：
   - 保留旧 `external` / `ExternalFile` 语义。
   - 新增 `ExternalLive` source 或等价模式。
   - 将 `VisionSceneLoadEvent` 或 C++ load API 扩展为可携带 `import_mode`、overlay path、overlay guid、bindings。
   - `apply_pending_vision_scene_load()` 按 mode 分支初始化 external pipeline 和 adapter。

2. Python import 与 overlay：
   - `SceneTools.import_vision_scene_into_current_scene()` 解析 Vision JSON model shapes。
   - 为每个支持的 model shape 创建或复用 Corona proxy actor。
   - 确保每个 proxy actor 有 `actor_guid`。
   - 生成 overlay：`overlay_guid`、`source_path`、`bindings`、`ops`。
   - `.scene [vision]` 写入 `import_mode=external_live`、`overlay_path`、`overlay_guid`。
   - phase 1 明确只支持 model shape；primitive shape 必须标记 unsupported 或生成 proxy mesh，不能静默丢失。

3. `ExternalVisionSceneAdapter` skeleton：
   - 新增 `src/systems/optics/vision/external_vision_scene_adapter.h/.cpp`。
   - 保存 `actor_guid -> actor_handle -> shape_guid/json_path` bindings。
   - 扫描 `renderPipeline->scene()` 建立 `actor_guid -> ShapeInstance/group/instance` 映射。
   - 初始化失败时给出可诊断日志，不回退到 name matching。

4. transform-only 同步：
   - `run_vision_frame()` 在 `ExternalLive` 下调用 adapter。
   - adapter 从 `SharedDataHub` 读取 proxy actor geometry transform。
   - 复用 built-in Vision 的 Corona->Vision matrix 转换。
   - 对 mapped `ShapeInstance(s)` 调用 `set_o2w()`。
   - 调用 `renderPipeline->update_geometry()` 和 `invalidate_all_view_contexts()`。
   - 不 clear/rebuild，不 reload JSON，不替换整个 pipeline。

5. runtime topology add/delete/replace：
   - 新增模型：Corona mesh/material -> Vision Mesh/ShapeInstance/ShapeGroup -> scene add path -> safe topology refresh -> overlay added record。
   - 删除模型：通过正式 Scene API 移除 group/instances，维护 flattened instances 和 geometry handles -> safe topology refresh -> overlay deleted record。
   - 替换模型：删除旧 shape + 新增新 shape，保留同一 `actor_guid` -> overlay replaced record。
   - 优先补 Vision Scene-level add/remove API，避免在业务代码里直接改私有容器。

6. material/emission first stage：
   - 复用 built-in Vision 的 `create_vision_material()`。
   - 复用 `setup_vision_lights()` 和既有 Area light 安全边界。
   - 第一阶段只承诺 baseColor、roughness、metallic 和现有 light setup。
   - 复杂 Vision material graph 先保留 metadata 或标记降级，不做复杂支持矩阵。

7. overlay 恢复、撤销/重做、导出：
   - overlay 不参与当前帧渲染。
   - 重启恢复时用 overlay 重建 proxy actors 和 bindings。
   - 导出时把 added/deleted/replaced 意图应用回 Vision scene 或生成新 JSON。

宏观检查：

- 每个阶段都要先确认 object identity 是否仍然清晰。
- 如果某个实现开始依赖 shape name、导入顺序猜测或多处散落双写，应停止并回到 adapter/overlay 边界。
- transform-only 路径必须证明没有 JSON reload、没有 pipeline replacement。
- topology/material 路径必须证明没有调用 full `renderPipeline->prepare()`。

### 6. 建测试 scene 与验证流程

目标：把同步对齐变成可重复验证的行为，而不是只靠肉眼检查。

实现概括：

- 准备最小 scene：
  - 单模型：测试 position、rotation、scale、gizmo scale compensation。
  - 多模型：测试增删顺序、同名 actor、删除后 Vision 不残留。
  - 材质：测试 baseColor、roughness、metallic、visible。
  - 替换模型资源：测试旧 mesh 消失、新 mesh 出现。
  - external Vision import：执行同样编辑，验证 native viewport 与 Vision viewport 对齐。
- 优先写自动化或半自动化验证：
- Python 层数据读写验证。
- C++ build 验证。
- 可渲染结果如果难自动断言，至少保存对比截图和操作步骤。
- 使用项目规定的 VS DevCmd + CMake build 流程验证。

宏观检查：

- 不要只测试 happy path。
- 不要只验证 native，必须覆盖内置 Vision 和 external Vision 路径。
- 测试应覆盖“重启/切场景后是否仍一致”，尤其是 gizmo 持久化和 external overlay/export。

