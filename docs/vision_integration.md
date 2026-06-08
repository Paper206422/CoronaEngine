# Vision 渲染后端接入文档

本文档总结当前 Vision 路径追踪后端与 CoronaEngine 的适配代码位置与职责，反映代码现状。

> 历史说明：早期版本通过 `FrameBuffer::view_texture()` 下载到 CPU、做 `float32 → half` 转换后再上传回 `finalOutputImage`（即旧的 `VisionOutputBridge` / `[MANUAL-READBACK]` 路径）。该路径已移除，Vision 帧现统一经 **零拷贝桥（VisionZeroCopyBridge）** 与 `vision_resolve` compute pass 输出。

---

## 适配器总览

所有 Vision 适配代码位于 `src/systems/optics/vision/`，统一在 `Corona::Systems::Vision` 命名空间下，并受 `#ifdef CORONA_ENABLE_VISION` 保护：

| 文件 | 入口 | 职责 |
|------|------|------|
| `vision_geometry_adapter.h/.cpp` | `build_vision_geometry(scene)` | Corona 场景几何 → Vision `Mesh` / `ShapeInstance` |
| `vision_material_adapter.h/.cpp` | `create_vision_material(optics, mesh_dev)` | `OpticsDevice` + `MeshDevice` → Vision `principled_bsdf` |
| `vision_camera_adapter.h/.cpp` | `sync_vision_camera(pipeline, camera)` | Corona 主相机 → Vision `Sensor`（yaw/pitch/position/fov + 分辨率） |
| `vision_light_adapter.h/.cpp` | `setup_vision_lights(scene, env)` | `EnvironmentDevice` → 单个 Infinite 天光 + point 太阳 |
| `vision_zero_copy_bridge.h/.cpp` | `VisionZeroCopyBridge` | 共享 Vision pre-tonemap 线性 buffer 给 Vulkan（CUDA↔Vulkan 外部内存） |

渲染循环与后端调度仍在 `OpticsSystem`（`src/systems/optics/optics_system.cpp`，`Corona::Systems` 命名空间）。

---

## 适配器一：几何（vision_geometry_adapter）

**职责**

清空并从 `SharedDataHub` 全量重建 Vision 场景的几何。遍历层级与 `optics_pipeline()` / `compute_vision_scene_signature()` 保持一致：

```
SceneDevice(enabled) → actor_handles → ActorDevice
  → profile_handles → ProfileDevice → optics_handle
    → OpticsDevice(visible / geometry_handle)
      → GeometryDevice → mesh_handles + transform_handle
```

对每个可见物体：
1. 读取 CPU mesh 数据——优先从资源层（`model_resource_handle` → `Resource::Scene`）读，回退从 GPU buffer（`vertexBuffer`/`vertexStorageBuffer`）拷回；两者都拿不到则计入 `skipped_no_data` 并跳过。
2. 由 `transform->compute_matrix()` 构建 object-to-world `float4x4`。
3. 创建 `vision::Mesh`（`upload_immediately()` + `register_mesh()`，按 hash 去重）。
4. 经材质适配器创建材质（失败回退 `scene.obtain_black_body()`），创建 `vision::ShapeInstance` 并加入 `ShapeGroup`。
5. 收尾 `scene.fill_instances()` / `update_geometry_instances()`；BVH 构建与设备上传留给 `Pipeline::prepare_geometry()`。

> 几何查找以 `optics->geometry_handle` 为准（非 `profile->geometry_handle`），二者可能不一致，用错会静默丢物体。
> `build_vision_geometry()` 会同时清空 `scene.clear_shapes()` 与 `geometry().data()->clear_meshes()`，避免重复重建时旧 mesh 残留导致 GPU 显存单调增长。

**关键接口与返回值**

```cpp
struct VisionBuildResult {
    int instance_count = 0;   // 成功加入的 ShapeInstance 数
    int candidate_count = 0;  // 通过可见性/链接过滤、预期贡献几何的物体数
    int skipped_no_data = 0;  // 因 mesh 数据不可用而跳过的候选数
};

VisionBuildResult build_vision_geometry(::vision::Scene& scene);
```

`candidate_count` 与 `instance_count` 用于让调用方区分“空场景”（`candidate_count==0`）与“数据尚未就绪”（有候选但 0 实例），支撑动态重建的重试逻辑。

---

## 适配器二：材质（vision_material_adapter）

**职责**

将单个 Corona 材质映射为 Vision `principled_bsdf`。首版仅纯色，不接入纹理：

- `MeshDevice::materialColor[0..2]` → `color`
- `OpticsDevice::roughness` → `roughness`
- `OpticsDevice::metallic` → `metallic`
- 其余 principled 参数走 Vision 默认值

```cpp
std::shared_ptr<::vision::Material> create_vision_material(
    const OpticsDevice& optics,
    const MeshDevice& mesh_dev);
```

> `MaterialDesc::init` 必须传入空 JSON **对象**（`DataWrap::object()`），否则 nlohmann 在 `JSON_NOEXCEPTION` 下对 null 负载触发 `abort()`/SIGABRT。

---

## 适配器三：相机（vision_camera_adapter）

**职责**

把 Corona 主相机同步到 Vision `Sensor`。Vision 的 Sensor 由 (yaw, pitch, position) 参数化，每次 `update_device_data()` 都会从这三者重建 c2w，因此必须驱动 Vision 自己的模型，而非手搓基矩阵：

- 由 Corona 归一化 `forward` 反解：`pitch = asin(fy)`、`yaw = atan2(fx, -fz)`（roll / 任意 world_up 无法表达，按 +Y 上方向忽略）。
- 调 `set_yaw/set_pitch/set_position/set_fov_y` + `update_device_data()`。
- 分辨率变化时 `change_resolution()` 并 **重建 `prepare_view_texture()`**（否则 tone-mapping 写入旧的小 view texture 会越界）。
- 仅当相机实际变化时才 `invalidate()`，让路径追踪在相机静止时持续累积收敛。

```cpp
void sync_vision_camera(::vision::Pipeline& pipeline, const CameraDevice& camera);
```

---

## 适配器四：光源（vision_light_adapter）

**职责**

由 `EnvironmentDevice` 重建 Vision 灯光。Vision 的环境光模型有强约束，踩坑较多：

- `DirectionalLight` 与 `SphericalMap` 都派生自 `Environment` 且带 `LightType::Infinite`，而场景**只能有一个** `env_light_`。注册两个 Infinite 光会让第二个覆盖 `env_light_`、第一个变孤儿，破坏 light sampler 的 env 索引/PMF 并使 CUDA device 崩溃。

因此本适配器：
1. 注册**单个** Infinite spherical 天光（常量白 × `sky_intensity`，并保证 ≥1 的环境光下限，避免全黑）。
2. 追加一个 **非 Infinite** 的 point 光近似定向“太阳”（沿 `sun_position` 方向放远处，按距离平方补偿强度）。
3. 重建时**只移除我们自己注入的非 Area 灯光**——绝不触碰几何产生的 Area 灯光（它们被 `ShapeInstance` 反向引用，误删会导致悬垂指针与 GPU use-after-free）。

```cpp
void setup_vision_lights(::vision::Scene& scene, const EnvironmentDevice& env);
```

> 每次场景（重）建调用一次，不要每帧调用。

---

## 适配器五：输出零拷贝桥（VisionZeroCopyBridge）

**职责**

把 Vision（CUDA）渲染出的 **pre-tonemap 线性 float4 颜色 buffer** 共享给 Vulkan，替代旧的 GPU→CPU→GPU 回读：

1. `ensure(pipeline, w, h)`：用 `create_exported_buffer`（`cuMemCreate + CU_MEM_HANDLE_TYPE_WIN32`）分配 OS 可导出 buffer，`export_handle()` 取 Win32 handle，再 import 成 Vulkan `HardwareBuffer`。分辨率不变时为 no-op。
2. `copy_from_framebuffer(pipeline)`：在 Vision stream 上把 `accumulation_buffer_`（或未累积时 `rt_buffer_`）device-to-device 拷进可导出 buffer，随后 `synchronize() + commit()`。
3. Vulkan 侧 `vision_resolve` compute pass 读 `imported()` 的 SSBO，做 exposure + ACES（顺带 float32→half），写入 `hardware_->finalOutputImage`（RGBA16F）。

```cpp
class VisionZeroCopyBridge {
public:
    bool ensure(::vision::Pipeline& pipeline, uint32_t width, uint32_t height);
    bool copy_from_framebuffer(::vision::Pipeline& pipeline);
    HardwareBuffer& imported() noexcept;   // 作为 resolve pass 的源 SSBO
    bool valid() const noexcept;
};
```

**当前已知限制**（代码注释明确标注，属“先跑通”版本）：
- **仍有一次 CUDA 侧 device-to-device 拷贝**：Vision 的 `accumulation_buffer_`/`rt_buffer_` 不是可导出分配，最终 tonemap 后的 `view_texture_` 又是不可导出的 cuArray，因此必须先拷进单独的可导出 buffer 才能共享。
- **无跨 API timeline semaphore**：CUDA 写与 Vulkan 读的顺序靠 `synchronize()` 的 CPU 全同步保证，可能撕裂/闪烁；后续应引入 external semaphore 并让两侧 overlap。

---

## OpticsSystem Vision 方法（渲染循环 / 后端调度 / 动态同步）

| 方法 | 作用 |
|------|------|
| `init_vision_lazy()` | 首次切到 Vision 时懒初始化：创建 CUDA device（function-local static，仅创建一次）、`init_rtx()`、创建 Pipeline、`build_vision_geometry` + `setup_vision_lights` + `prepare()` + `prepare_view_texture()`，并建立动态场景签名基线 |
| `run_vision_frame(fc, fi)` | 每帧：`sync_vision_dynamic_scene()` → `sync_vision_camera()` → `upload_data()` + `display(dt)` → 零拷贝桥 `ensure`/`copy_from_framebuffer` → `vision_resolve` 写 `finalOutputImage` → 发布 `OpticsFrameReadyEvent`。只处理第一个启用场景的第一个相机 |
| `compute_vision_scene_signature()` | 对几何拓扑/transform/材质参数/per-mesh 颜色做 64-bit hash_combine，作为动态变化探测 |
| `rebuild_vision_scene()` | 全量重建：`build_vision_geometry` → `setup_vision_lights` → 增量序列 `scene.prepare → prepare_geometry → prepare_lights → upload_bindless_array → compile → invalidate`（**不可**调用完整 `prepare()`，会重分配 framebuffer 致崩溃） |
| `sync_vision_dynamic_scene()` | 签名去抖（稳定 3 帧后重建）+ 重试（数据未就绪最多重试 30 帧后兜底接受），覆盖导入/导出/参数调整等动态操作 |

---

## 后端切换机制

`RenderBackend`：`Native=0`（Vulkan 光栅）/ `Vision=1`（CUDA 路径追踪）。

- 编译启用 `CORONA_ENABLE_VISION` 时，`pending_backend_` 默认 `Vision`，`current_backend_` 仍为 `Native`，首帧 `update()` 检测到不一致即触发 `init_vision_lazy()`；初始化失败回退 `Native`。
- 运行时可由 `RenderBackendSwitchEvent`（脚本 API 发布）改 `pending_backend_` atomic。
- **切回 Native 不销毁 Vision**：底层 CUDA device 是 static（只创建一次），在残留状态上重建会冲突崩溃，因此切回 Native 时只“挂起” Vision（保留 pipeline 与 `vision_initialized_`），切回 Vision 直接复用。

```cpp
void OpticsSystem::update() {
    // 检测 pending_backend_ != current_backend_，执行切换 / 懒初始化 / 挂起
#ifdef CORONA_ENABLE_VISION
    if (current_backend_ == RenderBackend::Vision) {
        optics_pipeline(vc, vi);   // 直接走 Vision 帧循环，绕过 Native guard
        return;
    }
#endif
    // Native Vulkan 管线...
}
```

> 另有 `CORONA_VISION_IMPORT_DEMO` 编译开关（默认 OFF）：直接从磁盘 import 已知正确的 `.json` 场景，用于隔离验证 Vision 渲染路径本身能否出图，绕过 Corona→Vision 适配器。

---

## 数据流总览

```
CORONA_ENABLE_VISION 启用 → pending_backend_ 默认 = Vision
  ▼
OpticsSystem::update()              ← 首帧自动切换；Vision 模式直接进入帧循环
  │  init_vision_lazy()             ← 首次：创建 Vision Pipeline + 注入场景/灯光
  ▼
run_vision_frame()
  │  sync_vision_dynamic_scene()    ← 签名去抖 + 增量重建（导入/导出/改参）
  │  sync_vision_camera()           ← 同步相机 yaw/pitch/position/fov + 分辨率
  │  upload_data() + display(dt)    ← Vision 渲染并 synchronize/commit CUDA 命令
  │  accumulation_buffer_ (float4)  ← pre-tonemap 线性 HDR（CUDA device 内存）
  ▼
VisionZeroCopyBridge
  │  copy_from_framebuffer()        ← D2D 拷进可导出 buffer（CUDA），synchronize
  │  CUDA exported buffer ──Win32 handle──▶ imported HardwareBuffer (Vulkan)  ← 共享内存
  ▼
vision_resolve compute pass (Vulkan)
  │  exposure + ACES + float32→half → hardware_->finalOutputImage (RGBA16F)
  ▼
OpticsFrameReadyEvent → DisplaySystem → 屏幕显示
```

---

## 编译开关

所有 Vision 适配代码均受 `CORONA_ENABLE_VISION` 宏保护：

```cmake
target_compile_definitions(corona_engine PRIVATE CORONA_ENABLE_VISION)
```

源文件层面由 `CORONA_BUILD_VISION` 在 `src/systems/optics/CMakeLists.txt` 中按条件加入编译，并 `PRIVATE` 链接 `vision-all_libs`。未启用时上述适配代码均不参与编译，引擎退回 Native Vulkan 管线。

---

## 差分诊断实验（排查"非 DEMO 路径黑屏"）

**现象**：开启 `CORONA_VISION_IMPORT_DEMO`（从磁盘 import 已知正确的 `.json` 场景）时画面正常、相机可控；关闭它（走 `create_vision_pipeline` + `build_vision_geometry` 适配器）时画面全黑。

**核心思路**：DEMO 路径与非 DEMO 路径**共享 `run_vision_frame` 的输出链路**。DEMO 能出图且能操控相机，已一次性证明零拷贝桥 / `vision_resolve` / `display` / 上屏 / 相机 yaw-pitch 模型全部正常。故二者差异只剩 4 个变量：① pipeline 创建（import vs create）② 几何来源（json vs `build_vision_geometry`）③ 光源 ④ 相机同步。把这些逐个搬进 DEMO 这个"可工作的台子"即可二分定位。

相关开关与探针实现在 [optics_system.cpp](../src/systems/optics/optics_system.cpp) 顶部匿名命名空间（`CORONA_ENABLE_VISION` 保护下）：

| 开关 | 默认 | 作用 |
|------|------|------|
| `CORONA_VISION_EXP_PROBE` | **开** | 只读状态探针 `dump_vision_state()`，在关键生命周期点 dump 几何(host/device)/光源/相机/累积帧。开销极小，可常开 |
| `CORONA_VISION_EXP_SKIP_GEOMETRY` | 关 | Stage 1.5：非 DEMO 下跳过 `build_vision_geometry`，做"空几何天光测试" |
| `CORONA_VISION_EXP_GRAFT_GEOMETRY` | 关 | Stage 2：DEMO 下渲染 N 帧后调 `rebuild_vision_scene()` 把 demo 几何嫁接成 Corona 几何 |

### "mesh 导入成功"的判据（主机侧 vs 设备侧）

探针日志 `[VPROBE <tag>]` 分两段，二者**同时**满足才算导入成功：

- **HOST**（`build_vision_geometry` 之后即生效）：`inst > 0` 且 `mesh_reg > 0`，且适配器日志 `skipped == 0`。
- **DEV**（`prepare`/`prepare_geometry` 之后才生效）：`accel tri > 0` 且 `mesh > 0`。
- **world r**：合理（非 0、非天文数字）。退化 0 或天文数字 ⇒ transform 拷贝 bug 把几何甩飞。

探针标签：`demo.after_prepare`（DEMO 基线）/ `prod.host_built`（非DEMO，prepare 前）/ `prod.after_prepare`（非DEMO，prepare 后）/ `runtime`（每 120 帧）/ `graft.before` `graft.after`（Stage 2）。

### 实验阶梯

```
Stage 0  读现有日志        build_vision_geometry 已打 "added N ShapeInstances (C candidates, S skipped)"
                          S>0 或 N==0 → 主机侧就失败，根因在 load_cpu_mesh_*

Stage 1  对比 VPROBE       prod.after_prepare vs demo.after_prepare：
                          prod 的 DEV tri==0 而 demo tri>0 → 设备侧上传/BVH 失败
                          prod 与 demo 同量级 → mesh 导入成功，黑屏在下游 → Stage 2

Stage 1.5 空几何天光       开 CORONA_VISION_EXP_SKIP_GEOMETRY，非 DEMO 构建：
                          看见灰色天空 → 输出/光/相机均正常，问题 100% 在几何
                          仍全黑 → 问题在 env_light_/输出/相机，而非几何

Stage 2  几何嫁接          开 CORONA_VISION_EXP_GRAFT_GEOMETRY，DEMO 构建：跑 120 帧后自动嫁接
                          看见 Corona 物体并可飞行 → 几何路径无罪，根因 = create_vision_pipeline / 首次 prepare
                          变全黑 → Corona 几何本身有问题，回看 graft.after 的 HOST/DEV 数字
```

> 先验建议：**全黑（连天空都没有）**更像 `env_light_` 未赋值或输出/相机问题——因为天光是白色、强度≥1，空场景也应是灰的。故建议**从 Stage 1.5 开局**（只改一个宏，最快切开"几何问题"与"光/输出问题"）；若专门验证 mesh 导入，则 **Stage 1 探针 + Stage 2 嫁接**是直接答案。`runtime` 探针还可揭示 `frame_idx` 是否每帧归 0（`sync_vision_camera` 每帧误触发 `invalidate()` ⇒ 路径追踪永不累积）。
