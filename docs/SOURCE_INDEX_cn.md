# CoronaEngine 源码阅读索引

## 1. 文档目的

本文档为 CoronaEngine 提供一份“从哪里开始读代码”的导航索引，重点覆盖：

- 核心入口文件
- 关键类与关键函数
- 关键事件定义
- Python 绑定与运行时入口
- 推荐阅读顺序

它不是设计文档，而是一份面向源码阅读和后续修改的快速定位表。

## 2. 第一层入口

如果第一次进入这个仓库，最重要的入口文件只有四类。

### 2.1 引擎入口

- `include/corona/engine.h`
- `src/engine.cpp`

重点看这些函数：

- `Engine::initialize()`
- `Engine::run()`
- `Engine::shutdown()`
- `Engine::register_systems()`
- `Engine::tick()`

读这部分的目的：

- 弄清引擎生命周期。
- 弄清系统注册顺序。
- 确认哪些系统在独立线程里跑，哪些在主线程跑。

### 2.2 共享数据入口

- `include/corona/shared_data_hub.h`
- `src/shared_data_hub.cpp`

重点看这些结构：

- `SceneDevice`
- `ActorDevice`
- `ProfileDevice`
- `GeometryDevice`
- `OpticsDevice`
- `MechanicsDevice`
- `CameraDevice`
- `EnvironmentDevice`
- `ImageDevice`

读这部分的目的：

- 理解当前运行时世界到底存成什么样。
- 看清各系统是围绕哪些 storage 读写数据。

### 2.3 系统实现入口

优先看下面几个：

- `src/systems/optics/optics_system.cpp`
- `src/systems/display/display_system.cpp`
- `src/systems/mechanics/mechanics_system.cpp`
- `src/systems/ui/imgui_system.cpp`
- `src/systems/ui/vulk/vulkan_backend.cpp`
- `src/systems/script/script_system.cpp`

次级入口：

- `src/systems/geometry/geometry_system.cpp`
- `src/systems/kinematics/kinematics_system.cpp`
- `src/systems/acoustics/acoustics_system.cpp`

### 2.4 Python API 与绑定入口

- `include/corona/systems/script/corona_engine_api.h`
- `src/systems/script/python/corona_engine_api.cpp`
- `src/systems/script/python/engine_bindings.cpp`
- `src/systems/script/include/corona/systems/script/python_api.h`
- `src/systems/script/python/python_api.cpp`

读这部分的目的：

- 理解 Python 侧暴露了哪些对象模型。
- 确认 Python 如何写入 `SharedDataHub`。
- 看清脚本启动、热重载、UI 调 Python 的入口位置。

## 3. 关键类导航

### 3.1 Engine

位置：

- `include/corona/engine.h`
- `src/engine.cpp`

作用：

- 引擎生命周期协调器。
- 注册资源解析器和核心系统。
- 启动系统线程并驱动主循环。

### 3.2 SharedDataHub

位置：

- `include/corona/shared_data_hub.h`
- `src/shared_data_hub.cpp`

作用：

- 当前运行时数据中心。
- 提供多种 `Storage<T>` 单例访问。
- 是渲染、物理、脚本、UI 共享数据的核心枢纽。

### 3.3 DisplaySystem

位置：

- `include/corona/systems/display/display_system.h`
- `src/systems/display/display_system.cpp`

优先关注：

- `initialize()` 中订阅了哪些事件。
- `update()` 如何从 `ImageStorage` 取图。
- `compose_and_present()` 如何完成最终合成。

### 3.4 OpticsSystem

位置：

- `include/corona/systems/optics/optics_system.h`
- `src/systems/optics/optics_system.cpp`

优先关注：

- `initialize_hardware_resources()`
- `initialize_render_pipelines()`
- `update()`
- `optics_pipeline()`
- `process_pending_screenshots()`

### 3.5 MechanicsSystem

位置：

- `include/corona/systems/mechanics/mechanics_system.h`
- `src/systems/mechanics/mechanics_system.cpp`

优先关注：

- `update()` 和 `update_physics()`
- 世界空间 AABB / OBB 构造逻辑
- 碰撞检测与回调调用路径

### 3.6 ImguiSystem

位置：

- `include/corona/systems/ui/imgui_system.h`
- `src/systems/ui/imgui_system.cpp`

优先关注：

- `initialize()` 如何串起 CEF、SDL、ImGui
- `update()` 如何驱动 UI 每帧渲染
- `shutdown()` 如何关闭标签页与前端环境

### 3.7 VulkanBackend

位置：

- `include/corona/systems/ui/vulkan_backend.h`
- `src/systems/ui/vulk/vulkan_backend.cpp`

优先关注：

- `initialize()` 如何注册默认 surface 并分配 UI 图像句柄
- `render_frame()`
- `present_frame()` 如何向显示系统发布 UI 帧事件
- 多 viewport 回调如何组织独立窗口渲染资源

### 3.8 ScriptSystem

位置：

- `include/corona/systems/script/script_system.h`
- `src/systems/script/script_system.cpp`

优先关注：

- `initialize()` 中订阅的 UI -> Python 事件
- `update()` 中的脚本执行入口
- `shutdown()` 中的解释器关闭流程

### 3.9 PythonAPI

位置：

- `src/systems/script/include/corona/systems/script/python_api.h`
- `src/systems/script/python/python_api.cpp`

优先关注：

- `ensureInitialized()`
- `runPythonScript()`
- `performHotReload()`
- `shutdown()`

### 3.10 Corona::API 对象模型

位置：

- `include/corona/systems/script/corona_engine_api.h`
- `src/systems/script/python/corona_engine_api.cpp`

优先关注的对象：

- `Scene`
- `Actor`
- `Geometry`
- `Mechanics`
- `Optics`
- `Kinematics`
- `Acoustics`
- `Camera`
- `Environment`

它们的重要性在于：

- 这些类定义了 Python 侧看到的引擎对象模型。
- 它们也是写入 `SharedDataHub` 的主要适配层。

## 4. 关键函数索引

如果你是为了改功能，下面这些函数是最常见的切入点。

### 生命周期与调度

- `Engine::initialize()`
- `Engine::run()`
- `Engine::register_systems()`
- `Engine::tick()`

### 渲染与显示

- `OpticsSystem::initialize()`
- `OpticsSystem::update()`
- `OpticsSystem::optics_pipeline()`
- `DisplaySystem::initialize()`
- `DisplaySystem::update()`
- `DisplaySystem::compose_and_present()`
- `VulkanBackend::initialize()`
- `VulkanBackend::present_frame()`

### 脚本与绑定

- `ScriptSystem::initialize()`
- `ScriptSystem::update()`
- `PythonAPI::ensureInitialized()`
- `PythonAPI::runPythonScript()`
- `EngineScripts::BindAll()`

### 对象创建与 API 适配

- `Scene::Scene()`
- `Scene::add_actor()`
- `Actor::add_profile()`
- `Geometry::Geometry()`
- `Camera::set_surface()`
- `Camera::save_screenshot()`
- `Camera::save_screenshot_sync()`

## 5. 关键事件索引

当前需要优先知道的事件并不多，但每个都很关键。

### 渲染与显示相关

位置：

- `include/corona/events/display_system_events.h`
- `include/corona/events/optics_system_events.h`

重点事件：

- `DisplaySurfaceChangedEvent`
- `OpticsFrameReadyEvent`
- `UIFrameReadyEvent`
- `ScreenshotRequestEvent`

用途：

- 通知显示表面变化
- 通知新一帧 optics 图像可用
- 通知新一帧 UI 图像可用
- 提交截图请求给渲染系统处理

### 脚本与 UI 相关

位置：

- `include/corona/events/script_system_events.h`
- `include/corona/events/imgui_system_events.h`

重点事件：

- `ImguiToPythonEvent`
- `ImguiCallPythonEvent`
- `ScriptFinishStartEvent`

用途：

- UI 触发 Python 入口函数
- UI 向 Python 传递参数调用
- Python 初始化完成后通知 UI 显示窗口

### 引擎层事件

位置：

- `include/corona/events/engine_events.h`

重点事件：

- `FrameBeginEvent`
- `FrameEndEvent`
- `EngineShutdownEvent`

说明：

- 这些事件定义了引擎级生命周期信号。
- 当前代码中可见定义较明确，但并不是本仓库里最活跃的数据通路。

## 6. Python 绑定阅读法

如果你想从脚本 API 反推引擎内部实现，推荐按下面顺序读：

1. `src/systems/script/python/engine_bindings.cpp`
2. `include/corona/systems/script/corona_engine_api.h`
3. `src/systems/script/python/corona_engine_api.cpp`
4. `src/systems/script/script_system.cpp`
5. `src/systems/script/python/python_api.cpp`

这样读的好处是：

- 先知道 Python 暴露了什么
- 再知道每个 API 写到哪里
- 最后知道脚本运行时怎么启动和接收 UI 事件

## 7. 渲染链路阅读法

如果你想从“窗口里看到一帧图像”反推整条链路，推荐按下面顺序读：

1. `src/engine.cpp`
2. `src/systems/optics/optics_system.cpp`
3. `src/systems/ui/vulk/vulkan_backend.cpp`
4. `src/systems/display/display_system.cpp`
5. `include/corona/events/display_system_events.h`

这样读的目标是搞清楚：

- 谁生成 3D 渲染图像
- 谁生成 UI 图像
- 谁负责把两层图像合成并显示到 surface

## 8. 物理链路阅读法

如果你关心碰撞、刚体和回调，推荐顺序是：

1. `include/corona/shared_data_hub.h`
2. `include/corona/systems/script/corona_engine_api.h`
3. `src/systems/script/python/corona_engine_api.cpp`
4. `src/systems/mechanics/mechanics_system.cpp`
5. `src/systems/script/python/engine_bindings.cpp`

这样读可以先明确数据结构，再看 API 如何写入，再看物理系统如何消费和计算。

## 9. 当前最值得看的 10 个文件

如果时间有限，只读 10 个文件，建议就是这 10 个：

1. `src/engine.cpp`
2. `include/corona/shared_data_hub.h`
3. `src/systems/optics/optics_system.cpp`
4. `src/systems/display/display_system.cpp`
5. `src/systems/ui/imgui_system.cpp`
6. `src/systems/ui/vulk/vulkan_backend.cpp`
7. `src/systems/mechanics/mechanics_system.cpp`
8. `src/systems/script/script_system.cpp`
9. `src/systems/script/python/corona_engine_api.cpp`
10. `src/systems/script/python/engine_bindings.cpp`

## 10. 一句话结论

如果把 CoronaEngine 当作一个正在演进中的工程来读，最有效的方式不是从头遍历全部目录，而是先抓住 `Engine -> SharedDataHub -> Optics/Display -> UI/VulkanBackend -> Script/Python API` 这一条主链路。