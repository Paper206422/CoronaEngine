# CoronaEngine 系统职责总览

## 1. 文档目的

本文档从当前代码实现出发，整理 CoronaEngine 各个核心 System 的职责、优先级、线程模型、源码入口和当前成熟度，作为阅读 `src/systems/` 的导航页。

说明：

- 以当前代码实现为准，不完全以旧架构文档或头文件注释为准。
- 部分系统头文件注释已经滞后，尤其是 `ScriptSystem`，本文档已按实现修正。
- 当前系统总体上采用“`Engine` 统一注册，`SystemManager` 按优先级初始化/启动”的组织方式。

## 2. 系统总表

| 系统 | 优先级 | 线程模型 | 目标 FPS | 主要职责 | 成熟度判断 |
| --- | ---: | --- | ---: | --- | --- |
| `DisplaySystem` | 100 | 独立线程 | 120 | 接收光学层与 UI 层帧，执行合成并输出到显示表面 | 较完整 |
| `OpticsSystem` | 90 | 独立线程 | 60 | 场景渲染、GPU 资源管理、截图请求处理 | 较完整 |
| `GeometrySystem` | 85 | 独立线程 | 60 | 几何/变换系统占位，当前逻辑很少 | 骨架阶段 |
| `KinematicsSystem` | 80 | 独立线程 | 60 | 动画/运动学系统占位，当前逻辑很少 | 骨架阶段 |
| `MechanicsSystem` | 75 | 独立线程 | 60 | 物理模拟、碰撞检测、姿态积分与场景物理数据处理 | 较完整 |
| `AcousticsSystem` | 70 | 独立线程 | 60 | 声学系统占位，当前逻辑很少 | 骨架阶段 |
| `ScriptSystem` | 60 | 独立线程 | 60 | Python 运行入口、UI 到 Python 的事件桥接 | 可用但在重构 |
| `ImguiSystem` | 40 | 主线程 | 60 | SDL/ImGui/CEF UI 生命周期与每帧 UI 刷新 | 较完整 |

## 3. 系统注册关系

系统注册发生在 `src/engine.cpp` 的 `Engine::register_systems()` 中，当前顺序是：

1. `DisplaySystem`
2. `OpticsSystem`
3. `GeometrySystem`
4. `KinematicsSystem`
5. `MechanicsSystem`
6. `AcousticsSystem`
7. `ScriptSystem`
8. `ImguiSystem`

其中：

- 大多数系统继承 `Kernel::SystemBase`，由系统管理器负责线程生命周期。
- `ImguiSystem` 直接实现 `Kernel::ISystem`，由主线程手动调用 `update()`。

## 4. 各系统说明

### 4.1 DisplaySystem

源码入口：

- 头文件：`include/corona/systems/display/display_system.h`
- 实现：`src/systems/display/display_system.cpp`

主要职责：

- 订阅 `DisplaySurfaceChangedEvent`，维护显示表面集合。
- 订阅 `OpticsFrameReadyEvent` 和 `UIFrameReadyEvent`，接收来自光学系统和 UI 系统的帧。
- 使用 GPU 计算管线将 Optics 层和 UI 层合成为最终输出。
- 将合成结果提交到 `HardwareDisplayer` 进行呈现。

实现特点：

- 使用 `frame_mutex_` 保护来自不同线程的事件写入和显示线程读取。
- 使用 1x1 透明图像作为缺失图层的回退资源，支持“只有光学层”或“只有 UI 层”的情况。
- 显示系统当前是“跨系统帧汇聚点”，本质上承担了最终呈现编排职责。

结论：

`DisplaySystem` 已经不是简单窗口管理器，而是“显示表面管理 + 两层图像合成 + 最终呈现”的系统。

### 4.2 OpticsSystem

源码入口：

- 头文件：`include/corona/systems/optics/optics_system.h`
- 实现：`src/systems/optics/optics_system.cpp`
- 硬件辅助：`src/systems/optics/hardware.h`

主要职责：

- 初始化底层硬件资源和渲染管线。
- 遍历场景、相机、Actor、Profile、Optics/Geometry 数据，构建实例表和材质表。
- 执行可见性、光照、天空盒、色调映射等渲染流程。
- 接收截图请求事件并在渲染流程中处理截图输出。
- 将渲染结果写回 `SharedDataHub` 供 `DisplaySystem` 消费。

实现特点：

- 当前实现明显依赖 `SharedDataHub` 作为跨系统共享数据中心。
- 渲染链路已经具备较完整的 GPU pipeline 初始化逻辑。
- 代码中存在条件编译的 Vision 后端接入痕迹，但默认被关闭。
- 头文件写的是 120 FPS，但实现构造函数实际设置为 60 FPS，应以实现为准。

结论：

`OpticsSystem` 是当前最核心、最实质性的系统之一，负责把场景数据组织成 GPU 可消费的数据并输出图像帧。

### 4.3 GeometrySystem

源码入口：

- 头文件：`include/corona/systems/geometry/geometry_system.h`
- 实现：`src/systems/geometry/geometry_system.cpp`

头文件目标职责：

- 几何数据管理。
- 空间变换。
- 层次结构。
- 包围盒计算。

当前实现状态：

- `initialize()` 和 `shutdown()` 只有日志输出。
- `update()` 为空。

结论：

`GeometrySystem` 目前更像架构预留位，设计目标明确，但具体能力尚未在系统循环中完整落地。

### 4.4 KinematicsSystem

源码入口：

- 头文件：`include/corona/systems/kinematics/kinematics_system.h`
- 实现：`src/systems/kinematics/kinematics_system.cpp`

头文件目标职责：

- 管理运动学状态。
- 进行动画更新。
- 在渲染前更新姿态数据。

当前实现状态：

- `initialize()` 和 `shutdown()` 只有日志输出。
- `update()` 为空。
- 对外名称仍返回 `Animation`，说明命名处于“Animation 向 Kinematics 迁移”的过渡状态。

结论：

`KinematicsSystem` 的定位已经确定，但当前系统循环内还未体现出完整动画求值逻辑。

### 4.5 MechanicsSystem

源码入口：

- 头文件：`include/corona/systems/mechanics/mechanics_system.h`
- 实现：`src/systems/mechanics/mechanics_system.cpp`

主要职责：

- 执行力学/物理更新。
- 基于几何和变换数据构建世界空间碰撞包围体。
- 处理 AABB / OBB / SAT / 三角形窄相等碰撞流程。
- 积分位置、朝向、角速度等状态。
- 与资源系统配合加载碰撞网格等数据。

实现特点：

- 这是目前代码体量最大的系统之一，包含大量数学辅助函数和碰撞检测逻辑。
- 明确依赖 `SharedDataHub`，说明它直接操作引擎共享状态，而不是只消费事件。
- 代码中包含较多条件编译开关，用于控制碰撞算法路径。

结论：

`MechanicsSystem` 已经是实质性物理系统，不是占位实现，后续如果要理解实体运动和碰撞，这是必须重点阅读的模块。

### 4.6 AcousticsSystem

源码入口：

- 头文件：`include/corona/systems/acoustics/acoustics_system.h`
- 实现：`src/systems/acoustics/acoustics_system.cpp`

头文件目标职责：

- 声音播放。
- 混音。
- 3D 声学处理。

当前实现状态：

- `initialize()` 和 `shutdown()` 只有日志输出。
- `update()` 为空。

结论：

`AcousticsSystem` 目前仍是架构槽位，尚未形成完整音频运行逻辑。

### 4.7 ScriptSystem

源码入口：

- 头文件：`include/corona/systems/script/script_system.h`
- 实现：`src/systems/script/script_system.cpp`
- Python 实现目录：`src/systems/script/python/`

当前实际职责：

- 持有 `PythonAPI` 实例。
- 在 `update()` 中驱动 Python 脚本执行入口。
- 订阅来自 UI 的 `ImguiToPythonEvent` 和 `ImguiCallPythonEvent`。
- 在收到事件时获取 GIL 并调用 Python 侧回调函数。
- 在系统关闭时主动关闭 Python 解释器。

实现特点：

- 头文件注释把它描述成“显示系统”，这是明显过时内容。
- 当前实现本质上是“UI 与 Python 的桥接层 + Python 运行入口”。
- 仓库中已有单独的脚本重构 TODO 文档，说明该系统仍在演进中。

结论：

`ScriptSystem` 已经可用，但它更像现阶段的脚本适配层，而不是最终形态的脚本架构。

### 4.8 ImguiSystem

源码入口：

- 头文件：`include/corona/systems/ui/imgui_system.h`
- 实现：`src/systems/ui/imgui_system.cpp`
- UI 子模块：`src/systems/ui/imgui/`、`src/systems/ui/cef/`、`src/systems/ui/sdl/`、`src/systems/ui/vulk/`

主要职责：

- 在主线程初始化 CEF。
- 在主线程初始化 SDL、ImGui 和 Vulkan UI 后端。
- 每帧运行 UI frame runner。
- 管理浏览器标签页生命周期。
- 在脚本启动完成后响应事件并显示窗口。

实现特点：

- 它不是典型 `SystemBase` 子类，而是一个“必须主线程运行”的特殊系统。
- `Engine::tick()` 会直接调用它的 `update()`。
- 它和 `ScriptSystem` 之间存在明显的联动关系。

结论：

`ImguiSystem` 是当前编辑器/UI 能力的核心承载点，也是主线程模式最明确的系统。

## 5. 现阶段系统成熟度判断

如果按“已经有较多实质逻辑”与“主要仍是架构占位”来划分，可以得到一个更实用的阅读顺序。

建议优先阅读：

1. `OpticsSystem`
2. `DisplaySystem`
3. `MechanicsSystem`
4. `ImguiSystem`
5. `ScriptSystem`

可以暂时只了解接口的系统：

1. `GeometrySystem`
2. `KinematicsSystem`
3. `AcousticsSystem`

## 6. 代码阅读建议

如果目的是快速理解“引擎现在真正能跑什么”，建议按下面顺序读代码：

1. `src/engine.cpp`
2. `src/systems/optics/optics_system.cpp`
3. `src/systems/display/display_system.cpp`
4. `src/systems/ui/imgui_system.cpp`
5. `src/systems/script/script_system.cpp`
6. `src/systems/mechanics/mechanics_system.cpp`

如果目的是做功能开发，建议先确认目标属于哪一类：

- 渲染/显示链路：优先看 Optics + Display。
- 编辑器/前端交互：优先看 Imgui + Script + CEF。
- 物理/碰撞：优先看 Mechanics。
- 动画、几何、声学：先评估现有系统是否已具备足够基础，否则可能需要先补系统实现。

## 7. 一句话结论

CoronaEngine 当前的系统层已经形成“渲染显示链路 + 主线程 UI + Python 脚本桥接 + 物理系统 + 若干待完善系统槽位”的整体格局，其中 `Optics`、`Display`、`Mechanics`、`Imgui` 是最值得优先阅读的实装模块。