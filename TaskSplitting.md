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
5. 选择 external 对齐路线：
   - 若以 native 编辑为核心，优先做“Vision JSON -> Corona actors -> EngineBuilt”。
   - 若必须保留 external Vision pipeline，先做 object identity/mapping，再做 transform-only 增量同步，最后做增删和材质同步。
6. 建测试 scene：
   - 单模型：position/rotation/scale/gizmo scale compensation。
   - 多模型：增删顺序、同名对象。
   - 材质：baseColor/roughness/metallic/visible。
   - 替换模型资源。
   - external Vision JSON import 后执行同样编辑，验证 native viewport 与 Vision viewport 是否一致。

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

执行状态：已实施，代码提交 `61a90a46 fix: replace actor model profiles`。

实施摘要：

- `Actor.set_model(route)` 已从“只改 `model_path`”改为创建新 `Geometry` 和新 profile/component wrapper。
- 替换前捕获 transform、optics、mechanics、collision 状态；替换后恢复这些状态。
- 新 profile 激活后显式调用 engine `remove_profile(old_profile)`，避免旧 profile/geometry 继续挂在 actor 上。
- `_create_and_add_profile()` 保存 `self._profile`，后续替换可以精确定位旧 profile。
- 新增 `test_set_model_replaces_profile_and_preserves_edit_state`，验证 profile 替换和关键编辑状态保留。

验证摘要：

- 通过：`python -m py_compile editor\CoronaCore\core\entities\actor.py editor\CoronaCore\tests\test_actor_network_broadcast.py`
- 通过：`python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_set_model_replaces_profile_and_preserves_edit_state`
- 通过：`git diff --check`
- 已知阻塞：`python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast` 仍因既有 `Scene.terrain_type` 缺失失败，失败测试为 `test_scene_actor_follow_camera_persists_in_scene_actor_section`，不属于本任务链路。

下一条任务前的宏观提醒：

- 第 2 条 transform 契约统一应继续服务于统一 source-of-truth，而不是只改 UI 字符串。
- 开始第 2 条前必须先确认当前代码与文档记录均已提交，然后再做起点提交。

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

### 5. 选择 external Vision 对齐路线

目标：决定外部 Vision 与 native 编辑完全对齐时的 source-of-truth，避免在两套 scene graph 之间做脆弱双写。

推荐路线概括：Vision JSON -> Corona actors -> EngineBuilt。

- external Vision 导入时解析 JSON shapes/materials/camera/lights。
- 为每个 Vision shape 生成 Corona actor/profile/geometry/optics。
- 建立 stable identity：shape name、JSON path，或生成 `vision_shape_<index>`。
- 将 Vision transform 转为 Corona transform，复杂矩阵保留 metadata。
- 将 Vision material graph 降级到 Corona Optics，并记录无法表达的原始 metadata。
- 导入后切到 `EngineBuilt`，让后续 native 编辑和内置 Vision 使用同一 `SharedDataHub`。
- 如需要保留 Vision 文件工作流，补 Corona scene -> Vision scene.json export。

备选路线概括：保留 external pipeline 并新增增量镜像。

- 新增 `ExternalVisionSceneAdapter`。
- 建立 Corona actor handle 与 Vision shape/group/instance/material 映射。
- 补 Vision runtime edit API：transform、visibility、material、topology。
- transform-only 可尝试增量更新 `ShapeInstance::set_o2w()` 和 TLAS。
- topology/material 先复用保守 rebuild。
- 维护 JSON 或 overlay 写回。

宏观检查：

- 如果目标是 native 编辑完全对齐，优先统一到 Corona source-of-truth。
- 如果保留 external pipeline，会同时维护 Corona scene、Vision pipeline、Vision JSON 三份状态，必须先证明收益大于复杂度。
- 不要在没有 object identity 的情况下做名称猜测式同步。

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

