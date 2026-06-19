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

---

# external_live 路线确定与具体实现调查

## 路线结论

已选择 external Vision 对齐路线中的 `external_live` 导入模式。

新的目标不是把外部 Vision JSON 导入后切回 `EngineBuilt`，而是：

- 导入外部 Vision scene 时，仍在 Corona scene 中创建或复用 proxy actors，用于 native 编辑、选择、持久化和 UI 操作。
- Vision viewport 继续使用外部 Vision pipeline，也就是从 Vision `Importer::import_scene()` 得到的 pipeline。
- native 编辑通过稳定 object identity 同步到外部 Vision runtime scene。
- overlay 只保存编辑意图和恢复/导出所需信息，不作为当前帧实时渲染的数据源。

因此旧建议“Vision JSON -> Corona actors -> EngineBuilt”不再作为当前实现路线；它只保留为将来需要统一 source-of-truth 时的备选方案。

## 必须坚持的边界

`external_live` 的 source-of-truth 分层如下：

- 当前进程实时渲染：外部 Vision pipeline 的内存 scene。
- native 编辑入口和 UI 选择：Corona proxy actors。
- 稳定身份：`actor_guid` 和 overlay 中记录的 Vision `shape_guid` / JSON path / instance refs。
- 重启恢复、撤销/重做、导出：overlay。

禁止的做法：

- 不靠 Vision shape name 做匹配。
- transform 变化不 reload JSON。
- transform 变化不替换整个 pipeline。
- overlay 不驱动当前帧渲染。
- 删除/替换不能只改 Corona actor 而让 Vision instance 残留。
- runtime topology refresh 不能调用完整 `renderPipeline->prepare()`；已有注释说明 initialized pipeline 上这么做有 CUDA 资源生命周期风险。

## 已确认的代码事实

### Vision runtime 支持 transform-only 更新

相关文件：

- `vision/src/base/shape.h`
- `vision/src/base/mgr/scene.h`
- `vision/src/base/mgr/scene.cpp`
- `vision/src/base/mgr/pipeline.cpp`
- `vision/src/base/mgr/geometry.cpp`

已确认：

- `vision::ShapeInstance` 有 `set_o2w(float4x4)`，会写入 instance handle 的 `o2w_transposed`。
- `vision::Scene` 同时维护：
  - `groups_`
  - flattened `instances_`
  - `geometry_`
- `Scene::update_geometry_instances()` 会调用 `geometry_.update_instances(instances_)`。
- `Pipeline::update_geometry()` 的路径是：

```text
scene_.update_geometry_instances()
scene_.geometry_.upload()
scene_.geometry_.update_accel()
```

- `Geometry::update_accel()` 如果 mesh id 集合没变，会走 TLAS transform update；如果 mesh id 变化，则会 rebuild accel。

因此 transform-only 同步可以走：

```text
actor_guid
-> ShapeInstance(s)
-> set_o2w()
-> renderPipeline->update_geometry()
-> renderPipeline->invalidate_all_view_contexts()
```

这条路径不需要 clear/rebuild，不需要 reload JSON，也不需要替换 pipeline。

### OpticsSystem 当前 external 模式只同步 camera

相关文件：

- `include/corona/systems/optics/optics_system.h`
- `src/systems/optics/optics_system.cpp`
- `include/corona/events/optics_system_events.h`

已确认：

- 当前 `VisionSceneSource` 只有 `EngineBuilt` 和 `ExternalFile`。
- `load_external_vision_scene(path)` 会 import 外部 Vision JSON，成功后替换全局 `renderPipeline`，并清空 view contexts、zero-copy bridges、retained contexts。
- `run_vision_frame()` 只在 `vision_scene_source_ == EngineBuilt` 时调用 `sync_vision_dynamic_scene()`。
- external 模式下仍调用 `Vision::sync_vision_camera(*renderPipeline, *camera)`。

因此需要新增或扩展模式：

```cpp
enum class VisionSceneSource {
    EngineBuilt,
    ExternalFile,
    ExternalLive,
};
```

`ExternalFile` 保留旧语义：只加载外部 Vision pipeline，同步 camera，不同步 native 模型编辑。

`ExternalLive` 新语义：加载外部 Vision pipeline，同步 camera，同时通过 `ExternalVisionSceneAdapter` 把 proxy actor edits 增量同步到 Vision runtime scene。

### built-in Vision 已有可复用的坐标和材质逻辑

相关文件：

- `src/systems/optics/vision/vision_geometry_adapter.cpp`
- `src/systems/optics/vision/vision_material_adapter.cpp`
- `src/systems/optics/vision/vision_light_adapter.cpp`
- `docs/vision_integration.md`

已确认：

- Corona/native object transform 由 `ModelTransform::compute_matrix()` 生成。
- Corona/native 使用 +Z-forward 左手坐标，Vision 使用 -Z-forward；built-in Vision 用 `F * M * F` 做 object matrix 转换。
- mesh 顶点/法线 z 取反，三角形 winding 交换。
- `create_vision_material()` 当前只桥接 baseColor、roughness、metallic。
- `setup_vision_lights()` 会注入 spherical environment 和 sun point light。
- light adapter 有重要边界：不要移除 geometry 产生的 Area light，否则 ShapeInstance 可能持有 dangling pointer 并导致 CUDA 崩溃。

`external_live` 第一阶段应该复用这些函数和边界：

- factor 出 shared transform conversion helper，避免手写第二套 `F * M * F`。
- material/emission 第一阶段照搬 built-in Vision 的 `create_vision_material()` 和 `setup_vision_lights()`。
- 不做复杂支持矩阵；只明确 first stage 支持 baseColor、roughness、metallic 和已有 light setup。

### Python actor_guid 已存在，但 C++ ActorDevice 没有 guid

相关文件：

- `editor/CoronaCore/core/entities/actor.py`
- `editor/CoronaCore/core/entities/scene.py`
- `editor/plugins/SceneTools/main.py`
- `include/corona/shared_data_hub.h`

已确认：

- Python `Actor` 已有 `actor_guid` 字段。
- 缺失时会生成 `actor-{uuid}`。
- `Actor.to_dict()` 和 standalone actor 保存路径包含 `actor_guid`。
- 当前 Vision JSON import 只设置 `[vision] source_path/import_mode`、同步 camera、调用 `load_vision_scene(abs_path)`，不创建 proxy actors，不写 overlay。
- C++ `SharedDataHub::ActorDevice` 目前没有 `actor_guid` 字段。

因此 `external_live` 不能在 C++ 侧凭 actor handle 自己恢复 guid；必须在导入时把 mapping 明确传过去，或者把 guid 扩展进共享数据。

推荐第一阶段做法：

- Python import 创建/复用 proxy actor 后生成 overlay。
- 通过扩展 `VisionSceneLoadEvent` 或新增 C++ API，把 `import_mode=external_live`、overlay path、`actor_guid -> actor_handle -> shape_guid/json_path` mapping 传入 OpticsSystem。
- C++ adapter 以内存中的 mapping 建立 `actor_guid -> ActorBinding`，每帧用 actor handle 查 SharedDataHub transform。

## ExternalVisionSceneAdapter 设计

新增文件建议：

- `src/systems/optics/vision/external_vision_scene_adapter.h`
- `src/systems/optics/vision/external_vision_scene_adapter.cpp`

核心职责：

1. 接收 external_live import 后的 overlay/mapping。
2. 扫描当前 `renderPipeline->scene()`，建立 `actor_guid -> Vision ShapeInstance/group/instance` 的稳定映射。
3. 每帧或收到 dirty event 时，同步 proxy actor 的 transform/material/topology 到 Vision runtime scene。
4. 对 topology/material refresh 使用 OpticsSystem 已证明安全的 runtime refresh 边界。

建议数据结构：

```cpp
struct VisionInstanceRef {
    std::shared_ptr<::vision::ShapeGroup> group;
    std::shared_ptr<::vision::ShapeInstance> instance;
    std::string shape_guid;
    uint32_t group_index = 0;
    uint32_t instance_index = 0;
};

struct ActorBinding {
    std::string actor_guid;
    std::uintptr_t actor_handle = 0;
    std::vector<std::uintptr_t> geometry_handles;
    std::vector<VisionInstanceRef> instances;
    std::size_t last_transform_signature = 0;
    std::size_t last_material_signature = 0;
    bool deleted = false;
};
```

第一阶段不建议直接依赖 actor/shape name。匹配优先级应为：

1. overlay 中的 `actor_guid -> shape_guid`。
2. overlay 中的 `actor_guid -> json_path`。
3. import 阶段写入或保留的 shape metadata。

如果 Vision runtime 当前没有 shape metadata，可先用导入顺序建立 mapping，但 overlay 必须记录 JSON path 和导入时序号；这只能作为 phase 1 fallback，并且要在文档和测试中覆盖同名对象。

## Transform-only 同步

同步触发方式：

- phase 1 建议在 `run_vision_frame()` 的 `ExternalLive` 分支做轻量 signature diff。
- 不要求改完所有 transform 入口后再做，因为 Object 面板、gizmo、Python 直接操作都会写 `SharedDataHub`。
- 后续可以再补 dirty event，提高效率。

伪流程：

```text
if visible Vision camera and source == ExternalLive:
    adapter.sync_transforms_if_needed(*renderPipeline)
```

adapter 内部：

```text
for each ActorBinding:
    read actor -> profile -> geometry -> transform from SharedDataHub
    compute transform signature
    if unchanged: continue
    compute Corona model matrix
    convert to Vision matrix with shared F * M * F helper
    for each mapped ShapeInstance:
        instance->set_o2w(vision_matrix)
        instance->init_aabb()
mark geometry_dirty

if geometry_dirty:
    renderPipeline->update_geometry()
    renderPipeline->invalidate_all_view_contexts()
```

注意：

- 要复用 native gizmo 已经写入的最终 position/rotation/scale，不在 Vision 侧重复计算 scale center compensation。
- rotation 不要走 Vision JSON 的 Euler 描述，直接写最终 matrix。
- 如果一个 actor 有多个 geometry/profile，需要明确 phase 1 是否支持；否则先限制为一个 model actor 对一个 Vision shape，并在 overlay 中记录不支持原因。

## 新增、删除、替换模型

### 新增模型

新增 Corona proxy actor 后，`external_live` 必须把对应模型加入 Vision runtime scene。

建议封装安全 runtime add path：

```text
Corona Geometry/MeshDevice
-> Vision Mesh conversion
-> create_vision_material()
-> ShapeInstance + ShapeGroup
-> scene.add_shape(group, shape_desc_or equivalent)
-> safe topology refresh
-> overlay added record
```

如果 `Scene::add_shape()` 依赖 `ShapeDesc` 才能正确补 material/emission/medium refs，新增 path 应优先构造完整 desc 或新增正式 API，不要在 OpticsSystem 里散落手动 push `groups()` / `instances()`。

### 删除模型

删除必须同时维护：

- `Scene.groups_`
- `Scene.instances_`
- `Geometry` 内部 instance handles
- acceleration structure
- overlay deleted record

建议补 Vision Scene-level removal API，例如：

```cpp
bool Scene::remove_shape_group(const std::shared_ptr<ShapeGroup>& group);
bool Scene::remove_instances(std::span<const std::shared_ptr<ShapeInstance>> instances);
```

删除后执行 safe topology refresh。

### 替换模型

替换建议视作“删除旧 ShapeGroup/instances + 新增新 ShapeGroup/instances”，但保留同一个 `actor_guid`。

overlay 记录：

- old shape guid
- new shape guid
- replacement model path
- replacement time/order

native 侧还必须先修 `Actor.set_model()`，否则 proxy actor 本身不会真的换 geometry，external_live 也拿不到新 mesh。

## Topology/material refresh 边界

`src/systems/optics/optics_system.cpp` 的 `rebuild_vision_scene()` 已经写出了 initialized pipeline 的安全 runtime refresh 序列。

topology/material/light 变化时应复用这个边界，而不是 full prepare：

```text
scene.prepare()
renderPipeline->prepare_geometry()
renderPipeline->renderer().prepare_lights()
renderPipeline->upload_bindless_array()
renderPipeline->compile()
renderPipeline->rebuild_view_context_renderers()
renderPipeline->invalidate_all_view_contexts()
```

transform-only 则走更轻的：

```text
renderPipeline->update_geometry()
renderPipeline->invalidate_all_view_contexts()
```

## overlay 格式建议

`.scene` 增加或扩展 `[vision]`：

```ini
[vision]
source_path = D:\...\vision_scene.json
import_mode = external_live
overlay_path = Scene\MyScene.vision_overlay.json
overlay_guid = vision-overlay-...
```

overlay v1：

```json
{
  "schema": "corona.external_vision_overlay.v1",
  "overlay_guid": "vision-overlay-...",
  "source_path": "D:/.../vision_scene.json",
  "bindings": {
    "actor-...": {
      "shape_guid": "vision-shape-...",
      "json_path": "/scene/shapes/0",
      "instance_indices": [0],
      "proxy_model": "D:/assets/model.obj",
      "transform": {
        "position": [0, 0, 0],
        "rotation": [0, 0, 0],
        "scale": [1, 1, 1]
      }
    }
  },
  "ops": [
    {
      "op": "added",
      "actor_guid": "actor-...",
      "shape_guid": "vision-shape-...",
      "model": "D:/assets/new_model.obj"
    },
    {
      "op": "deleted",
      "actor_guid": "actor-...",
      "shape_guid": "vision-shape-..."
    },
    {
      "op": "replaced",
      "actor_guid": "actor-...",
      "old_shape_guid": "vision-shape-old",
      "new_shape_guid": "vision-shape-new",
      "model": "D:/assets/replacement.obj"
    }
  ]
}
```

overlay 原则：

- `bindings` 表示重启恢复和 runtime binding 所需的稳定关系。
- `ops` 表示用户编辑意图和导出所需历史。
- 当前帧渲染不从 overlay 读 transform；当前帧渲染从 Corona proxy actor 和 Vision runtime scene 读。
- overlay 写失败不应破坏当前帧实时渲染，但必须向 UI 报错，因为重启恢复会丢状态。

## Python import 需要新增的工作

`editor/plugins/SceneTools/main.py` 当前只导入 camera 和 source path。`external_live` 需要扩展：

1. 解析 Vision JSON shapes。
2. 对 model shape 创建或复用 Corona proxy actor。
3. 为每个 proxy actor 保证 `actor_guid`。
4. 生成 `shape_guid`：
   - JSON 中已有稳定 id/name 可记录，但不能只靠 name。
   - 没有 id 时生成 `vision-shape-{uuid}` 并写入 overlay。
5. 写 `.scene [vision] import_mode = external_live`。
6. 写 overlay path 和 overlay guid。
7. 调用 C++ load API 时传 import mode 与 mapping。

phase 1 只建议明确支持 Vision `model` shape。`quad/cube/sphere` 等 primitive shape 要么生成 proxy mesh asset，要么暂时标记 unsupported 并在 overlay 中记录；不能默默丢失。

## C++ event/API 需要新增的工作

当前：

```cpp
struct VisionSceneLoadEvent {
    std::string scene_path;
};
```

需要扩展为可以表达 import mode 和 overlay/mapping。建议最小结构：

```cpp
enum class VisionSceneImportMode {
    EngineBuilt,
    ExternalFile,
    ExternalLive,
};

struct VisionExternalBindingDesc {
    std::string actor_guid;
    std::uintptr_t actor_handle;
    std::string shape_guid;
    std::string json_path;
};

struct VisionSceneLoadEvent {
    std::string scene_path;
    VisionSceneImportMode import_mode = VisionSceneImportMode::ExternalFile;
    std::string overlay_path;
    std::string overlay_guid;
    std::vector<VisionExternalBindingDesc> bindings;
};
```

如果 Python binding 不方便直接传 vector，可先传 overlay path，然后 C++ 读取 overlay。但长期更清晰的是 Python 负责 import/actor 创建，C++ 负责 runtime binding，不让 C++ 再解析 editor 语义。

## OpticsSystem 修改点

建议修改点：

1. `VisionSceneSource` 增加 `ExternalLive`。
2. `pending_vision_scene_load_` 从 `optional<string>` 改成包含 path/mode/overlay/bindings 的 pending request。
3. `apply_pending_vision_scene_load()`：
   - `ExternalFile`：保持旧行为。
   - `ExternalLive`：先 `load_external_vision_scene(path)`，成功后初始化 `ExternalVisionSceneAdapter`，设置 source 为 `ExternalLive`。
   - empty path：保持恢复 `EngineBuilt`。
4. `run_vision_frame()`：
   - `EngineBuilt`：保持 `sync_vision_dynamic_scene()`。
   - `ExternalFile`：只同步 camera。
   - `ExternalLive`：先让 adapter 同步 runtime scene，再同步 camera/render。
5. pipeline 替换或 scene unload 时清空 adapter state。

## 验证计划

第一阶段 transform-only 必须至少验证：

- external_live import 后 Vision viewport 没有切回 `EngineBuilt`。
- proxy actor 存在且有稳定 `actor_guid`。
- 移动 proxy actor 后，Vision ShapeInstance 走 `set_o2w()`，没有 reload JSON，没有替换 pipeline。
- rotation/scale 使用最终 matrix，gizmo scale compensation 结果与 native viewport 一致。
- 多模型同名时不靠 name 匹配。
- 切场景/重启后 overlay 能恢复 binding。

topology 阶段必须验证：

- 新增模型进入 Vision runtime scene。
- 删除模型后 Vision runtime scene 无残留 instance。
- 替换模型后旧 mesh 不再渲染，新 mesh 渲染，同一 `actor_guid` 保持。
- topology refresh 不调用 full `renderPipeline->prepare()`。

material/emission 第一阶段必须验证：

- baseColor、roughness、metallic 能同步到 external_live 新增或替换后的 Vision material。
- `setup_vision_lights()` 不删除 geometry area light。
- 不支持的复杂 Vision material graph 有明确降级或保留策略，不静默承诺完全一致。

## 实施顺序

建议按以下顺序落地：

1. 文档和模式定义：引入 `external_live` import mode，保留旧 `external`。
2. Python import overlay：解析 Vision JSON model shapes，创建/复用 proxy actors，保存 overlay。
3. C++ pending load request：把 scene path/mode/overlay/bindings 传到 OpticsSystem。
4. `ExternalVisionSceneAdapter` skeleton：只做 binding 初始化和诊断日志。
5. transform-only sync：`actor_guid -> ShapeInstance(s) -> set_o2w() -> update_geometry() -> invalidate`。
6. native `set_model()` 修复：否则替换模型无法作为 external_live topology 的输入。
7. runtime add/delete/replace path：补正式 Scene API，避免散落改私有容器。
8. material/emission first stage：复用 built-in Vision material/light adapter。
9. overlay restart restore、undo/redo、export 支持。

---

# external_live 开工前管线审计

## 审计结论

当前 external_live 任务安排的大方向是合理的，但实现顺序需要调整。

最关键的前置不是 `set_model()`、gizmo 持久化或扩展 built-in Vision material adapter，而是：

1. 稳定 object identity 能跨保存/重启保留。
2. external_live import mode 能跨 Python -> C++ event -> OpticsSystem 渲染线程传递。
3. 场景切换/初始化恢复时能识别 `external_live`，不退回旧 `external` 或 `EngineBuilt`。
4. adapter 能用 `actor_guid -> shape_index/json_path -> ShapeGroup/ShapeInstance` 建立映射，不靠 name。

因此建议把 external_live 第一阶段定义为：

```text
stable identity + overlay/import plumbing
-> ExternalLive mode request
-> adapter binding skeleton
-> transform-only set_o2w/update_geometry/invalidate
```

`Actor.set_model()` 修复、gizmo drag end 持久化、material 支持矩阵和 topology add/delete/replace 都应排在 transform-only 验证之后，除非当前阶段明确要实现替换模型或重启恢复。

## 导入管线审计

当前调用链：

```text
SceneBar.OpenVisionScene()
-> bridge.sceneService.importVisionSceneIntoCurrentScene(sceneName, path)
-> SceneTools.import_vision_scene_into_current_scene(scene_name, path)
-> CoronaEngine.load_vision_scene(abs_path)
-> Events::VisionSceneLoadEvent{scene_path}
-> OpticsSystem pending_vision_scene_load_
-> run_vision_frame()
-> apply_pending_vision_scene_load()
-> load_external_vision_scene(path)
-> import_vision_scene_from_file()
-> Vision Importer::import_scene()
```

已确认代码事实：

- `SceneTools.import_vision_scene_into_current_scene()` 当前只解析 camera，写 `[vision] source_path/import_mode=external`，不创建 proxy actors，不写 overlay。
- Python API `CoronaEngine.load_vision_scene(path)` 当前只能传 path。
- `VisionSceneLoadEvent` 当前只有 `std::string scene_path`。
- `OpticsSystem::pending_vision_scene_load_` 当前是 `std::optional<std::string>`。
- `OpticsSystem::apply_pending_vision_scene_load()` 非空 path 总是设置 `VisionSceneSource::ExternalFile`。

结论：

- external_live 不能先写 adapter 再回头补事件；adapter 没有 mode、overlay、binding 输入。
- 最小安全做法是新增 external_live 专用 load API，或扩展 load API 但保持旧 path-only 调用默认 `ExternalFile`。
- pending request 应变成结构体，至少包含 path、mode、overlay_path、overlay_guid。

## 场景恢复管线审计

当前恢复链：

```text
Scene.read_data()
-> scene.vision_source_path / scene.vision_import_mode
-> MainView._apply_vision_source_for_scene(scene)
-> CoronaEngine.load_vision_scene(source_path or "")
```

已确认代码事实：

- `Scene.read_data()` 只读 `source_path` 和 `import_mode`。
- `Scene.save_data()` 只写 `source_path` 和 `import_mode`。
- `MainView._apply_vision_source_for_scene()` 只在 `import_mode == "external"` 时 load 外部 Vision scene；其他 mode 会 `load_vision_scene("")`。

结论：

- 如果只把导入时写成 `external_live`，切场景/重启会被当前恢复逻辑当作非 external，从而 unload external scene 并恢复 EngineBuilt。
- `vision_overlay_path` / `vision_overlay_guid` 必须进入 `Scene` 持久化字段。
- 恢复时需要调用 external_live load request，而不是旧 `load_vision_scene(path)`。

## actor_guid 管线审计

当前 actor identity 链：

```text
Actor.__init__()
-> actor_guid 生成/读取
-> Actor.to_dict()
-> scene tree / network payload
```

已确认代码事实：

- Python `Actor` 有 `actor_guid`，缺失时生成 `actor-{uuid}`。
- standalone actor `save_data()` 会写 `base.actor_guid`。
- `Actor.to_dict()` 会输出 `actor_guid`。
- scene-level `Scene.save_data()` 当前 `[actors]` 不写 `actor_guid`。
- `Scene._build_actor_json()` 当前不读 `actor_guid`。
- C++ `SharedDataHub::ActorDevice` 当前没有 `actor_guid`。

结论：

- external_live proxy actor 如果保存在 `.scene [actors]` 中，重启后会生成新 guid，overlay binding 断裂。
- 第一项代码任务应先修 scene-level actor_guid 持久化。
- 建议 C++ `ActorDevice` 增加 `actor_guid`，Python `Actor` 初始化后同步到 engine actor。否则 OpticsSystem 只能依赖一次性 event binding，不利于重载、切场景和后续新增 actor。

## Vision runtime 更新管线审计

transform-only 可用路径：

```text
ShapeInstance::set_o2w()
-> Scene::update_geometry_instances()
-> Geometry::update_instances()
-> Pipeline::update_geometry()
-> Geometry::upload()
-> Geometry::update_accel()
-> Pipeline::invalidate_all_view_contexts()
```

已确认代码事实：

- `ShapeInstance::set_o2w()` 只写 instance handle transform。
- `Geometry::update_accel()` 在 mesh id 集合不变时走 TLAS transform update；mesh id 变化时才 rebuild accel。
- `Pipeline::update_geometry()` 不 clear shapes，不 reload JSON，不替换 pipeline。

结论：

- transform-only 路线合理，可以作为第一阶段行为闭环。
- adapter 每帧 diff `SharedDataHub` transform 即可覆盖 Object panel fast path、gizmo、Python direct transform，因为这些路径最终都写 `model_transform_storage`。
- 应复用 built-in Vision 的 Corona->Vision matrix 转换；不要在 adapter 中手写第二套坐标逻辑。

## topology 管线审计

已确认代码事实：

- `Scene::add_shape()` 不只是 push group，还会补 material、emission、medium 引用，并把 group instances 追加到 flattened `instances_`。
- `Scene::clear_shapes()` 只清 `groups_` 和 `instances_`。
- `Pipeline::clear_geometry()` 会清 shapes 和 mesh registry。
- `build_vision_geometry()` 会 full clear，适合 EngineBuilt，不适合 external_live 增量编辑。
- 当前 Vision Scene 没有对称的 public remove shape/group API。

结论：

- 新增/删除/替换不能直接散落修改 `scene.groups()` / `scene.instances()`。
- topology 阶段必须先补正式 Scene-level add/remove/reorganize API，或封装在 adapter 内部的唯一窄口。
- topology refresh 应复用 `rebuild_vision_scene()` 已验证的 runtime safe sequence：

```text
scene.prepare()
renderPipeline->prepare_geometry()
renderPipeline->renderer().prepare_lights()
renderPipeline->upload_bindless_array()
renderPipeline->compile()
renderPipeline->rebuild_view_context_renderers()
renderPipeline->invalidate_all_view_contexts()
```

- 不能调用 initialized pipeline 上的 full `renderPipeline->prepare()`。

## Geometry/material 复用审计

已确认代码事实：

- Corona mesh -> Vision mesh 转换逻辑在 `vision_geometry_adapter.cpp` 的匿名命名空间中。
- `load_cpu_mesh_from_resource()` / `load_cpu_mesh_from_buffers()` 当前不是 header API。
- built-in Vision 的 vertex z-flip、normal z-flip、triangle winding swap 只在 `build_vision_geometry()` 内部实现。
- `create_vision_material()` 已作为 header API 暴露，可复用。
- `setup_vision_lights()` 已作为 header API 暴露，可复用，但必须遵守“不移除 Area light”的边界。

结论：

- external_live topology add path 不应复制 mesh conversion 代码。
- 在 topology 阶段前，应先把“Corona GeometryDevice/MeshDevice -> Vision Mesh/ShapeInstance”抽成共享 helper。
- material/emission first stage 可以直接复用 `create_vision_material()` 和 `setup_vision_lights()`。

## 编辑入口审计

transform：

- `handle_actor_transform_fast()` 写 absolute position/euler/scale。
- `handle_actor_gizmo_drag()` 写 final position/euler/scale；scale 已在 native 侧补偿 bounds center。
- Python `Actor.set_position/set_rotation/set_scale()` 也写 geometry transform。

结论：external_live transform-only 不需要先改所有入口，per-frame diff 足够覆盖。

新增/删除/替换：

- `SceneTools.create_actor()` 创建 actor 并 `scene.add_actor(actor)`。
- `SceneTools.remove_actor()` 调 `scene.remove_actor(actor)`。
- `SceneDatas.select_model_file()` 调 `actor.set_model(file_path)`。
- 当前这些入口没有统一 topology dirty event，也没有 overlay 意图记录。

结论：topology 阶段需要在 Python 操作入口记录 overlay op，并通知 C++ adapter。不能只靠 C++ 每帧 diff 猜新增/删除/替换语义。

## 调整后的开工任务

1. 修 scene-level actor_guid 持久化和 C++ ActorDevice guid 同步。
2. 扩展 `.scene [vision]` 的 overlay path/guid 和 `external_live` 恢复逻辑。
3. 实现 Python Vision JSON model shape 解析、proxy actor 创建/复用、overlay binding 生成。
4. 扩展 Python/C++ load request，保留旧 `external` 行为，新增 `external_live` mode。
5. 建 `ExternalVisionSceneAdapter` skeleton，完成 overlay binding -> runtime ShapeGroup/ShapeInstance refs。
6. factor Corona->Vision matrix helper，并实现 transform-only sync。
7. 验证 transform-only 闭环。
8. 再做 `Actor.set_model()`、gizmo 持久化、runtime topology add/delete/replace、material/emission first stage。
