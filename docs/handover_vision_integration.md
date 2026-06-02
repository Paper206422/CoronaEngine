# Vision 渲染后端接入 —— 工作交接文档

**分支**：`merge_vision`
**日期**：2026-05-25
**状态**：该文档反映的是早期接入状态；当前主文档以 `docs/planning/VISION_INTEGRATION_MINIMAL_PLAN_cn.md` 为准。

---

## 1. 初始状态

接手前，`merge_vision` 分支的状况如下：

- Vision 作为 FetchContent 依赖已引入（`misc/cmake/corona_third_party.cmake` 中有 `Vision` 声明，`CORONA_BUILD_VISION` 宏已存在）。
- `optics_system.cpp` 内有一段注释掉或硬编码的 Vision 路径追踪调用草稿，直接写死了 JSON 场景路径，**无法编译通过**。
- 三个 Vision 私有方法（`init_vision_lazy` / `run_vision_frame` / `update_vision_camera`）在头文件中有声明但**未受 `#ifdef CORONA_ENABLE_VISION` 保护**，导致关闭宏时产生 LNK2019 链接错误。
- `assimp` 预构建目标缺少 `INTERFACE_LINK_LIBRARIES`，zlib 符号（`inflate`、`crc32` 等）无法链接，**全工程构建失败**。
- 没有可执行的构建脚本；根目录散落临时日志文件，未纳入版本管理。
- CMake 版本要求写的是 4.0（过高，实际环境 CMake 3.x），构建时报警。
- `FetchContent` 每次 configure 都尝试联网拉取依赖，离线或网络不稳定时构建卡住。

---

## 2. 本次已完成的工作

### 2.1 构建修复（工程可编译、可运行）

| 问题 | 修复位置 | 说明 |
|------|----------|------|
| assimp zlib LNK2019 | `misc/cmake/corona_third_party.cmake` | 新增 `assimp_zlibstatic` imported target，并设为 assimp 的 `INTERFACE_LINK_LIBRARIES` |
| CMake 版本过高 | `CMakeLists.txt` | `cmake_minimum_required` 从 4.0 改为 3.29 |
| 离线构建卡死 | `CMakeLists.txt` | 检测 `_deps` 目录是否存在，若存在则自动启用 `FETCHCONTENT_FULLY_DISCONNECTED`，不再联网 |
| assimp 头文件缺失 | 手动操作 | 将 `assimp-src/include/assimp/*` 复制到 `assimp-build/include/assimp/`，修复 `C1083` |

### 2.2 阶段 A：后端切换骨架

- `optics_system.h`：新增 `RenderBackend` 枚举（`Native=0` / `Vision=1`）、`pending_backend_`（atomic）、`current_backend_`、`vision_initialized_` 字段，以及公开的 `set_render_backend` / `get_render_backend` 接口。
- `optics_system.cpp`：
  - `update()` 入口处优先检测 Vision 路径，绕过 Native Vulkan 初始化 Guard 条件。
  - 后端切换通过 `pending_backend_` atomic 提交，在 OpticsSystem 渲染线程内每帧前生效，外部线程仅写 atomic，不做资源操作。
  - 所有 Vision 私有方法声明和实现统一包裹在 `#ifdef CORONA_ENABLE_VISION`，关闭宏时零链接错误。

### 2.3 阶段 C：Vision 输出桥接

新增文件 `src/systems/optics/vision/vision_output_bridge.h/.cpp`：

- `VisionOutputBridge::upload_to_hardware_image()`：将 Vision `FrameBuffer` 输出的 `float4 RGBA32F` 逐通道转换为 `RGBA16F`，调用 `HardwareExecutor` 上传到 `HardwareImage`，写回 `SharedDataHub::image_storage`，并发布 `OpticsFrameReadyEvent`。
- `VisionOutputBridge::float_to_half()`：完整 IEEE 754 float32 → float16 转换，含 NaN / Inf / 次正规数处理。
- `run_vision_frame()` 中加入 `static_assert` 校验 `float4` 大小，保证 `reinterpret_cast` 安全。

### 2.4 阶段 C：相机适配（update_vision_camera）

`update_vision_camera()` 从 `CameraDevice` 构造完整的列主序相机到世界矩阵（c2w），调用 Vision `sensor.set_mat()` + `sensor.set_fov_y()` + `sensor.update_device_data()`，每帧同步相机位置与朝向。矩阵列定义：`col[0]=right, col[1]=up, col[2]=-forward, col[3]=position`，与 `ocarina::float4x4` 约定一致。

### 2.5 阶段 D：后端自动切换（无 Python 接口）

当编译宏 `CORONA_ENABLE_VISION` 启用时，引擎在首帧自动切换到 Vision 后端，无需任何 Python 调用：

- `include/corona/systems/optics/optics_system.h`：在 `#ifdef CORONA_ENABLE_VISION` 下将成员 `pending_backend_` 默认值设为 `RenderBackend::Vision`，`current_backend_` 仍为 `Native`。
- `OpticsSystem::update()` 首帧检测到 `pending_backend_ != current_backend_`，触发 `init_vision_lazy()` 完成切换；若初始化失败则回退 `Native`。

> 说明：早期版本通过 Python `set_render_backend` / `get_render_backend` 手动切换的接口已移除（含 `corona_engine_api.h/.cpp` 声明与实现、`engine_bindings.cpp` 的 nanobind 绑定，以及 `OpticsSystem` 对应公有方法）。后端现由编译宏决定。
### 2.6 构建脚本与日志管理

- 新增 `scripts/build/build_relwithdebinfo.bat`：无硬编码路径，通过 `vswhere.exe` 自动定位 VS 安装，通过 `where clion64.exe` 推导 CLion 内置 ninja 路径，日志统一输出到 `scripts/build/logs/`。
- 新增 `scripts/build/logs/.gitignore`：排除 `*.txt` 日志文件。

### 2.7 验证结果

- `ninja -C cmake-build-relwithdebinfo corona_engine` 构建成功，exit code 0。
- `corona_engine.exe` 启动后所有系统正常初始化，日志中出现 `"OpticsSystem: Vision backend ready for lazy init"`。
- Native 渲染路径行为不变，无 Vision 相关崩溃。

---

## 3. 最终目标

详见 `docs/planning/VISION_INTEGRATION_MINIMAL_PLAN_cn.md`，核心验收标准摘录如下：

**功能**
- Native 后端正常渲染（已满足）。
- Vision 后端正常渲染（部分满足：框架完备，场景数据尚未填入）。
- 运行中可在 native ↔ vision 间切换（框架完备，待阶段 B 后完整验证）。
- DisplaySystem 无代码改动仍可显示两者输出（架构设计满足）。
- 静态几何、环境光、纯色材质可正确传递到 Vision 并渲染（**待阶段 B**）。

**稳定性**
- 连续切换 50 次无崩溃。
- 运行 10 分钟无显存泄漏趋势。

**可维护性**
- `optics_system.cpp` 不再依赖外部 Vision scene JSON 作为首版主路径。
- 适配器职责边界清晰，每类数据有独立适配器文件。

---

## 4. 待完成工作

### 4.1 阶段 B：三个数据适配器（最高优先级）

这是当前最核心的剩余工作，也是让 Vision 能真正渲染出画面的关键。

#### 4.1.1 几何适配器

**目标文件**：`src/systems/optics/vision/vision_geometry_adapter.h/.cpp`

需要做的事：
1. 遍历 `SharedDataHub` 或 Scene 的 Actor Profile，收集所有启用了 Optics 组件的 Actor。
2. 对每个 Actor，从资源层读取 CPU mesh 数据（顶点位置、法线、UV、三角索引）。
   - CPU mesh 数据来源：`ResourceManager` 通过 `model_resource_handle` 获取 `ModelResource`，读取顶点/索引缓冲。
   - 若 CPU 数据不可用，跳过该物体并记录警告，不中断渲染。
3. 读取 Actor Transform（位置、旋转、缩放），转换为 Vision 可接受的 `float4x4` 实例变换。
4. 调用 Vision 接口创建 `vision::Mesh` 和 `vision::ShapeInstance`，加入 `Pipeline::scene()`。
5. 坐标系转换（如 Corona Y-up 与 Vision 坐标系有差异）统一在此适配器内部处理。

**Vision 接口参考**：`vision::Scene::add_shape()`、`vision::Mesh`、`vision::ShapeInstance`（需先盘点 Vision 公开接口是否完备）。

#### 4.1.2 光源适配器

**目标文件**：`src/systems/optics/vision/vision_light_adapter.h/.cpp`

需要做的事：
1. 从 CoronaEngine 的 Environment 数据（`SharedDataHub` 或 Scene Environment 节点）读取：
   - `sun_direction`（太阳方向向量）
   - `sun_color`（RGB）
   - `sun_intensity`（强度）
   - `sky_intensity`（环境光强度）
2. 映射到 Vision directional light 和 environment light：
   - 太阳光 → `vision::DirectionalLight`，设置方向、颜色、强度。
   - 天空光 → `vision::EnvironmentLight` 或 `vision::SkyLight`，设置强度。
3. 首版只支持以上两种灯光，其他灯光类型（点光、聚光、面光）跳过。

**Vision 接口参考**：`vision::Scene::add_light()`（需先盘点）。

#### 4.1.3 材质适配器

**目标文件**：`src/systems/optics/vision/vision_material_adapter.h/.cpp`

需要做的事：
1. 从 `OpticsDevice`（或对应的材质资源）读取：
   - `materialColor`（RGB 基础色）
   - `roughness`（粗糙度，0~1）
   - `metallic`（金属度，0~1）
2. 映射到 Vision principled BSDF：
   - `materialColor` → `baseColor`
   - `roughness` → `roughness`
   - `metallic` → `metallic`
   - 其余参数（subsurface、specular 等）使用 Vision 默认值。
3. 首版不处理纹理，只用纯色参数。
4. 每个材质创建一个 Vision Material 对象，并关联到对应的 ShapeInstance。

**Vision 接口参考**：`vision::Material`、`vision::PrincipledBSDF`（需先盘点）。

#### 4.1.4 阶段 B 准备工作

在开始写适配器代码前，建议先做一次 **Vision 公开接口盘点**，确认以下调用入口是否存在：
- 几何：`add_mesh()` / `add_instance()` 的参数格式与生命周期
- 光源：`add_light()` 的接口签名
- 材质：`create_material()` 或 principled BSDF 的参数设置方式
- 场景重建：切换时如何清空旧场景并重建（`scene.clear()` 或类似接口）

盘点位置：Vision 仓库 `include/` 目录下的公开头文件。若接口缺失，按 Vision 修改红线（`docs/planning/VISION_INTEGRATION_MINIMAL_PLAN_cn.md` 第 5.5 节），仅允许在 Vision 侧补最小公开接口，不修改内部逻辑。

### 4.2 阶段 B 完成后需补充的联调工作

1. **init_vision_lazy() 补全**：当前 `init_vision_lazy()` 只打印日志，需调用几何/光源/材质三个适配器，真正填充 Vision 场景。
2. **run_vision_frame() 补全**：当前已调用 `Pipeline::render()` 并读取 `window_buffer_`，输出桥接已实现，需确认 `window_buffer_` 的像素格式和分辨率与预期一致。
3. **相机变化触发累积帧清空**：`update_vision_camera()` 已同步相机参数，但需要在检测到相机变化时调用 Vision 的累积帧清空接口（如 `pipeline.reset_accumulation()`）。
4. **Viewport resize 处理**：当 CoronaEngine 窗口尺寸变化时，Vision 输出分辨率需跟随重建（`HardwareImage` 重建、`pipeline` 输出尺寸更新）。
5. **场景变化增量检测**（阶段 E，非首版阻塞）：首版允许全量重建，但如性能不可接受，需对 mesh/material 加缓存键，做增量更新。

### 4.3 稳定性验收（阶段 B 完成后执行）

- 连续切换 native ↔ vision 50 次，无崩溃。
- 运行 10 分钟，观察 GPU 显存占用趋势，确认无泄漏。
- 单场景静态几何 + 环境光 + 纯色材质，Vision 模式下画面正确收敛。

---

## 5. 关键约束提醒（接手必读）

1. **Vision 修改红线**：不在 Vision 内部引入 Corona 数据结构，不修改 Vision 积分器/材质模型/几何求交主路径。若需补接口，仅允许在 Vision 公开头文件中添加最小调用入口。
2. **编译宏保护**：所有 Vision 相关代码必须包裹在 `#ifdef CORONA_ENABLE_VISION`，关闭宏时工程对 Vision 无任何依赖。
3. **线程安全**：外部线程（脚本、UI）只允许写 `pending_backend_` atomic，真正的后端切换和资源重建只在 OpticsSystem 渲染线程的帧头执行。
4. **DisplaySystem 不改**：Vision 输出必须写回 `image_handle_`（`SharedDataHub::image_storage`）并发布 `OpticsFrameReadyEvent`，DisplaySystem 无感知。
5. **首版不自动 fallback**：Vision 单帧失败时，保留上一帧输出并记录日志，不自动切回 native，由用户主动触发。

---

## 6. 文件索引

| 文件 | 状态 | 说明 |
|------|------|------|
| `include/corona/systems/optics/optics_system.h` | ✅ 已改 | 后端枚举、字段、公开 API 声明 |
| `src/systems/optics/optics_system.cpp` | ✅ 已改 | 后端分支调度、相机同步、懒初始化骨架 |
| `src/systems/optics/vision/vision_output_bridge.h` | ✅ 新增 | RGBA32F→RGBA16F 转换接口声明 |
| `src/systems/optics/vision/vision_output_bridge.cpp` | ✅ 新增 | 转换与上传实现 |
| `include/corona/systems/script/corona_engine_api.h` | ✅ 已改 | Python API 声明 |
| `src/systems/script/python/corona_engine_api.cpp` | ✅ 已改 | Python API 实现 |
| `src/systems/script/python/engine_bindings.cpp` | ✅ 已改 | nanobind 模块注册 |
| `misc/cmake/corona_third_party.cmake` | ✅ 已改 | assimp zlib 链接修复 |
| `CMakeLists.txt` | ✅ 已改 | CMake 版本修复、离线 FetchContent |
| `scripts/build/build_relwithdebinfo.bat` | ✅ 新增 | 无绝对路径的构建脚本 |
| `scripts/build/logs/.gitignore` | ✅ 新增 | 排除日志文件 |
| `docs/planning/VISION_INTEGRATION_MINIMAL_PLAN_cn.md` | ✅ 已有 | 完整设计方案（接手必读） |
| `docs/vision_integration.md` | ✅ 新增 | 四适配器代码位置说明 |
| `src/systems/optics/vision/vision_geometry_adapter.h/.cpp` | ❌ 待创建 | 几何适配器 |
| `src/systems/optics/vision/vision_light_adapter.h/.cpp` | ❌ 待创建 | 光源适配器 |
| `src/systems/optics/vision/vision_material_adapter.h/.cpp` | ❌ 待创建 | 材质适配器 |
