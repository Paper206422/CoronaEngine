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

流程纠偏记录：

- 用户指出 task 1 提交前验证不足。该指出成立。
- task 1 已在提交后补测：语法检查、目标单测、CoronaCore discover、VS DevCmd + CMake `corona_engine` 增量 build。
- 补测结果已写入 `implementation.md`。其中 build 通过，目标单测通过，CoronaCore discover 仍被既有 `Scene.terrain_type` 缺失阻塞。
- 这次补测是补救，不算满足“提交前足量测试”。从 task 2 开始，提交前必须先完成与风险匹配的验证记录。

阻塞修复：

- `Scene.terrain_type` 缺失阻塞已修复，提交 `118e1a1c fix: default optional scene metadata on save`。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"` 当前通过，8 tests OK。

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

执行状态：已实施，验证阻塞修复提交 `df472e05 test: unblock validation checks`，代码提交 `11fb5e13 fix: clarify transform operation contract`。

实施摘要：
- `Actor` 明确区分 absolute setter 与 relative operation：`set_position/set_rotation/set_scale` 为绝对设置，`translate/rotate_delta/scale_delta` 为相对变换。
- `move/rotate` 保留为 relative alias；`scale(v)` 保持旧 Python API 的 absolute 语义，转发到 `set_scale(v)`，避免破坏已有直接调用。
- Object 面板数值输入改用 `SetPosition/SetRotation/SetScale`，与 C++ fast channel 的 operation 0/1/2 absolute 语义对齐，同时保留旧 `Move/Rotate/Scale` alias。
- AITool `transform_model` 统一为 relative tool，支持 `translate/rotate_delta/scale_delta`，旧 `move/rotate/scale` 作为兼容别名；absolute transform 继续由 `set_actor_transform` 承担。
- AITool transform prompt 已写明相对/绝对边界。

宏观检查结果：
- 本次没有为 Vision 层增加临时同步分支，也没有扩大双写状态；核心是把 native/API/UI/AI 工具的 transform contract 先统一。
- 后续 external Vision 适配可按明确契约做 object transform 映射，避免继续依赖含糊的 `Move/Rotate/Scale` 名称。

验证摘要：
- 通过：Python py_compile、actor transform 目标单测、transform_model 工具契约单测、CoronaCore 全量 discover、AITool 全量 discover、前端 build、前端 lint、C++ `corona_engine` 增量 build、`git diff --check`。
- 前端 lint 当前为 0 errors，仍有既有 Vue style warnings。
- AITool discover 当前通过，但测试环境仍打印部分工具注册 warning，原因是本地未安装完整 LangChain/httpx 依赖；目标 transform_model 分派已由新增测试覆盖。
- 真实 CEF UI E2E 尚无自动 harness，已在 `implementation.md` 记录手动验证步骤与剩余风险。

下一条任务前的宏观提醒：
- 第 3 条 gizmo drag end 持久化必须避免每帧写盘，也不要把保存逻辑散落在多个 UI 组件里。
- 开始第 3 条前先确认当前代码与文档记录均已提交，再做起点提交。

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

执行状态：已实施，起点提交 `c5ea6967 chore: mark start of gizmo persistence task`，代码提交 `23a02411 fix: persist gizmo transforms on drag end`。

实施摘要：

- C++ `actor-gizmo-transform` payload 新增 `phase`，前端可以可靠区分 start/move/end 回包。
- `createViewportGizmoController()` 新增 `onTransformCommit` 回调；drag move 继续只做实时同步，drag end 成功发送后只标记等待 commit。
- 前端只在同一 drag 的成功 end 回包到达时触发 `onTransformCommit`，避免旧 move 回包乱序到达时误保存。
- `MainPage.vue` 接入统一 commit，调用已有 `sceneService.saveActor(sceneId, actorName)` 写盘，失败时记录错误。
- 新增/扩展 `viewportGizmo.test.mjs`，验证 move 不保存、end 后旧 move 回包仍不保存、end 回包才保存一次。

宏观检查结果：

- 本次没有引入每帧保存，也没有把保存分散到多个 UI 组件；保存边界集中在 gizmo controller 的 end 回包确认处。
- 补 C++ `phase` 字段后，跨语言协议比单纯 JS 标记更稳，避免为了当前测试通过而接受乱序回包风险。
- 仍然以 Corona actor/SharedDataHub 为实时源，持久化只在用户完成一次 gizmo 编辑后提交，没有扩大 native、内置 Vision、external Vision 的多源状态。

验证摘要：

- 通过：`node editor\Frontend\src\utils\viewportGizmo.test.mjs`，覆盖 commit 时序和乱序 move 回包。
- 通过：CoronaCore 全量 discover，9 tests OK。
- 通过：前端 lint，0 errors，既有 66 warnings。
- 通过：前端 build，仅既有 Vite chunk warnings。
- 通过：C++ `corona_engine` 增量 build，日志 `build\agent-build.log`。
- 通过：`git diff --check`。
- 真实 CEF viewport gizmo E2E 尚无自动 harness，手动验证步骤与剩余风险已写入 `implementation.md`。

下一条任务前的宏观提醒：

- 第 4 条 material adapter/signature 不能只加 signature 触发 rebuild，否则会出现“重建了但材质没变”的假同步。
- 开始第 4 条前必须重新阅读 `implementation.md`、`TaskSplitting.md`、`AGENTS.md`，确认文档和代码提交均已完成，并先做起点提交。

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

执行状态：已实施，起点提交 `6fb2a98d chore: mark start of vision material task`，代码提交 `4cfbaeb3 fix: map vision principled material fields`。

实施摘要：

- 修复 `create_vision_material()` 实际默认成 diffuse 的问题：现在显式初始化 `type=principled_bsdf` 和空 `param`。
- `vision_material_adapter.cpp` 映射 Vision 可表达字段：
  - `subsurface -> subsurface_weight`
  - `anisotropic -> anisotropic`
  - `sheen -> sheen_weight`
  - `sheenTint -> sheen_tint` 灰度近似
  - `clearcoat -> coat_weight`
  - `clearcoatGloss -> coat_roughness` 反向近似
- `compute_vision_scene_signature()` fold 同一组已映射字段，避免 adapter 支持了但变化不触发 rebuild。
- `vision_material_adapter.h` 更新支持/近似/默认降级说明。
- 新增 `corona_vision_material_adapter_tests`，验证扩展 Optics 字段会改变 Vision material hash，并覆盖 clamp 路径。
- 修复 `BUILD_CORONA_TESTING=ON` 但 `BUILD_TESTING=OFF` 时 CTest 不生成测试清单的问题。
- 给 `VisionMaterialAdapterTests` 设置插件目录作为 working directory，保证 `vision-material-principled_bsdf` 可加载。

宏观检查结果：

- 没有只加 signature 空转；adapter 和 signature 成对更新。
- 没有把 unsupported 字段伪装成已适配：`bEnableLighting/specular/specularTint/legacy` 仍明确为降级或待定义策略。
- 测试没有停留在手动运行 exe；修通了 CTest 清单和工作目录，后续可重复执行。

验证摘要：

- 通过：`corona_vision_material_adapter_tests` target build。
- 通过：`ctest -R VisionMaterialAdapterTests`。
- 通过：C++ `corona_engine` 增量 build。
- 通过：`test-material-reset` target build 和 exe 运行，输出 `pass=4 fail=0`。
- 通过：`corona_network_protocol_tests` target build。
- 通过：全量项目 CTest，`NetworkProtocolTests` 与 `VisionMaterialAdapterTests` 均通过。
- 通过：CoronaCore 全量 discover，9 tests OK。
- 通过：`git diff --check`。
- 尚未完成 native/内置 Vision 的自动截图或数值渲染对比，手动复核步骤与剩余风险已写入 `implementation.md`。

下一条任务前的宏观提醒：

- 第 5 条是路线选择任务，不能直接开始在 external pipeline 上做名称匹配式同步。
- 开始第 5 条前必须重新阅读 `implementation.md`、`TaskSplitting.md`、`AGENTS.md`，确认代码和文档均已提交，并先做起点提交。
- 如果以 native 编辑完全对齐为目标，应优先论证并实施 “Vision JSON -> Corona actors -> EngineBuilt” 的统一 source-of-truth 路线；只有在明确必须保留 external pipeline 时，才进入 object identity/mapping 与增量镜像设计。

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

执行状态：已实施第一步，起点提交 `30b5cd37 chore: mark start of external alignment route task`，代码提交 `9bee50d6 fix: import vision models into engine built scene`。

实施摘要：

- 选择“Vision JSON -> Corona actors -> EngineBuilt”作为 native 编辑完全对齐的主路线。
- 新增 Vision JSON actor import helper，将可支持的 `model` shape 转换为 Corona actor data。
- `SceneTools.import_vision_scene_into_current_scene()` 导入可支持 model shape 后，保存 `import_mode=engine_built`，并调用 `load_vision_scene("")` 卸载 external pipeline。
- stable identity 使用 `vision:<abs_scene_path>#scene.shapes[index]` 写入 `actor_guid`。
- `Scene.save_data()` / `_build_actor_json()` 补 `actor_guid` 持久化，避免重启后失去 Vision shape identity。
- Vision material 做保守降级：base color、roughness、metallic、subsurface、anisotropic、sheen、coat 等可表达字段写入 Optics。
- `quad/cube` 等当前 Corona `Geometry(path)` 无法表达的 primitive 不再静默忽略，而是通过 `unsupported_shapes` 返回。

宏观检查结果：

- 没有走 external pipeline 增量镜像的局部补丁路线；当前修改减少 source-of-truth 数量，把后续编辑统一回 Corona scene/SharedDataHub。
- 没有用 shape name 做唯一匹配；重复导入和后续映射以 JSON path/index identity 为基础。
- 对 primitive 和复杂 matrix rotation 没有伪装成完全适配，后续必须通过明确 geometry/transform 能力补齐。

验证摘要：

- 通过：SceneTools Vision import 单测 4 个，覆盖 model 导入、material 降级、matrix/TRS transform、unsupported primitive/missing model、SceneTools 入口切 EngineBuilt。
- 通过：CoronaCore `actor_guid` 持久化目标单测。
- 通过：SceneTools tests discover、CoronaCore 全量 discover、py_compile。
- 通过：C++ `corona_engine` 增量 build。
- 通过：全量 CTest，`NetworkProtocolTests` 与 `VisionMaterialAdapterTests` 均通过。
- 通过：前端 lint，0 errors，既有 66 warnings。
- 通过：前端 build，仅既有 Vite chunk warnings。
- 通过：`git diff --check`。
- 真实 CEF 文件选择 + viewport E2E 尚无自动 harness，手动复核步骤和剩余风险已写入 `implementation.md`。

下一条任务前的宏观提醒：

- 第 6 条测试 scene 与验证流程必须补 external Vision import 后的完整用户链路验证，不能只停留在 parser/unit tests。
- 对 Task 5 暴露出的 `quad/cube` primitive 和 matrix rotation 缺口，应决定是先补测试 scene 揭示差异，还是先补 primitive-to-mesh/transform 分解；不能在后续验证里把 unsupported case 当成成功。

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

执行状态：已实施第一步，起点提交 `b646d84e chore: mark start of vision alignment validation task`，代码提交 `46c984ca test: add vision alignment workflow fixture`。

实施摘要：

- 新增固定 Vision alignment fixture：
  - 两个同名 `model` shape。
  - 一个 `quad` 和一个 `cube` unsupported primitive。
  - principled material。
  - matrix4x4 与 TRS transform。
  - replacement OBJ，用于导入后的 native model replacement 验证。
- 新增 workflow 测试，覆盖：
  - external Vision JSON import。
  - EngineBuilt 切换。
  - 重复导入去重。
  - 同名 actor 冲突处理。
  - material 降级字段。
  - native position/rotation/scale/visible/set_model/remove 编辑。
  - 保存快照中的 `vision.import_mode` 与 stable `actor_guid`。

宏观检查结果：

- 本次测试资产验证的是“external import -> Corona source-of-truth -> native edits -> saved state”的完整数据流，不是只证明 JSON parser 可以读字段。
- `quad/cube` 和 matrix rotation 仍作为显式缺口存在，测试不会把它们误判为已完全适配。
- 真实 viewport 视觉一致性仍需要后续 E2E/半自动截图工具补齐。

验证摘要：

- 通过：workflow 测试 2 个。
- 通过：SceneTools tests discover，6 tests OK。
- 通过：CoronaCore 全量 discover，9 tests OK。
- 通过：py_compile。
- 通过：C++ `corona_engine` 增量 build。
- 通过：全量 CTest，`NetworkProtocolTests` 与 `VisionMaterialAdapterTests` 均通过。
- 通过：前端 lint，0 errors，既有 66 warnings。
- 通过：前端 build，仅既有 Vite chunk warnings。
- 通过：`git diff --check`。

下一步宏观提醒：

- 如果继续推进“完全对齐”，不要把 Task 6 的 unsupported primitive 当成测试通过后的可忽略项；应优先补 primitive-to-mesh/Corona primitive geometry，或明确把 primitive 排除在当前对齐承诺外。
- 还需要真实 CEF/viewport E2E 或半自动截图对比，覆盖 SceneBar 文件选择、payload 可见性、native viewport 与 Vision viewport 的视觉一致性。

## Task 6 补充状态：真实 UI E2E 后的运行时修复

代码提交：`e15ebcc5 fix: keep vision imports stable during live rendering`

宏观检查结果：真实 UI 复测说明“重复导入时删除再新建同 guid actor”是局部最优。它能让数据层去重通过，但会破坏正在渲染的 actor/profile/geometry 生命周期。正确方向是让 `actor_guid` 成为真正稳定的 object identity：同一 Vision shape 复用同一 Corona actor，本次 JSON 新增才创建，不存在才删除。

实施摘要：
- `SceneTools.import_vision_scene_into_current_scene()` 导入 EngineBuilt actor 后不再强制调用 `load_vision_scene("")`。
- `OpticsSystem::apply_pending_vision_scene_load()` 对已处于 EngineBuilt 的空路径请求做幂等消费。
- 重复导入同一 Vision JSON 时复用既有 actor，更新 route/transform/optics，保留已去重名称，避免活跃渲染中删除再新建同一对象。
- workflow 测试新增断言：第二次导入同一 JSON 后 actor 对象 id 不变、未调用 `remove_actor`、`AlignedModel_1` 后缀保留。

验证摘要：
- 通过：`py_compile`。
- 通过：`python -m unittest editor.plugins.SceneTools.tests.test_vision_import editor.plugins.SceneTools.tests.test_vision_alignment_workflow`，6 tests OK。
- 通过：`python -m unittest discover -s editor\plugins\SceneTools\tests -p "test*.py"`，6 tests OK。
- 通过：`python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"`，9 tests OK。
- 通过：CTest，`NetworkProtocolTests` 和 `VisionMaterialAdapterTests`。
- 通过：C++ `corona_engine` 增量 build。
- 通过：前端 lint，0 errors，保留既有 66 warnings。
- 通过：前端 build，保留既有 Vite chunk warnings。
- 通过：`git diff --check`，仅 CRLF 提示。
- 通过真实 UI E2E：使用 VSCode CMake Tools 运行按钮启动；打开 `Vision Alignment E2E 20260616`；点击 SceneBar Vision 文件按钮；选择 `vision_scene.json`；重复导入后进程继续存活，日志无 `EXCEPTION_ACCESS_VIOLATION` / `SIGABRT` / `Received signal`，`.scene` 仍只有两个导入 actor 且 guid 稳定。

下一步宏观提醒：
- 继续推进完全对齐时，不要把当前 unsupported primitive 当成已完成能力；需要实现 primitive-to-mesh/Corona primitive geometry，或在对齐承诺中明确排除。
- UI E2E 已人工复测通过，但仍应沉淀为可重复的自动化或半自动化 viewport/CEF harness。
