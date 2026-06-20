# Vision scene.json 导入实现记录

提交：`6d6d08bdeeef020a21caceec75fb0c5d37ce3f5e`

## 目的

让 Editor 可以把外部 Vision `scene.json` 导入到当前 Corona 场景页，并让 Vision 渲染 pipeline 真正使用该 JSON，而不是只保存路径或同步相机。

本次导入语义是“覆盖当前场景页的 Vision source”：

- 不创建新的 `.scene`。
- 不新增 scene tab。
- 不修改 `project.ini [Project].scenes`。
- 当前 active camera 自动切到 `vision` backend。
- 如果 Vision JSON 有 camera，则同步到当前 scene active camera。
- 当前 `.scene` 持久化 `[vision] source_path/import_mode`，重启或切回该场景时可恢复。
- 切换到普通场景时清空外部 Vision source，恢复 engine-built Vision pipeline。

## 实现链路

Frontend：

- `SceneBar.vue` 的 Vision 导入按钮在 Vision 可用时显示。
- `OpenVisionScene()` 选择 JSON 后调用新接口，而不是直接调用旧的 `loadVisionScene(path)`。
- 导入成功后刷新当前 scene tree、选中返回的 camera，并刷新 render backend 状态。
- `bridge.js` 新增：

```js
importVisionSceneIntoCurrentScene(sceneName, path)
```

Python backend：

- `SceneTools.main.py` 新增：

```python
import_vision_scene_into_current_scene(scene_name, path)
```

- 该接口校验文件、解析 Vision JSON camera、更新当前 active camera、设置 `render_backend=vision`、写入 `[vision]` metadata、保存当前 scene，并调用：

```python
CoronaEditor.CoronaEngine.load_vision_scene(abs_path)
```

- camera 解析支持参考结构：

```text
scene.camera.param.transform.param.position
scene.camera.param.transform.param.up
scene.camera.param.transform.param.target_pos
scene.camera.param.fov_y
```

- 如果只有 `position + target_pos`，则计算 `forward = normalize(target_pos - position)`。
- `Scene` 新增 `vision_source_path` / `vision_import_mode` 的读取、保存和 `to_dict()` 输出。
- `MainView` 在项目初始化和场景切换时调用 `_apply_vision_source_for_scene(scene)`：
  - external scene：`load_vision_scene(source_path)`
  - normal scene：`load_vision_scene("")`

C++ optics：

- 原问题：`VisionSceneLoadEvent` 已经发布并写入 `pending_vision_scene_load_`，但 `apply_pending_vision_scene_load()` 只打印 warning，没有真正 import。
- 现在非空路径会调用 `load_external_vision_scene(path)`，成功后设置：

```cpp
vision_scene_source_ = VisionSceneSource::ExternalFile;
```

- `load_external_vision_scene()` 使用已有 Vision 导入链：

```text
Importer::import_scene -> init -> prepare -> prepare_view_texture
```

- 成功导入后才替换 `renderPipeline`，并清理旧 view contexts、zero-copy bridges 和 retained contexts。
- 空路径会重建 engine-built Vision pipeline：从 Corona scene 重新 build geometry/lights/camera。
- `run_vision_frame()` 只在 `EngineBuilt` 模式下执行 `sync_vision_dynamic_scene()`，避免外部 Vision JSON 被 Corona scene 覆盖。
- external 模式下仍同步当前 Corona camera 到 Vision pipeline，因此 viewport camera 由导入后的 active camera 驱动。

## 验证

已通过：

- `python -m py_compile editor\plugins\SceneTools\main.py editor\plugins\MainView\main.py editor\CoronaCore\core\entities\scene.py`
- 本次触碰前端文件 eslint：`bridge.js`、`SceneBar.vue`
- `git diff --check`

未完成：

- 当前 shell 找不到 `cmake`，未完成 C++ 构建验证。
- 全量前端 lint 仍被既有问题阻断：`EditorSettings.vue` 中 `cefQuery` 未定义，和本次提交无关。

## 参考 scene

```text
D:\Documents\GitHub\CoronaExample\test_vision\render_scene\cbox\vision_scene.json
```

---

## Task 2 实施记录：统一 transform 操作契约

代码提交：
- `df472e05 test: unblock validation checks`
- `11fb5e13 fix: clarify transform operation contract`

### 宏观检查

本任务没有选择给外部 Vision 或内置 Vision 增加一套临时 transform 特判，而是先统一 native 编辑入口的操作契约。这样后续 external Vision 适配可以明确按 absolute set 或 relative delta 映射到 Vision transform，不再依赖 `Move/Rotate/Scale` 这类含糊名称猜语义。

当前契约：
- `set_position()` / `set_rotation()` / `set_scale()`：绝对设置。
- `translate()` / `rotate_delta()` / `scale_delta()`：相对变换。
- Object 面板数值输入：绝对设置，前端内部改用 `SetPosition` / `SetRotation` / `SetScale`。
- AITool `set_actor_transform`：绝对设置。
- AITool `transform_model`：相对操作；旧 `move` / `rotate` / `scale` 作为兼容别名保留，但语义明确为相对平移、相对旋转、倍率缩放。

### 实施过程

- `Actor` 新增 `translate(delta)`、`rotate_delta(delta)`、`scale_delta(factor)`，并保留 `move()` / `rotate()` 作为 relative alias。
- `Actor.scale(v)` 保持旧 Python API 的 absolute 行为，转发到 `set_scale(v)`，避免把已有直接调用突然改成倍率缩放。
- Object 面板 actor/model 的 position/rotation/scale 输入从旧 `Move/Rotate/Scale` 改为 `SetPosition/SetRotation/SetScale`，与 C++ fast channel 的 operation 0/1/2 absolute 写入语义对齐。
- 前端 transform operation map 保留旧 `Move/Rotate/Scale` alias，避免其他旧调用立即失效。
- AITool MCP `transform_model` 支持并优先暴露 `translate` / `rotate_delta` / `scale_delta`，同时保留旧 `move` / `rotate` / `scale` 作为相对操作别名。
- 更新 AITool transform prompt，明确 `transform_model` 是相对变换，需要 absolute transform 时使用 `set_actor_transform`。
- 新增 `test_transform_contract_separates_absolute_and_delta_operations`，验证 actor absolute setter 与 delta operation 的差异。
- 新增 `test_transform_model_contract.py`，验证 `transform_model` 工具在 package 入口和 `scene_tools.py` 入口都执行 relative contract。

### 遇到的问题与处理

- `Scene.terrain_type` 阻塞 CoronaCore 全量测试：已先修复并提交 `118e1a1c fix: default optional scene metadata on save`，没有继续跳过。
- 前端 lint 被既有 `EditorSettings.vue` 的未声明全局 `cefQuery` 阻塞：改为 `window.cefQuery` 并提交 `df472e05`。
- AITool 全量测试在本地缺少 `langchain_core` / `yaml` 时无法进入测试主体：补充测试 stub，并让 fake `CoronaEditor.js_call_func` 同时兼容旧三参与当前两参调用，提交 `df472e05`。
- bundled npm 初次执行时 `node` 不在 `PATH`：按项目内 `third_party/node-v22.19.0-win-x64` 临时加入 `PATH` 后重跑，build/lint 均完成。

### 验证记录

提交 `11fb5e13` 前已执行：

- `python -m py_compile editor\CoronaCore\core\entities\actor.py editor\CoronaCore\tests\test_actor_network_broadcast.py editor\plugins\AITool\cai_extensions\mcp\tools\__init__.py editor\plugins\AITool\cai_extensions\mcp\tools\scene_tools.py editor\plugins\AITool\cai_extensions\mcp\configs\prompts.py editor\plugins\AITool\cai_extensions\mcp\configs\__init__.py editor\plugins\AITool\tests\test_transform_model_contract.py editor\plugins\AITool\tests\test_ai_rpc.py`：通过。
- `python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_transform_contract_separates_absolute_and_delta_operations`：通过。
- `python -m unittest editor.plugins.AITool.tests.test_transform_model_contract`：通过。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"`：通过，9 tests OK。
- `python -m unittest discover -s editor\plugins\AITool\tests -p "test*.py"`：通过，21 tests OK。输出中仍有工具注册 warning，因为测试环境未安装完整 LangChain/httpx 依赖，但测试用例已进入并覆盖目标逻辑。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run build`：通过。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run lint`：通过，0 errors，保留既有 66 warnings。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_engine -- --quiet`，通过 VS DevCmd wrapper 执行：通过。完整日志：`build\agent-build.log`。
- `git diff --check`：通过。

### E2E / 手动验证记录

当前 CLI 没有可自动驱动 CEF Editor Object 面板的 E2E harness，因此真实 UI 操作未自动执行。需要在 Editor 中手动复核：

1. 打开含有 actor/model 的 scene。
2. 在 Object 面板分别编辑 position、rotation、scale 的 x/y/z 数值。
3. 预期 C++ fast channel 收到 operation 0/1/2，语义为 absolute set，native viewport 立即更新。
4. 触发 `saveActor` 后切换 scene 或重启，预期 `.scene` 持久化后的 transform 与面板输入一致。
5. 使用 AITool `transform_model` 执行 `translate` / `rotate_delta` / `scale_delta`，预期基于当前 transform 做增量变化。
6. 使用 AITool `set_actor_transform` 执行 position/rotation/scale，预期直接写绝对值。

剩余风险：尚未通过真实 CEF UI 自动化验证 Object 面板输入到 native viewport 的完整链路；后续 task 6 应补可重复 E2E scene/harness。

## Task 3 实施记录：gizmo drag end 持久化

起点提交：`c5ea6967 chore: mark start of gizmo persistence task`

代码提交：`23a02411 fix: persist gizmo transforms on drag end`

### 宏观检查

本任务没有把保存逻辑散落到 Object 面板、MainPage pointerup 或每帧 move 回调里，也没有让 gizmo move 帧高频写盘。最终方案是在 gizmo 控制器里形成统一的 transform commit 边界：C++ drag end 成功回包确认后，前端只触发一次持久化；实时 viewport 更新仍继续由 SharedDataHub 快速通道负责。

实施中发现一个局部最优风险：如果只在 JS 端记录“end 命令已发出”，那么乱序到达的旧 move 回包可能提前触发保存。为避免这个问题，C++ `actor-gizmo-transform` 回包补充 `phase` 字段，JS 只在 `commitRequested && payload.phase === "end"` 时 commit。

### 实施过程

- `src/systems/ui/cef/cef_realtime_bridge.cpp` 的 gizmo transform payload 新增 `phase`，让前端能区分 start/move/end 回包。
- `createViewportGizmoController()` 新增 `onTransformCommit` 回调。
- `beginDrag()` 初始化 `commitRequested=false`。
- `endDrag()` 只在成功发送 end 命令后标记 `commitRequested=true`，不会直接写盘。
- `handleTransform()` 仍先更新 gizmo state 和 Object 面板 transform；只有收到同一 drag 的成功 end 回包时，才调用 `onTransformCommit(sceneId, actorName, actorType, transform)`，随后清空 `activeDrag`。
- `MainPage.vue` 接入 `onTransformCommit`，调用已有 `sceneService.saveActor(sceneId, actorName)`，失败时记录 `Actor gizmo transform save failed`，不阻断实时 transform。
- `viewportGizmo.test.mjs` 增加持久化时序测试：move 回包不保存；end 命令发出后，即使先收到旧 move 回包也不保存；只有 end 回包会保存一次。

### 验证记录

提交 `23a02411` 前已执行：

- `.\third_party\node-v22.19.0-win-x64\node.exe editor\Frontend\src\utils\viewportGizmo.test.mjs`：通过，覆盖 gizmo commit 时序和乱序 move 回包不保存。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"`：通过，9 tests OK。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run lint`：通过，0 errors，保留既有 66 warnings。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run build`：通过；仅保留既有 Vite dynamic/static import chunk warnings。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_engine -- --quiet`，通过 VS DevCmd wrapper 执行：通过。完整日志：`build\agent-build.log`。
- `git diff --check`：通过。

### E2E / 手动验证记录

当前 CLI 仍没有可自动驱动 CEF viewport gizmo 的 E2E harness，因此真实 UI 拖拽未自动执行。需要在 Editor 中手动复核：

1. 打开含有 actor/model 的 scene。
2. 选中 actor/model，使用 viewport gizmo 分别执行 move、rotate、scale 拖拽。
3. 拖拽过程中预期 native viewport 实时更新，且不会频繁写盘。
4. 松开鼠标后预期 C++ `actor-gizmo-transform` end 回包触发一次 `saveActor(sceneId, actorName)`。
5. 切换 scene 或重启 Editor 后，预期该 actor/model 的 position、rotation、scale 与松手后的最终 transform 一致。
6. 对 scale gizmo 复核 bounds center compensation：缩放后保存的 position/scale 应与 viewport 最终结果一致。

剩余风险：尚未通过真实 CEF UI 自动化验证 pointerup -> C++ end 回包 -> `saveActor` -> `.scene` 持久化的完整链路；后续 task 6 应补可重复 E2E scene/harness。

## Task 4 实施记录：扩展内置 Vision material adapter 和 signature

起点提交：`6fb2a98d chore: mark start of vision material task`

代码提交：`4cfbaeb3 fix: map vision principled material fields`

### 宏观检查

本任务没有只扩展 `compute_vision_scene_signature()` 触发 rebuild，而是同步修正了 Vision material adapter 的真实 material type 和可表达字段映射。这样 native Optics 字段变化会先被 signature 观察到，再在 rebuild 时实际进入 Vision `principled_bsdf` material，避免“重建了但结果不变”的假同步。

同时没有承诺所有 native material 参数完全等价。当前只映射 Vision `principled_bsdf` 明确支持且可合理近似的字段；`bEnableLighting`、`specular`、`specularTint`、legacy `ambient/diffuse/specular_color/shininess` 仍按降级处理，后续需要单独定义 unlit/specular/legacy 的转换策略。

### 实施过程

- 修复 `create_vision_material()` 的基础问题：旧代码 `MaterialDesc desc("principled_bsdf"); desc.init({})` 实际只设置 name，`MaterialDesc::init()` 会把 type 默认成 `diffuse`。现在显式传入：

```cpp
{ "type": "principled_bsdf", "param": {} }
```

- `vision_material_adapter.cpp` 新增可表达字段映射：
  - `OpticsDevice::subsurface` -> `subsurface_weight`
  - `OpticsDevice::anisotropic` -> `anisotropic`
  - `OpticsDevice::sheen` -> `sheen_weight`
  - `OpticsDevice::sheenTint` -> `sheen_tint` 灰度近似
  - `OpticsDevice::clearcoat` -> `coat_weight`
  - `OpticsDevice::clearcoatGloss` -> `coat_roughness = 1 - clearcoatGloss` 的 inverse approximation
- 对上述字段做合理 clamp，避免超过 Vision slot 范围。
- `compute_vision_scene_signature()` fold 同一组已映射字段，确保变化会触发 EngineBuilt Vision rebuild。
- `vision_material_adapter.h` 更新 mapping rules，明确 unsupported fields 使用 Vision defaults。
- 新增 `corona_vision_material_adapter_tests`：
  - 构造 base Optics 与 extended Optics。
  - 调用 `create_vision_material()` 创建 Vision material。
  - 用 material hash 验证扩展 Optics 字段会改变 Vision material。
  - 覆盖超范围输入的 clamp 路径。
- 修复 `BUILD_CORONA_TESTING=ON` 但 `BUILD_TESTING=OFF` 时 CTest 不生成测试清单的问题：根 `CMakeLists.txt` 在该条件下调用 `enable_testing()`。
- 给 `VisionMaterialAdapterTests` 设置 CTest working directory 为 Vision material 插件所在目录，保证 `vision-material-principled_bsdf` 能被动态加载。

### 遇到的问题与处理

- 新增测试首次运行返回 `-1073741515`：原因是测试 exe 不在运行时 DLL 目录。改用 `build/bin/RelWithDebInfo` 加入 `PATH` 和正确 working directory 后继续定位。
- 测试随后暴露 adapter 实际加载 `vision-material-diffuse`，并出现 principled 参数 unknown warning。根因是 `MaterialDesc::init({})` 默认 material type 为 `diffuse`；已改为显式 `type=principled_bsdf`。
- CTest 初次找不到任何测试：根因是项目自有 `BUILD_CORONA_TESTING` 没有启用 CTest；已修复。
- CTest 全量初次失败于 `NetworkProtocolTests` exe 未构建：先构建 `corona_network_protocol_tests`，再重跑全量 CTest，通过。

### 验证记录

提交 `4cfbaeb3` 前已执行：

- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_vision_material_adapter_tests -- --quiet`，通过 VS DevCmd wrapper 执行：通过。日志：`build\agent-vision-material-test-build.log`。
- `ctest --test-dir D:/Documents/GitHub/CoronaEngine/build -C RelWithDebInfo -R VisionMaterialAdapterTests --output-on-failure -V`，使用 VS 自带 `ctest.exe` 执行：通过。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_engine -- --quiet`，通过 VS DevCmd wrapper 执行：通过。日志：`build\agent-build.log`。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target test-material-reset -- --quiet`，通过。日志：`build\agent-vision-material-reset-build.log`。
- `build\bin\RelWithDebInfo\test-material-reset.exe`：通过，输出 `pass=4 fail=0`。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_network_protocol_tests -- --quiet`：通过。日志：`build\agent-network-tests-build.log`。
- `ctest --test-dir D:/Documents/GitHub/CoronaEngine/build -C RelWithDebInfo --output-on-failure -V`：通过，`NetworkProtocolTests` 与 `VisionMaterialAdapterTests` 均通过。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"`：通过，9 tests OK。
- `git diff --check`：通过。

### E2E / 手动验证记录

当前仍缺少 native/内置 Vision 对同一材质编辑的可视化自动对比 harness。需要在 Editor 中手动复核：

1. 打开含有 actor/model 的 EngineBuilt Vision scene。
2. 修改 actor optics 的 roughness、metallic、subsurface、anisotropic、sheen、sheenTint、clearcoat、clearcoatGloss。
3. 预期 native material 更新；切到 Vision backend 后，内置 Vision rebuild，且 material 至少按上述 mapping 发生可观察变化。
4. 修改 `bEnableLighting`、`specular`、`specularTint`、legacy material 字段时，当前不承诺 Vision 等价变化，应按默认/降级策略记录。

剩余风险：尚未做自动截图或数值渲染对比来证明 native 与 Vision 视觉结果接近；后续 task 6 应补材质测试 scene 和可重复对比流程。

## Task 1 实施记录：已有 actor 的 set_model() 真正替换 geometry/profile

代码提交：`61a90a46 fix: replace actor model profiles`

### 宏观检查

本任务没有选择给 Vision 层增加特殊同步补丁，而是先修复 native source-of-truth 本身的模型资源替换语义。这样后续内置 Vision 仍然只需要观察 Corona `SharedDataHub` 的 actor/profile/geometry 变化；不会扩大 native、内置 Vision、外部 Vision 之间的双写状态。

### 实施过程

- 重新阅读 `implementation.md`、`TaskSplitting.md`、`AGENTS.md`。
- 按用户要求先将当前 `implementation.md` 和 `TaskSplitting.md` 作为被 `.gitignore` 忽略的新增文件强制提交：`60b4e117 docs: add vision implementation task records`。
- 阅读 `Actor.set_model()`、`_create_and_add_profile()`、C++/fallback `Actor.remove_profile()`、`Geometry`、`Optics`、`Mechanics`、`Acoustics` wrapper 和现有 actor 测试。
- 确认旧问题：`Actor.set_model(route)` 对已有 `_geometry` 的 actor 只更新 `model_path`，不会替换 engine geometry/profile，因此 native viewport 和内置 Vision signature 都看不到真正的模型资源变化。
- 拆出 `Actor._create_profile_for_geometry(geometry)`，让 profile 创建可以返回 `stored profile` 以及新的 component wrapper。
- `_create_and_add_profile()` 现在保存 `self._profile`，使后续替换能精确移除旧 profile。
- `set_model(route)` 现在：
  - 更新 `model_path` 和 `final_model_path`。
  - 捕获旧 transform、optics 状态、mechanics 状态和 collision 类型。
  - 为新模型创建新的 `Geometry`、`Optics`、`Mechanics`、`Acoustics` 和 engine profile。
  - 激活新 profile，并把 Python wrapper 指向新 geometry/profile。
  - 恢复 transform、visible、material-ish optics 参数、mass/restitution/damping/physics/lock/collision 状态。
  - 调用 engine `remove_profile(old_profile)` 移除旧 profile，避免旧 geometry 继续挂在 actor 上造成重复渲染或 Vision 继续看到旧 mesh。
  - 重新注册 collision/on_move callback。
- 扩展 `test_actor_network_broadcast.py` 的 fake engine actor/profile/component，使测试能观察 profile 列表、remove_profile、状态恢复。
- 新增回归用例 `test_set_model_replaces_profile_and_preserves_edit_state`，覆盖：
  - 新旧 profile/geometry 不同。
  - actor engine 只保留新 profile。
  - `model_path/final_model_path` 更新。
  - position/rotation/scale、visible、metallic/roughness、mass、physics_enabled、collision 类型保留。

### 验证记录

已通过：

- `python -m py_compile editor\CoronaCore\core\entities\actor.py editor\CoronaCore\tests\test_actor_network_broadcast.py`
- `python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_set_model_replaces_profile_and_preserves_edit_state`
- `git diff --check`

已执行但未全量通过：

- `python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast`
  - 新增模型替换用例通过。
  - 整个文件仍被既有问题阻塞：`test_scene_actor_follow_camera_persists_in_scene_actor_section` 调用 `scene.save_data()` 时，`editor/CoronaCore/core/entities/scene.py:283` 访问不存在的 `Scene.terrain_type`，抛出 `AttributeError`。
  - 该失败与本任务的 actor model replacement 链路无关，但说明当前相关测试文件不能作为全绿回归信号。

未完成 / 剩余风险：

- 尚未做真实 editor E2E：在 UI 中对已有 actor 选择新模型文件后，观察 native viewport 新 mesh 出现、旧 mesh 消失，再切换到内置 Vision 验证 signature rebuild。
- 本任务未改 C++，未跑 C++ build。
- `Optics.to_dict()` 已暴露的 optics 参数会尽量恢复，但 mesh-level `materialColor` 不在当前 Python `Optics` wrapper 状态中，后续 material adapter 任务需要继续处理。
- 如果 engine `remove_profile()` 失败，当前实现会记录 warning，但 Python wrapper 已指向新 profile；真实运行时应在 E2E 中确认旧 profile 没有残留渲染。

### 2026-06-16 补充验证与流程纠偏

用户指出：每个 task 提交前都必须做足量测试，本任务在代码提交前只做了局部单测和语法检查，验证强度不足。该判断成立。本节记录的是提交后的补救验证，不应被视为满足“提交前足量测试”的流程要求。

补救验证时先将第 2 条任务的未提交 WIP 临时 stash，确保测试对象是已经提交的 task 1 代码。

补充执行：

- `python -m py_compile editor\CoronaCore\core\entities\actor.py editor\CoronaCore\core\entities\scene.py editor\plugins\SceneDatas\main.py editor\CoronaCore\tests\test_actor_network_broadcast.py`
  - 结果：通过。
- `python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_set_model_replaces_profile_and_preserves_edit_state`
  - 结果：通过。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"`
  - 结果：失败于既有 `Scene.terrain_type` 缺失问题；新增 task 1 用例通过。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_engine -- --quiet`，通过 VS DevCmd wrapper 执行。
  - 结果：通过。完整日志：`build\agent-build.log`。

仍缺失的足量验证：

- 真实 Editor E2E：从 UI 对已有 actor 选择新模型，确认 native viewport 新 mesh 出现、旧 mesh 消失、保存/切场景后仍一致。
- 内置 Vision E2E：同一 actor 替换模型后，确认 EngineBuilt Vision signature 触发 rebuild，Vision viewport 与 native 结果一致。

后续纪律修正：

- task 2 起不允许在只完成局部单测/语法检查时提交代码。
- 对跨模块或用户可见链路，必须先执行或明确记录单元、集成、E2E/手动 E2E 三层验证，再提交。

### 2026-06-16 修复 Scene.terrain_type 测试阻塞

代码提交：`118e1a1c fix: default optional scene metadata on save`

原因：

- CoronaCore 全量测试连续被 `Scene.save_data()` 中的 `self.terrain_type` 直接访问阻塞。
- 正常 `Scene.__init__` 会初始化 `terrain_type/terrain_path/vision_source_path/vision_import_mode`，但现有轻量测试用 `Scene.__new__` 构造保存对象，绕开了初始化。
- 修复 `terrain_type` 后，同一轻量测试继续暴露缺少 `engine_scene`，因此测试本身也需要补足最小 scene engine stub。

实施：

- `Scene.save_data()` 对 `script_path`、`terrain_path`、`terrain_type`、`vision_source_path`、`vision_import_mode` 使用安全默认值。
- 测试中的 `Scene.__new__` 对象补 `_main_camera` 和最小 `engine_scene.add_camera/set_active_camera` stub。
- 测试断言保存出的 `[terrain] path/type` 为空字符串，且缺省 vision 元数据时不写 `[vision]` section。

验证：

- `python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_scene_actor_follow_camera_persists_in_scene_actor_section` 通过。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"` 通过，8 tests OK。
- `python -m py_compile editor\CoronaCore\core\entities\scene.py editor\CoronaCore\tests\test_actor_network_broadcast.py` 通过。
- `git diff --check` 通过。

# 模型编辑操作与 Vision 同步对齐调查

## 调查目标

最终目标：让 native 层的模型编辑操作在行为、数据同步时机和可见结果上，能够与外部 Vision 层完全对齐。

本轮调查重点比较三条链路：

- 外部 Vision：从 Vision `scene.json` 导入后由 Vision 自身 pipeline 渲染的 `ExternalFile` 模式。
- 内置 Vision / Vision 兼容层：由 Corona scene 数据动态构建 Vision scene 的 `EngineBuilt` 模式。
- native：CoronaEngine 原生模型编辑与原生渲染链路。

模型编辑操作范围：

- 增：导入/添加模型、actor、geometry。
- 删：删除 scene object / actor / geometry。
- 改：模型资源、材质、可见性等非纯 transform 字段修改。
- 移动/旋转/平移：当前代码中主要表现为 geometry transform 的 position / euler_rotation / scale 更新；其中“移动/平移”按现有接口均落到 position 更新，需要继续确认前端是否存在语义差异。

## 调查方案

1. 先从 CodeGraph 追踪 Vision 外部导入、内置 Vision rebuild、每帧 camera/scene 同步入口。
2. 追踪 Editor 的模型编辑 API：scene tree 选中对象如何映射到 actor/geometry/profile/optics，增删改和 transform 操作如何落盘、如何下发到 C++。
3. 对比 native 与 Vision 兼容层：哪些编辑操作已经通过共享数据或签名检测自动适配，哪些只改 Python `.scene` 而没有实时同步，哪些 external Vision 明确不会同步。
4. 输出差异矩阵和适配方案：按操作列出当前状态、缺口、对齐 native/external Vision 所需改动。

## 调查过程记录

- 已确认仓库存在 `.codegraph/`，代码定位优先使用 CodeGraph。
- 已阅读既有记录：外部 Vision 导入会持久化当前 scene 的 `[vision] source_path/import_mode`，并在 C++ `OpticsSystem` 中切换到 `VisionSceneSource::ExternalFile`；空路径会恢复 `EngineBuilt`，从 Corona scene 重新 build Vision pipeline。
- 首轮 CodeGraph 入口：`VisionSceneLoadEvent`、`load_external_vision_scene`、`sync_vision_dynamic_scene`、`VisionSceneSource`、模型 transform 操作。
- 当前已确认：`run_vision_frame()` 只在存在可见 Vision camera 且 `vision_scene_source_ == EngineBuilt` 时执行 `sync_vision_dynamic_scene()`；因此外部 Vision JSON 模式不会被 Corona scene 的模型编辑覆盖。

## 已确认代码链路

### native / Corona scene 编辑入口

前端 Object 面板的 transform 数值输入：

- `editor/Frontend/src/views/sidebar/Object.vue`
  - `updateActorTransformFast()` / `updateModelTransformFast()` 通过 `window.coronaBridge.actorTransform(handle, operation, vector)` 走 C++ 快速通道。
  - `updateActorTransform()` / `updateModelTransform()` 只调用 `sceneService.saveActor()`，注释明确说明 transform 已由快速通道写入 `SharedDataHub`，这里仅写盘。
- `editor/Frontend/src/utils/bridge.js`
  - `sceneService.saveActor()` 调用 `SceneDatas.save_actor(sceneName, actorName)`。
- `editor/plugins/SceneDatas/main.py`
  - `save_actor()` 调用 `actor.save_data()`。
- `editor/CoronaCore/core/entities/actor.py`
  - `save_data()` 通过 `get_position()` / `get_rotation()` / `get_scale()` 回读 engine geometry 当前值，因此能把 C++ 快速通道写入的 transform 持久化。

C++ transform 快速通道：

- `src/systems/ui/cef/cef_realtime_bridge.cpp`
  - `handle_actor_transform_fast()` 解析 actor handle、operation、vec3。
  - 通过 `resolve_actor_geometry_handles(actor_handle)` 找到 geometry。
  - 写 `SharedDataHub::model_transform_storage()`：
    - operation 0：`position = value`
    - operation 1：`euler_rotation = value`
    - operation 2：`scale = value`

Python 直接操作入口：

- `editor/CoronaCore/core/entities/actor.py`
  - `move(v)`：读取当前 position，写入 `position + v`。
  - `rotate(euler)`：读取当前 rotation，写入 `rotation + euler`。
  - `scale(v)`：直接写入 absolute scale。
  - `set_position()` / `set_rotation()` / `set_scale()`：直接写 absolute transform。
- `editor/CoronaCore/core/components/geometry.py`
  - Geometry wrapper 调用 native `CoronaEngine.Geometry.set_position/set_rotation/set_scale`。
- `src/systems/script/python/corona_engine_api.cpp`
  - `Geometry::set_position()` / `set_rotation()` / `set_scale()` 直接写 `model_transform_storage`。
  - `Geometry::get_position()` / `get_rotation()` / `get_scale()` 直接读 `model_transform_storage`。

Scene 增删入口：

- `editor/plugins/SceneTools/main.py`
  - `create_actor()` → `_create_actor_impl()` → `Actor(...)` → `scene.add_actor(actor)`。
  - `remove_actor()` → `scene.remove_actor(actor)`。
- `editor/CoronaCore/core/entities/scene.py`
  - `add_actor()` 会把 Python actor 加到 `self._actors`，并调用 `self.engine_scene.add_actor(actor.engine_obj)`。
  - `remove_actor()` 会从 `self._actors` 移除，并调用 `self.engine_scene.remove_actor(actor.engine_obj)`。
- `src/systems/script/python/corona_engine_api.cpp`
  - `Scene::add_actor()` 写 `SharedDataHub::scene_storage()[scene].actor_handles`。
  - `Scene::remove_actor()` 从 `actor_handles` 擦除。

视口 gizmo 入口：

- `editor/Frontend/src/utils/viewportGizmo.js`
  - `actorGizmoDrag(start/move/end)` 发送到 C++。
  - `handleTransform()` 收到 C++ 返回的 transform 后发 `transform-update`，用于刷新 Object 面板 UI。
- `src/systems/ui/cef/cef_realtime_bridge.cpp`
  - `handle_actor_gizmo_drag()` 直接写 `model_transform_storage`。
  - move：写 position。
  - rotate：写 euler_rotation 的单轴分量。
  - scale：写 scale；如果有 local bounds，会额外补偿 position，使缩放中心保持在开始拖拽时的 bounds center。

当前发现的 gizmo 缺口：

- gizmo 路径实时写入 `SharedDataHub`，native 和内置 Vision 实时同步源一致。
- gizmo 结果只通过 `transform-update` 更新前端 Object 面板，当前未看到像数值输入 `@change` 那样调用 `saveActor()`。
- 因此 gizmo 的实时同步已适配，但持久化可能依赖之后手动保存 scene 或其他刷新路径；若目标是完全对齐，应补一个 drag end 后的 `saveActor(sceneId, actorName)` 或统一 transform commit 事件。

### native 渲染如何消费编辑结果

- `src/systems/optics/optics_system.cpp`
  - native `optics_pipeline()` 每帧遍历 enabled scene 的 `actor_handles`。
  - 链路：scene → actor → profile → optics → geometry → transform。
  - visible=false 会跳过该 object。
  - transform 通过 `ModelTransform::compute_matrix()` 变成 native model matrix。
  - material 读取 `OpticsDevice` 的 metallic/roughness/subsurface/specular/... 以及 `MeshDevice::materialColor`。
- `src/shared_data_hub.cpp`
  - `ModelTransform::compute_matrix()` 使用 `translate(position).rotate(qz*qy*qx).scale(scale)`。

这说明 native 的模型编辑实时显示不需要额外通知：只要 `SharedDataHub` 被写入，下一帧就会按最新数据渲染。

### 内置 Vision / Vision 兼容层如何消费编辑结果

- `include/corona/systems/optics/optics_system.h`
  - 注释明确：`VisionSceneSource::EngineBuilt` 随 `SharedDataHub` 动态同步；`ExternalFile` 禁用动态几何/灯光同步但仍使用当前 Corona camera。
- `src/systems/optics/optics_system.cpp`
  - `run_vision_frame()` 每帧先 `apply_pending_vision_scene_load()`。
  - 只有存在可见 Vision camera 且 `vision_scene_source_ == EngineBuilt` 时，才调用 `sync_vision_dynamic_scene()`。
  - `compute_vision_scene_signature()` fold：
    - enabled scene / actor handle / profile
    - visible
    - metallic / roughness
    - geometry handle / model_resource_handle / mesh count
    - 每个 mesh 的 `materialColor`
    - vertex buffer element count
    - transform position / euler_rotation / scale
  - `sync_vision_dynamic_scene()` 使用签名 + stable frame 去抖；签名稳定数帧后才 `rebuild_vision_scene()`。
  - `rebuild_vision_scene()` 调用 `Vision::build_vision_geometry(scene)`，再 `scene.prepare()`、`prepare_geometry()`、`prepare_lights()`、`upload_bindless_array()`、`compile()`、`rebuild_view_context_renderers()`、`invalidate_all_view_contexts()`。
- `src/systems/optics/vision/vision_geometry_adapter.cpp`
  - `build_vision_geometry()` 每次先 `scene.clear_shapes()` 和 `scene.geometry().data()->clear_meshes()`，避免删除对象后 Vision 侧遗留旧 mesh。
  - 遍历同一份 `SharedDataHub` scene → actor → profile → optics → geometry → transform。
  - visible=false 跳过。
  - Corona/native 使用 +Z-forward 左手坐标，Vision 使用 -Z-forward；object transform 通过 `F * M * F` 做坐标系转换，其中 `F = diag(1,1,-1,1)`。
  - mesh 顶点/法线 z 分量取反，三角形索引顺序交换以匹配 Vision 坐标系。
  - material 由 `create_vision_material(optics, mesh_dev)` 创建，目前只桥接 baseColor、roughness、metallic。

这说明内置 Vision 的模型编辑同步是“共享数据检测 + 全量重建”，不是 native 那样每帧直接消费 instance 表；实时性和成本不同，但数据源一致。

### 外部 Vision 如何消费编辑结果

- `src/systems/optics/optics_system.cpp`
  - `apply_pending_vision_scene_load()` 收到非空路径时调用 `load_external_vision_scene(path)`，成功后设置 `vision_scene_source_ = ExternalFile`，并清零 Vision 动态签名状态。
  - `load_external_vision_scene()` 通过 `import_vision_scene_from_file()` 导入 Vision JSON；成功后替换 `renderPipeline`，清空 view contexts / zero-copy bridges / retained contexts。
  - `import_vision_scene_from_file()` 设置 `vision::Global::scene_path = scene_path.parent_path()`，调用 `vision::Importer::import_scene(scene_path)`，然后 `pipeline->init()`、`pipeline->prepare()`、`frame_buffer()->prepare_view_texture()`。
  - `run_vision_frame()` 在 external 模式下不会调用 `sync_vision_dynamic_scene()`，但仍对每个 Vision camera 调用 `Vision::sync_vision_camera(*renderPipeline, *camera)`。

结论：外部 Vision 模式的模型/材质/灯光来自 Vision JSON 导入后的 Vision pipeline，不从 Corona `SharedDataHub` 同步模型编辑；只有 camera 继续由 Corona camera 驱动。

## 操作级差异矩阵

### 增：导入/添加模型

native：

- `SceneTools.create_actor()` 创建 `Actor`。
- `Actor.__init__()` 为 model 创建 `Geometry`、`Optics`、`Mechanics`、`Acoustics`，组装 `ActorProfile`。
- `Scene.add_actor()` 把 actor handle 加入 engine scene。
- native 下一帧遍历 `scene.actor_handles`，立即出现新模型。

内置 Vision / EngineBuilt：

- `compute_vision_scene_signature()` fold actor handle、profile、geometry handle、model resource handle、mesh count、vertex buffer element count。
- 添加模型会改变签名。
- `sync_vision_dynamic_scene()` 等签名稳定数帧后全量 `rebuild_vision_scene()`。
- `build_vision_geometry()` 从 Corona geometry 重建 Vision mesh/shape/material。
- 若 mesh GPU/CPU 数据尚未就绪，`candidate_count > 0 && instance_count == 0` 会触发重试，直到数据就绪或达到上限。

external Vision：

- 添加 Corona actor 不会进入外部 Vision pipeline。
- 外部 Vision 的 shape 已在 `Importer::import_scene()` 时从 JSON 建好，之后不看 Corona `scene.actor_handles`。

适配状态：

- native：已适配。
- 内置 Vision：已适配，但有 rebuild 延迟和全量重建成本。
- external Vision：未适配。

要适配 external Vision：

1. 必须建立“Corona actor ↔ Vision shape/instance”的稳定映射；当前 external import 没有把 Vision JSON shape 注册成 Corona actor，也没有保存 shape id 到 editor scene tree。
2. 添加 native actor 时，要么：
   - 方案 A：退出 external pipeline，转为 EngineBuilt，以 Corona scene 作为唯一源；或
   - 方案 B：保留 external pipeline，增量创建 Vision `Mesh/ShapeInstance/Material` 并插入 `renderPipeline->scene()`，然后执行与 topology change 等价的 refresh：`scene.prepare()`、`prepare_geometry()`、`prepare_lights()`、`upload_bindless_array()`、`compile()`、invalidate。
3. 如果要做到重启后也一致，还要把新增对象写回 Vision JSON，或维护一个 external overlay 文件。

### 删：删除模型 / actor

native：

- `Scene.remove_actor()` 从 Python `_actors` 移除，并调用 engine `Scene::remove_actor()`。
- C++ 从 `SceneDevice.actor_handles` 擦除。
- native 下一帧不再遍历该 actor。

内置 Vision / EngineBuilt：

- actor handle 从 enabled scene 消失，签名变化。
- rebuild 时 `build_vision_geometry()` 先 `clear_shapes()` 和 `clear_meshes()`，再只按当前 Corona actor 重建。
- 因此删除后的 mesh/shape 不会遗留在内置 Vision scene。

external Vision：

- 删除 Corona actor 不会删除 external Vision JSON 中导入的 shape。
- 如果当前 viewport 使用 external Vision，用户看到的外部 Vision 模型不会随 native 删除变化。

适配状态：

- native：已适配。
- 内置 Vision：已适配。
- external Vision：未适配。

要适配 external Vision：

1. 删除操作必须能找到对应 Vision instance/group。
2. 从 `renderPipeline->scene()` 的 groups/instances 中移除对应对象；若 Vision 当前没有按 name/id 暴露可删 API，需要补 Scene-level API，而不是直接散落操作内部 vector。
3. 删除后刷新 geometry accel/material/light 数据；保守做法复用现有 rebuild 序列，激进做法只更新 instances + TLAS。
4. 同步更新 Vision JSON 或 overlay。

### 改：替换模型资源

native 当前状态：

- `SceneDatas.select_model_file()` 对 file_type=`model` 调用 `actor.set_model(file_path)`。
- `Actor.set_model()` 当前只更新 `self.model_path = route`。
- 只有当 actor 没有 `_geometry` 时才会创建新 `Geometry` 和 profile。
- 对已有模型 actor，当前不会替换 C++ geometry/model_resource/mesh handles。

结论：

- “已有 actor 替换模型资源”目前 native 自身也没有完整适配。
- 因为 native 未真正替换 SharedDataHub geometry，内置 Vision 也无法检测到真实模型替换。

要先修 native：

1. 明确 `set_model(route)` 是“替换现有 geometry”而不是只改路径。
2. 保存旧 transform、visible、optics 参数、mechanics 参数、follow_camera 等需要保留的状态。
3. 构造新的 `Geometry(route)`。
4. 构造或重绑新的 `Optics/Mechanics/Acoustics`，确保它们引用新 geometry。
5. 用 `Actor.remove_profile(old_profile)` 或新增 replace-profile API，从 `ActorDevice.profile_handles` 中移除旧 profile handle，再加入新 profile handle。
6. 释放旧 geometry/model_resource/transform 句柄，避免 native 和 Vision 继续看到旧 mesh。
7. 写盘时使用新 route。

内置 Vision 适配：

- native 替换完成后，`compute_vision_scene_signature()` 已包含 `model_resource_handle`、mesh count、vertex buffer element count，因此会触发 rebuild。

external Vision 适配：

- 需要把 Corona 的 model replacement 映射成 Vision shape 的 mesh/material 替换。
- 最保守实现是重新生成/更新 external overlay 后重新 `load_external_vision_scene(path)`。
- 增量实现需要替换 Vision Mesh、更新 bindless/accel/material，并刷新 pipeline。

### 改：可见性 visible

native：

- 后端存在 `Actor.set_visible()` → `Optics.set_visible()` → `OpticsDevice.visible`。
- native `optics_pipeline()` 遇到 `!optics.visible` 会跳过 object。

内置 Vision：

- `compute_vision_scene_signature()` fold visible。
- `build_vision_geometry()` 遇到 `!optics->visible` 跳过 object。
- 因此如果调用后端 `SetVisible`，内置 Vision 会 rebuild 并对齐。

external Vision：

- 不同步 Corona `OpticsDevice.visible`。

前端状态：

- `SceneDatas.actor_operation()` 支持 `"SetVisible"`。
- 当前 `Object.vue` 中未看到调用 `"SetVisible"` 的 UI；Scene tree 会显示 actor visible 字段，但是否有可见性开关需要另查对应 UI。

适配状态：

- native：后端已适配。
- 内置 Vision：后端已适配。
- external Vision：未适配。

要适配 external Vision：

- 需要映射到 Vision instance/group 的 enabled/visibility 状态；如果 Vision 没有 visibility flag，可以通过移除/重新加入 instance 或设置材质透明/禁用参与构建实现，但推荐补正式 visibility 字段。

### 改：材质/渲染参数

native：

- native `optics_pipeline()` 读取 `OpticsDevice` 的多项参数：
  - `bEnableLighting`
  - `metallic`
  - `roughness`
  - `subsurface`
  - `specular`
  - `specularTint`
  - `anisotropic`
  - `sheen`
  - `sheenTint`
  - `clearcoat`
  - `clearcoatGloss`
  - `MeshDevice::materialColor`

内置 Vision：

- `compute_vision_scene_signature()` 目前只 fold：
  - `visible`
  - `metallic`
  - `roughness`
  - `materialColor`
- `vision_material_adapter.cpp` 目前只把以下字段映射到 Vision principled material：
  - `MeshDevice::materialColor` → `color`
  - `OpticsDevice::roughness` → `roughness`
  - `OpticsDevice::metallic` → `metallic`

差异：

- native 支持的 `subsurface/specular/specularTint/anisotropic/sheen/clearcoat/clearcoatGloss/bEnableLighting` 不会影响内置 Vision material。
- 即使这些字段被后端修改，当前 Vision 签名也不会变化，因此不会触发 rebuild。

适配状态：

- baseColor / roughness / metallic：内置 Vision 已适配。
- 其他 native material 参数：内置 Vision 未适配或无对应 Vision material 参数。
- external Vision：完全未跟随 Corona material edit。

要适配内置 Vision：

1. 扩展 `compute_vision_scene_signature()`，把所有 Vision 可表达的 Optics 字段 fold 进去。
2. 扩展 `create_vision_material()`，把 native Optics 字段映射到 Vision `principled_bsdf` 支持的参数。
3. 对 Vision 不支持的 native 字段，需要写明确的近似策略，例如：
   - `bEnableLighting=false`：生成不受光照影响的材质，或在 Vision 侧补 emission/unlit material。
   - legacy `ambient/diffuse/specular_color/shininess`：要么不承诺对齐，要么定义到 principled 参数的转换公式。
4. 增加最小验证 scene：同一 actor 修改 roughness/metallic/specular/clearcoat 等，确认 native 与 Vision 输出预期一致或文档声明近似。

要适配 external Vision：

- 需要能定位 external Vision material node，并把 native material edit 转换成 Vision JSON/material graph edit。
- external Vision 原生 material graph 可能比 Corona Optics 更复杂；完全对齐应定义 source-of-truth：
  - 如果 Corona 是源：外部 Vision material graph 需要被降级/覆盖成 Corona Optics 可表达的 principled 材质。
  - 如果 Vision JSON 是源：native Optics 需要扩展到能表达 Vision material graph，成本很高。

### 移动 / 平移：position

native：

- Object 面板数值输入：`ActorTransformFast` operation 0 写 absolute position。
- gizmo move：根据拖拽起点和 axis delta 算出 absolute `next_position`，写 position。
- Python `Actor.move(v)`：relative delta，写 `old_position + v`。
- Python `Actor.set_position(pos)`：absolute。

内置 Vision：

- signature fold position。
- rebuild 后通过 `F * M * F` 将 Corona/native +Z-forward 左手 transform 转成 Vision -Z-forward transform。
- 因此 position 改变会同步，但有 debounce/rebuild 延迟。

external Vision：

- 不同步 Corona position。
- external pipeline 只同步 camera。

语义差异：

- 目前“Move”在前端快速通道是 absolute position；Python `move()` 是 delta。
- “平移/translate”没有独立统一 API；实际都落到 position。

要对齐：

1. 明确统一操作契约：
   - `SetPosition(pos)`：absolute。
   - `Translate(delta)`：relative。
   - 前端现有 `Move` 建议改名或内部规范为 `SetPosition`。
2. external Vision 适配时不能只按 operation 名称判断，应按明确 contract 更新 Vision `o2w`。
3. 若保留 external pipeline，position 更新可优先做增量路径：更新映射到的 Vision `ShapeInstance::set_o2w()`，再更新 instances buffer/TLAS 并 invalidate。

### 旋转：euler_rotation

native：

- Object 面板数值输入：写 absolute euler_rotation。
- gizmo rotate：只更新拖拽轴分量，结果是 absolute euler_rotation。
- Python `Actor.rotate(euler)`：relative delta。
- Python `Actor.set_rotation(euler)`：absolute。
- `ModelTransform::compute_matrix()` 使用 `qz * qy * qx`。

内置 Vision：

- signature fold euler_rotation。
- rebuild 时使用 `compute_matrix()` 后做 `F * M * F` 坐标转换。

external Vision：

- 不同步 Corona rotation。

风险：

- native 的 Euler 组合顺序是 `qz*qy*qx`。
- Vision JSON 支持 `matrix4x4`、`look_at`、`Euler`、`trs` 等 transform 描述；其中 `TransformDesc::Euler` 使用 `translation * pitch_x * roll_z * yaw_y`，和 Corona 的内部约定不一定等价。

要对齐：

1. 对 external Vision 不要优先写 Euler 字段，优先写最终 `matrix4x4`，避免 Euler 顺序差异。
2. 内置 Vision 已走 matrix，因此风险较小。
3. 如果需要反向把 Vision JSON transform 拆成 Corona position/rotation/scale，应使用矩阵分解并写测试覆盖坐标系和旋转顺序。

### 缩放：scale

native：

- Object 面板数值输入：写 absolute scale。
- gizmo scale：写 absolute scale；如果有 local bounds，会同步补偿 position，保持缩放中心在原 bounds center。
- Python `Actor.scale(v)`：虽然名字像动词，但当前是直接写 absolute scale。
- Python `Actor.set_scale(scale)`：absolute。

内置 Vision：

- signature fold scale。
- rebuild 后 Vision 使用补偿后的 position/scale 和坐标转换矩阵。

external Vision：

- 不同步 Corona scale。

要对齐：

1. external 增量适配应复用 native gizmo 已计算出的 final position + scale，不要在 Vision 侧重复计算缩放中心补偿。
2. 如果 external Vision JSON 写回，建议写 `matrix4x4`，避免 scale/rotation 分解误差。

## native 与内置 Vision 兼容层总体适配情况

已经适配：

- 添加 actor/model：通过 SharedDataHub topology 签名触发 Vision rebuild。
- 删除 actor/model：通过 actor_handles 变化触发 Vision rebuild，且 rebuild 会清空旧 shapes/meshes。
- position / rotation / scale：通过 transform 签名触发 Vision rebuild。
- visible：后端支持，签名和 build 均处理。
- baseColor / roughness / metallic：Vision material adapter 已覆盖。
- camera：Vision 每帧同步当前 Corona camera。

部分适配 / 有差异：

- 实时性：native 下一帧直接消费 SharedDataHub；内置 Vision 需要签名稳定后全量 rebuild。
- 代价：native 更新 instance/material 表；内置 Vision 清空并重建 Vision geometry/material/lights。
- gizmo 持久化：实时同步 OK，但当前未看到 drag end 自动 `saveActor()`。
- `Move/Rotate` 语义：前端快速通道为 absolute，Python `move/rotate` 为 delta。
- material：内置 Vision 只覆盖 native material 的一小部分。

未适配：

- 已有 actor 的模型资源替换：native 层 `Actor.set_model()` 对已有 `_geometry` 不会替换 engine geometry。
- external Vision 模式下的任何 Corona 模型编辑同步：增、删、改、position、rotation、scale 都不会进入 external Vision pipeline。

## external Vision 与内置 Vision 的根本差异

内置 Vision：

- Corona `SharedDataHub` 是唯一模型数据源。
- Vision scene 是 Corona scene 的派生结果。
- native 编辑操作只要写入 SharedDataHub，Vision 兼容层就有机会检测并同步。

external Vision：

- Vision JSON / Vision pipeline 是模型数据源。
- 当前 Corona scene 只保存 external source path/import mode，并同步 camera。
- Vision JSON 中的 shapes/materials/lights 没有被注册为 Corona actor/profile/geometry/optics。
- native 编辑操作修改的是 Corona `SharedDataHub`，external pipeline 不读取这份数据。

所以 external Vision 未同步不是某个 transform 字段漏了，而是两套 scene graph 没有同一个 object identity 和 source-of-truth。

## 对齐适配路线建议

### 推荐路线：Corona scene 作为统一编辑源

目标：native 层模型编辑操作与 Vision 完全对齐。

做法：

1. external Vision 导入时，不只 `load_external_vision_scene(path)`，还解析 Vision JSON 的 shapes/materials/camera/lights，生成 Corona scene actor/profile/geometry/optics。
2. 生成每个 actor 的 stable identity，例如：
   - Vision shape `name`
   - JSON 路径 `scene.shapes[i]`
   - 若缺 name，生成 `vision_shape_<index>` 并写回 metadata。
3. 将 Vision transform 转成 Corona transform：
   - 优先读取 `matrix4x4`。
   - 做 Vision(-Z) → Corona(+Z) 坐标转换。
   - 分解出 position/rotation/scale。
   - 对无法稳定分解的 transform，保留 matrix metadata，同时给 native 一个近似 TRS。
4. 将 Vision model shape 的 `fn` 导入为 Corona `Geometry`。
5. 将 Vision material graph 降级映射到 Corona `Optics`：
   - 必须支持 base color、roughness、metallic。
   - 复杂 graph 先记录 metadata，native UI 未表达的部分声明为不可编辑或编辑后会被覆盖。
6. 切换到 `EngineBuilt` Vision 渲染，而不是继续使用 `ExternalFile` pipeline。
7. 后续增删改/移动/旋转/缩放只改 Corona actor；native 和内置 Vision 都从同一 SharedDataHub 同步。
8. 如仍需要保存为 Vision JSON，新增 export：Corona scene → Vision scene.json。

优点：

- 和现有 native 编辑链路最一致。
- 复用现有 EngineBuilt Vision rebuild。
- 不需要给 external Vision pipeline 补大量运行时编辑 API。

缺点：

- 外部 Vision 的复杂 material graph / renderer / integrator / medium / light 可能无法完全无损导入 Corona。
- 如果目标是“编辑外部 Vision 原始 JSON 的所有高级特性”，这条路线需要持续扩展 Corona 数据模型。

### 备选路线：External pipeline 增量镜像

目标：保留 external Vision pipeline，同时让 native 编辑操作投递到 external Vision。

需要新增：

1. `ExternalVisionSceneAdapter`
   - 保存 Vision JSON document 或 ProjectDesc。
   - 建立 Corona actor handle ↔ Vision shape/group/instance/material 的映射。
   - 提供 `add_actor` / `remove_actor` / `set_transform` / `set_visible` / `set_material` API。
2. OpticsSystem 编辑事件入口
   - 目前 Vision 同步靠每帧签名检测，没有增删改事件。
   - external 模式需要在 native 编辑发生时主动通知 adapter，或让 adapter 也做签名 diff。
3. Vision runtime edit API
   - transform-only：更新 mapped `ShapeInstance::set_o2w()`，调用 `Geometry::update_instances()` / `Geometry::update_accel()` / upload instances / invalidate。
   - topology/material change：复用保守 rebuild 序列。
4. JSON/overlay 写回
   - 否则 external edit 只在当前进程有效，重启后丢失。

优点：

- 最大程度保留 external Vision JSON 的 renderer/material/light 语义。

缺点：

- 当前代码没有 object identity 映射。
- Vision scene 内部增删改 API 不完整，容易直接触碰内部容器。
- 同一编辑要维护 Corona scene、Vision pipeline、Vision JSON 三份状态，复杂度高。

### 不推荐路线：native 与 external 各自编辑后做结果对齐

即保持 external Vision 和 native scene 两套独立 scene graph，只尝试在渲染结果层面对齐。

不推荐原因：

- 没有共同 object identity，无法可靠知道 native actor 对应 external 哪个 shape。
- 增删操作不可判定。
- material graph 表达能力不一致。
- 最终会变成大量脆弱的名称匹配和特例。

## 最小实施清单

若目标是“native 层模型编辑操作可以和外部 Vision 层完全对齐”，建议按以下顺序做：

1. 先修 native 缺口：实现已有 actor 的 `set_model()` 真正替换 geometry/profile，并保留 transform/optics/mechanics。
2. 统一 transform 操作契约：区分 `SetPosition/SetRotation/SetScale` 和 `Translate/RotateDelta/ScaleDelta`。
3. 给 gizmo drag end 补持久化：`saveActor(sceneId, actorName)` 或统一 transform commit 事件。
4. 扩展内置 Vision material adapter 和 signature，至少让 native 已暴露的材质参数有明确支持或明确降级。
5. 选择 external 对齐路线：
   - 若以 native 编辑为核心，优先做“Vision JSON → Corona actors → EngineBuilt”。
   - 若必须保留 external Vision pipeline，先做 object identity/mapping，再做 transform-only 增量同步，最后做增删和材质同步。
6. 建测试 scene：
   - 单模型：position/rotation/scale/gizmo scale compensation。
   - 多模型：增删顺序、同名对象。
   - 材质：baseColor/roughness/metallic/visible。
   - 替换模型资源。
   - external Vision JSON import 后执行同样编辑，验证 native viewport 与 Vision viewport 是否一致。

---

## Task 5 实施记录：选择并落地 external Vision 对齐路线第一步

起点提交：`30b5cd37 chore: mark start of external alignment route task`

代码提交：`9bee50d6 fix: import vision models into engine built scene`

### 宏观检查

本任务没有选择在 external Vision pipeline 上按名称猜测同步 transform，也没有让 Corona scene、Vision runtime scene、Vision JSON 三份状态并行双写。最终选择并开始实施“Vision JSON -> Corona actors -> EngineBuilt”：外部 Vision JSON 导入时先解析可编辑对象，生成 Corona actor；导入后卸载 external pipeline，后续 native 与内置 Vision 都继续以 Corona `SharedDataHub` 为统一 source-of-truth。

当前实现只导入 Vision `model` shape，`quad` / `cube` 等过程几何会在返回值 `unsupported_shapes` 中明确列出原因。这样不是跳过问题，而是避免把当前 `Geometry(path)` 不支持的 primitive 静默伪装成已适配。后续应补 primitive-to-mesh bake 或 Corona primitive geometry，再把这些 unsupported case 变成可导入对象。

### 实施过程

- 新增 `editor/plugins/SceneTools/vision_import.py`，负责把 Vision JSON shapes/materials/transform 转换为 Corona actor data。
- `model` shape 的 `param.fn` 解析为相对 Vision JSON 所在目录的绝对模型路径，支持常见模型扩展名。
- stable identity 使用 `vision:<abs_scene_path>#scene.shapes[index]` 写入 `actor_guid`。
- shape name 使用 Vision `name` / `names`，缺失时生成 `vision_shape_<index>`，并规避 `.` 影响 `.scene` actor key。
- transform 支持：
  - `matrix4x4`：做 Vision(-Z) 与 Corona(+Z) 的 Z flip，提取 position 与 column scale；rotation 暂不强行分解。
  - `trs`：导入 position/scale，并做 Z flip。
  - `Euler`：导入 position 与 pitch/yaw/roll 的保守映射。
- material 支持：
  - `color` 降级到 Corona Optics `diffuse/ambient`。
  - `roughness/metallic/subsurface_weight/anisotropic/sheen_weight/coat_weight/coat_roughness` 映射到 Optics 可表达字段。
- `SceneTools.import_vision_scene_into_current_scene()` 改为：
  - 继续解析并同步 Vision camera。
  - 删除同一 `actor_guid` 的旧导入 actor，避免重复导入同一 JSON 时堆叠对象。
  - 创建可支持的 Corona actor 并应用 Optics 降级字段。
  - 保存 `[vision] source_path`，但 `import_mode` 写为 `engine_built`。
  - 调用 `CoronaEngine.load_vision_scene("")` 卸载 external Vision pipeline，切回 EngineBuilt。
  - 返回 `imported_actor_count/imported_actors/unsupported_shapes`，让 UI 或日志能看到导入覆盖范围。
- `Scene.save_data()` / `_build_actor_json()` 补 `actor_guid` 持久化，保证 stable identity 重启后不丢。

### 遇到的问题与处理

- PowerShell 当前版本不支持 `&&` 作为命令连接符，提交命令第一次失败；已改为分两步 `git add` 与 `git commit`，没有影响代码。
- Vision primitive shapes 不能直接塞给当前 Corona `Geometry(model_path)`。本次用显式 `unsupported_shapes` 暴露，后续任务应正面实现 primitive-to-mesh/primitive geometry，而不是在导入时忽略。
- 任意 `matrix4x4` 的旋转分解容易因为坐标系、列主序和非均匀缩放出错。本次只提取 position/scale 并记录 approximation，避免错误旋转进入 native source-of-truth。

### 验证记录

提交 `9bee50d6` 前已执行：

- `python -m py_compile editor\plugins\SceneTools\vision_import.py editor\plugins\SceneTools\main.py editor\CoronaCore\core\entities\scene.py editor\plugins\SceneTools\tests\test_vision_import.py editor\CoronaCore\tests\test_actor_network_broadcast.py`：通过。
- `python -m unittest editor.plugins.SceneTools.tests.test_vision_import`：通过，4 tests OK。覆盖 model shape 导入、material 降级、matrix/TRS transform、unsupported primitive/missing model、SceneTools 入口切换 EngineBuilt。
- `python -m unittest editor.CoronaCore.tests.test_actor_network_broadcast.ActorNetworkBroadcastTests.test_scene_actor_follow_camera_persists_in_scene_actor_section`：通过，覆盖 `actor_guid` 与 `terrain_type` 等 scene save 边界。
- `python -m unittest discover -s editor\plugins\SceneTools\tests -p "test*.py"`：通过，4 tests OK。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"`：通过，9 tests OK。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_engine -- --quiet`，通过 VS DevCmd wrapper 执行：通过。日志 `build\agent-build.log`。
- `ctest --test-dir D:/Documents/GitHub/CoronaEngine/build -C RelWithDebInfo --output-on-failure`：通过，`NetworkProtocolTests` 与 `VisionMaterialAdapterTests` 均通过。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run lint`：通过，0 errors，保留既有 66 warnings。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run build`：通过，仅保留既有 Vite dynamic/static import chunk warnings。
- `git diff --check`：通过，仅有仓库行尾 CRLF 提示。

### E2E / 手动验证记录

当前仍没有可自动驱动 CEF 文件选择器和真实 viewport backend 切换的 E2E harness。需要在 Editor 中手动复核：

1. 打开一个普通 Corona scene。
2. 点击 SceneBar 的 Vision 导入按钮，选择包含 `model` shape 的 Vision `scene.json`。
3. 预期 scene tree 新增对应 model actor；返回 payload 中 `import_mode=engine_built`，`imported_actor_count` 与可支持 model shape 数一致。
4. 若 JSON 中包含 `quad/cube`，预期返回 `unsupported_shapes` 中列出这些 primitive，而不是静默成功。
5. 切换到 Vision backend 后，预期渲染来自 EngineBuilt 的 Corona actors；执行移动/旋转/缩放/删除/替换模型后，native 与内置 Vision 按前几项任务的同步机制保持一致。
6. 保存、重启或重新打开 scene 后，预期 actor 的 `actor_guid` 仍为 `vision:<path>#scene.shapes[index]`，不会重复导入同一 shape。

剩余风险：

- `quad/cube` 等过程几何尚未导入为 Corona actor，需要后续补 primitive-to-mesh 或 Corona primitive geometry。
- 任意 matrix transform 的 rotation 尚未可靠分解；当前只保守导入 position/scale。
- 尚未做真实 CEF 导入后的截图或像素对比，Task 6 需要补可重复测试 scene 与 E2E/半自动验证流程。

## Task 6 实施记录：测试 scene 与可重复验证流程

起点提交：`b646d84e chore: mark start of vision alignment validation task`

代码提交：`46c984ca test: add vision alignment workflow fixture`

### 宏观检查

本任务没有只补 parser happy path，也没有把真实 external Vision 对齐继续停留在口头手动步骤。新增的是固定 fixture 与 workflow 级测试：从 external Vision `scene.json` 导入开始，经过 EngineBuilt 切换、重复导入去重、同名对象处理、材质降级、native 编辑操作、删除与保存快照，形成一条可反复执行的数据流验证。

当前仍没有自动驱动真实 CEF 文件选择器和 viewport 截图对比的 harness，因此 UI E2E 仍明确记录为未自动化风险；但数据同步、identity、持久化和导入覆盖范围已经进入自动测试。

### 实施过程

- 新增 fixture 目录 `editor/plugins/SceneTools/tests/fixtures/vision_alignment/`：
  - `vision_scene.json`：包含两个同名 `model` shape、一个 `quad`、一个 `cube`、camera、principled material、matrix4x4/TRS transform。
  - `model_a.obj` / `model_b.obj`：两个可导入 model shape 的最小 OBJ。
  - `replacement.obj`：用于验证导入后 native `set_model()` 替换模型资源的测试模型。
- 新增 `test_vision_alignment_workflow.py`：
  - `test_fixture_covers_alignment_cases` 验证 fixture 能覆盖多模型、同名对象、matrix/TRS transform、材质降级和 unsupported primitive。
  - `test_external_import_then_native_edits_stay_on_engine_built_source` 验证：
    - SceneTools import 返回 `engine_built`。
    - external pipeline 通过 `load_vision_scene("")` 卸载。
    - 重复导入同一 Vision JSON 不重复堆叠 actor。
    - 同名 model shape 进入 scene 后按 `AlignedModel` / `AlignedModel_1` 处理。
    - 导入后执行 native set position/rotation/scale/visible/set_model/remove，再保存快照。
    - 保存结果仍保持 `vision.import_mode=engine_built` 与 stable `actor_guid`。

### 验证记录

提交 `46c984ca` 前已执行：

- `python -m py_compile editor\plugins\SceneTools\tests\test_vision_alignment_workflow.py`：通过。
- `python -m unittest editor.plugins.SceneTools.tests.test_vision_alignment_workflow`：通过，2 tests OK。
- `python -m unittest discover -s editor\plugins\SceneTools\tests -p "test*.py"`：通过，6 tests OK。
- `python -m unittest discover -s editor\CoronaCore\tests -p "test*.py"`：通过，9 tests OK。
- `git diff --check`：通过。
- `cmake --build D:/Documents/GitHub/CoronaEngine/build --config RelWithDebInfo --target corona_engine -- --quiet`，通过 VS DevCmd wrapper 执行：通过。日志 `build\agent-build.log`。
- `ctest --test-dir D:/Documents/GitHub/CoronaEngine/build -C RelWithDebInfo --output-on-failure`：通过，`NetworkProtocolTests` 与 `VisionMaterialAdapterTests` 均通过。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run lint`：通过，0 errors，保留既有 66 warnings。
- `$env:PATH = "<repo>\third_party\node-v22.19.0-win-x64;$env:PATH"; npm --prefix editor\Frontend run build`：通过，仅保留既有 Vite dynamic/static import chunk warnings。

### E2E / 手动验证记录

自动测试当前覆盖的是 Python/SceneTools 数据流、持久化快照和构建边界；真实 CEF UI 和 viewport 视觉对比仍未自动化。需要手动复核：

1. 在 Editor 中打开普通 Corona scene。
2. 通过 SceneBar Vision 导入按钮选择 `editor/plugins/SceneTools/tests/fixtures/vision_alignment/vision_scene.json`。
3. 预期 scene tree 中出现 `AlignedModel` 和 `AlignedModel_1` 两个 actor；`quad/cube` 通过返回 payload 或日志显示为 unsupported，而不是静默导入。
4. 切到 Vision backend，预期使用 EngineBuilt 结果。
5. 分别执行 position、rotation、scale、visible、set_model(replacement.obj)、删除第二个 actor。
6. 保存、切换 scene 或重启后，预期只保留编辑后的 actor，`actor_guid` 仍指向 `#scene.shapes[0]`，`vision.import_mode` 仍是 `engine_built`。

剩余风险：

- 真实 CEF 文件选择器、SceneBar payload 展示、viewport 图像一致性尚未自动截图验证。
- `quad/cube` primitive 仍是显式 unsupported；下一步需要实现 primitive-to-mesh 或 Corona primitive geometry，或者在验证报告中继续标为不可对齐项。
- `matrix4x4` rotation 分解仍未实现；当前 workflow 测试只锁定 position/scale 的保守导入。

## Task 6 补充实施记录：真实 UI E2E 暴露的 Vision 导入运行时问题

代码提交：`e15ebcc5 fix: keep vision imports stable during live rendering`

本次真实 UI E2E 发现两个运行时问题：已处于 EngineBuilt Vision 时重复消费空路径恢复请求会造成不必要的 pipeline 重建；重复导入同一 Vision JSON 时删除再新建同 guid actor 会在 Optics 活跃渲染中打断 actor/profile/geometry 生命周期，旧进程日志出现 `EXCEPTION_ACCESS_VIOLATION`。

修复策略没有引入 external pipeline 双写，而是继续坚持 `Vision JSON -> Corona actors -> EngineBuilt` 的单一 source-of-truth：`SceneTools.import_vision_scene_into_current_scene()` 不再强制调用 `CoronaEngine.load_vision_scene("")`；`OpticsSystem::apply_pending_vision_scene_load()` 对已经处于 EngineBuilt 的空路径请求做幂等消费；重复导入时按 `actor_guid` 复用既有 actor，只更新模型 route 变化、transform 和 optics 字段，保留 `AlignedModel_1` 这类去重后名称，只删除同一 `vision:<abs_path>#` source 下本次 JSON 已不存在的 actor。

验证：`py_compile`、目标 SceneTools 测试、SceneTools discover、CoronaCore discover、CTest、`corona_engine` C++ build、前端 lint/build、`git diff --check` 均通过。前端 lint 仍为既有 66 warnings；前端 build 仍为既有 Vite dynamic/static import chunk warnings；`git diff --check` 仅有 CRLF 提示。

真实 UI E2E：通过 VSCode CMake Tools 的 `play, 在终端窗口中启动所选目标: [corona_engine]` 按钮启动程序；点击“继续游戏/最近项目”并双击 `Vision Alignment E2E 20260616`；进入编辑器后确认 scene tree 包含 `AlignmentCamera`、`alignedmodel`、`alignedmodel_1`，视口显示导入模型，日志出现 `External CUDA buffer imported`；点击 SceneBar 的 Vision 场景文件按钮，在原生文件对话框中选择运行目录下的 `vision_scene.json`；重复导入后对话框关闭，进程 20 秒后仍存活。最新日志 `2026-06-16_20-29-16_corona.log` 出现 `Vision scene imported into current scene Scene/场景1.scene: ...\vision_scene.json`，未出现 `EXCEPTION_ACCESS_VIOLATION`、`SIGABRT` 或 `Received signal`。`.scene` 仍只包含 `alignedmodel` 和 `alignedmodel_1` 两个 actor，guid 分别指向 `#scene.shapes[0]` 和 `#scene.shapes[1]`，`camera0.render_backend = vision`，`[vision].import_mode = engine_built`。

剩余风险：`quad/cube` primitive 仍是显式 unsupported；`matrix4x4` rotation 仍只做保守导入；当前 UI E2E 仍是人工点击加日志/scene 文件交叉验证，尚未沉淀为自动化 CEF/viewport harness。
