# CoronaEngine 能力状态清单

## 1. 文档目的

本文档用于回答一个更务实的问题：截至当前代码状态，CoronaEngine 到底哪些能力已经可用，哪些只是部分接入，哪些仍是骨架或占位。

这份清单不是未来规划，而是基于当前仓库代码和文档的“现状判断”。

## 2. 总体判断

当前 CoronaEngine 已经形成一条可以运行的主链路：

- 引擎生命周期管理可用
- 系统注册和多线程系统框架可用
- 渲染输出链路可用
- UI 主线程链路可用
- Python API 与运行时对象构造链路可用
- 力学系统已有较多真实实现

但整体仍处于“部分模块成熟、部分模块预留”的阶段：

- `Optics`、`Display`、`Imgui`、`Mechanics` 是当前最实装的模块
- `Geometry`、`Kinematics`、`Acoustics` 系统层仍偏骨架
- Python API 比底层某些系统更完整，存在“API 已先行、系统仍待补”的现象

## 3. 状态分级

本文使用三种状态：

- `可用`：代码链路完整，已经有明确的运行时作用
- `部分可用`：主结构存在，但仍有明显空白、条件编译、占位接口或未实现分支
- `占位/骨架`：已建类、已建接口，但核心逻辑尚未落地

## 4. 能力总表

| 能力域 | 状态 | 简述 |
| --- | --- | --- |
| 引擎生命周期 | 可用 | `Engine::initialize/run/shutdown` 完整可读 |
| 系统注册与调度框架 | 可用 | 系统优先级、线程启动、主线程 UI 例外路径已存在 |
| 共享数据中心 `SharedDataHub` | 可用 | 已成为运行时单一事实来源 |
| 资源导入与模型加载 | 可用 | `Geometry` 已接入资源导入与网格/纹理构建 |
| 光学渲染链路 | 可用 | `OpticsSystem` 具有完整渲染路径 |
| 显示合成链路 | 可用 | `DisplaySystem` 可合成 optics + UI 帧并输出 |
| UI 主线程链路 | 可用 | `ImguiSystem + VulkanBackend + CEF/SDL/ImGui` 已接通 |
| Python API 对象模型 | 可用 | Scene/Actor/Geometry/Camera 等对象可构造运行时世界 |
| Python 脚本运行时 | 部分可用 | 可启动、可回调、可热更尝试，但仍在重构期 |
| 截图链路 | 可用 | `Camera -> ScreenshotRequestEvent -> OpticsSystem` 已接通 |
| 物理/碰撞 | 部分可用偏可用 | `MechanicsSystem` 实装较多，但仍需结合业务验证 |
| 几何系统线程逻辑 | 占位/骨架 | 系统类已存在，`update()` 为空 |
| 动画/运动学系统线程逻辑 | 占位/骨架 | 系统类已存在，API 多为未实现 |
| 声学系统线程逻辑 | 占位/骨架 | 系统类已存在，核心处理尚未落地 |
| ImageEffects | 占位/骨架 | API 已有，但未接入共享存储和渲染链路 |
| 相机扩展能力 | 部分可用 | 基础相机可用，视口矩形和拾取仍未实现 |
| 多 viewport UI 渲染 | 部分可用 | 基础结构完整，但仍有一些 TODO 与细节待稳固 |
| Vision 后端 | 关闭/实验性 | 代码存在，但默认 `#undef CORONA_ENABLE_VISION` |

## 5. 已可依赖的核心能力

### 5.1 引擎启动与关闭

状态：`可用`

现状：

- `Engine` 的初始化、主循环和关闭流程完整
- 系统会被注册、初始化、启动、停止、关闭
- 主线程会持续驱动 `ImguiSystem`

适合做什么：

- 作为整个运行时与示例程序的稳定入口
- 作为继续扩展系统注册、资源初始化的基础

### 5.2 运行时对象建模

状态：`可用`

现状：

- `Scene`
- `Environment`
- `Geometry`
- `Optics`
- `Mechanics`
- `Acoustics`
- `Actor`
- `Camera`

这些对象都能通过 Python API 或绑定层进入 `SharedDataHub`。

适合做什么：

- 快速构造场景
- 进行脚本驱动原型开发
- 作为 editor / tool 层的上层接口

### 5.3 渲染与显示

状态：`可用`

现状：

- `OpticsSystem` 会从场景对象构建 GPU 数据
- 生成图像后写入 `ImageStorage`
- `DisplaySystem` 会接收 optics 层与 UI 层帧事件
- 最终完成合成和显示输出

适合做什么：

- 继续扩展材质、调试视图、截图功能
- 做渲染质量和性能方面的开发

### 5.4 UI 与前端桥接

状态：`可用`

现状：

- `ImguiSystem` 已能初始化 CEF、SDL、ImGui
- `VulkanBackend` 已能生成 UI 图像并发给显示系统
- Python 启动完成后可通知 UI 显示窗口

适合做什么：

- 扩展编辑器面板
- 做脚本与前端联动
- 做日志、控制台、浏览器标签页等工具能力

### 5.5 截图能力

状态：`可用`

现状：

- `Camera::save_screenshot()` 和 `save_screenshot_sync()` 都已接通事件链路
- `OpticsSystem` 会消费截图请求并在渲染流程中处理

适合做什么：

- 渲染验证
- 自动化截图
- 离线导出流程

## 6. 部分可用但需要谨慎依赖的能力

### 6.1 脚本运行时

状态：`部分可用`

现状：

- `ScriptSystem` 已经能驱动 `PythonAPI`
- 可以缓存 Python 回调并响应 UI 事件
- 存在热重载逻辑和脚本启动完成事件

限制：

- 仓库内有单独的脚本系统重构 TODO，说明当前架构并非最终形态
- `ScriptSystem` 头文件注释和实现明显不同步，说明这部分仍在演进
- 启用脚本执行依赖 `CORONA_ENABLE_PYTHON_API`

建议：

- 可以用来做开发期能力，但不应假设架构已经稳定

### 6.2 物理与碰撞

状态：`部分可用偏可用`

现状：

- `MechanicsSystem` 已实现大量刚体、碰撞、几何辅助逻辑
- `Mechanics` API 已能写质量、弹性、阻尼、回调等参数

限制：

- 需要结合实际场景验证稳定性和精度
- 某些能力更像“已有复杂实现，但仍需工程化打磨”

建议：

- 可以继续在其上开发，但应配套样例和测试验证

### 6.3 相机扩展功能

状态：`部分可用`

现状：

- 相机基础参数可用
- surface 绑定可用
- 输出模式可用
- 截图可用

未完成部分：

- `Camera::set_viewport_rect()` 明确 `Not implemented yet`
- `Camera::pick_actor_at_pixel()` 明确 `Not implemented yet`
- `set_size()` 当前只更新包装对象本地状态，没有完整进入共享存储

建议：

- 当前可把 Camera 视为“基础渲染视角 + surface + screenshot”接口，而不是完整 viewport 系统

### 6.4 多 viewport UI 渲染

状态：`部分可用`

现状：

- `VulkanBackend` 已有 per-viewport 资源结构和回调机制
- 支持主 viewport 与次级 viewport 渲染资源

限制：

- UI 代码中仍有 TODO，说明 renderer 路径和纹理能力还有边界情况待处理

建议：

- 可以继续沿这个方向扩展，但不应把它看成完全稳定的编辑器窗口系统

## 7. 明确处于占位或骨架阶段的能力

### 7.1 GeometrySystem

状态：`占位/骨架`

证据：

- `initialize()` 只有日志输出
- `update()` 为空
- `shutdown()` 只有日志输出

解释：

- 几何数据本身已经存在于 `SharedDataHub`
- 但“几何系统线程逻辑”还没有真正落地

### 7.2 KinematicsSystem 与 Kinematics API

状态：`占位/骨架`

证据：

- `KinematicsSystem::update()` 为空
- `Kinematics::set_animation()` / `play_animation()` / `stop_animation()` / `get_animation_index()` / `get_current_time()` 都会输出 `Not implemented yet`

解释：

- 动画对象壳已经在 API 层出现
- 但系统层与行为层几乎还未实现

### 7.3 AcousticsSystem

状态：`占位/骨架`

证据：

- `initialize()` 和 `shutdown()` 只有日志
- `update()` 为空

解释：

- 声学参数对象已有最基本存储
- 但系统执行逻辑还没真正建立

### 7.4 ImageEffects

状态：`占位/骨架`

证据：

- `ImageEffects` 只有本地 handle 占位
- `Camera::set_image_effects()` 只是保存裸指针
- 注释里明确写了“如果有 image_effects_storage，在此写入”

解释：

- 这是已经规划好的 API 入口，但还不是引擎运行时能力

## 8. 当前实现中的明显空白点

下面这些点不是推测，而是代码里能直接确认的现状：

1. `Kinematics` 的动画相关接口尚未实现
2. `ImageEffects` 未接入共享存储
3. `Camera::set_viewport_rect()` 未实现
4. `Camera::pick_actor_at_pixel()` 未实现
5. `GeometrySystem` / `KinematicsSystem` / `AcousticsSystem` 的系统线程逻辑仍为空
6. `Vision` 后端代码默认关闭
7. `ScriptSystem` 某些注释仍然过时，和真实职责不一致

## 9. 如果现在要做开发，建议怎么选模块

### 适合直接基于现有代码继续开发的方向

- 渲染链路增强
- 显示合成和调试视图
- UI 编辑器能力
- Python 驱动的场景构造
- 物理与碰撞相关增强

### 适合先补基础设施再开发的方向

- 动画系统
- 真实音频系统
- ImageEffects 真正落地
- 相机视口矩形与拾取功能
- 脚本系统架构整理和注释修正

## 10. 一句话结论

CoronaEngine 当前最强的是“引擎框架 + 渲染显示 + UI + Python API + 物理主链路”，而动画、声学、图像后处理和部分相机扩展能力仍明显处于建设中。