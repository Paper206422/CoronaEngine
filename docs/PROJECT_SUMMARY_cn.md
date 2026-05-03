# CoronaEngine 项目总览

## 1. 项目定位

CoronaEngine 是一个模块化、多线程、数据驱动的 C++ 游戏引擎。项目当前处于持续演进阶段，根目录 `README.md` 现在已经作为简洁入口页存在，而更完整的开发说明主要集中在 `docs/` 目录。

引擎的核心目标可以概括为：

- 以系统（System）为基本功能单元，按优先级注册和初始化。
- 以 `KernelContext` 为服务中心，统一提供日志、事件总线和系统管理。
- 通过多线程系统更新机制提升并行能力。
- 通过事件总线和数据驱动方式降低系统耦合。
- 同时支持原生 C++ 扩展、示例程序和 Python 脚本接口。

## 2. 当前代码结构

项目的关键目录如下：

- `include/corona/`：公共头文件，包含引擎 API、事件定义、系统对外接口。
- `src/`：核心引擎实现，包含 `engine.cpp`、共享数据模块和各系统构建入口。
- `src/systems/`：系统模块目录，当前包含 `acoustics`、`display`、`geometry`、`kinematics`、`mechanics`、`optics`、`script`、`ui`。
- `examples/`：示例程序，当前可见示例包括 `engine` 和 `cef_subprocess`。
- `docs/`：项目中文/英文文档、设计提案和重构规划。
- `misc/cmake/`：模块化 CMake 脚本，负责选项、依赖、Python、运行时文件复制等构建细节。
- `assets/`：示例和运行时使用的模型、纹理、着色器等资源。
- `editor/`：编辑器相关代码。
- `third_party/`：第三方依赖或嵌入式运行时资源，其中包含 Python 运行时目录。

## 3. 核心架构总结

### 3.1 Engine 的职责

`Engine` 是应用的中央协调器，负责：

- 初始化 `KernelContext`。
- 注册核心系统。
- 注册资源解析器（文本、图像、场景）。
- 初始化和启动系统。
- 驱动主循环并维护帧时间。
- 协调退出与关闭流程。

从当前实现看，主循环会：

- 启动所有系统线程。
- 在循环中调用 `tick()`。
- 在主线程直接更新 `ImguiSystem`。
- 检查 UI 是否请求退出。
- 进行简单帧率控制。

需要注意的是，`engine.cpp` 中用于限帧的目标帧时长设置为 `16666` 微秒，这更接近 60 FPS；而部分历史文档仍写为 120 FPS，说明文档和实现存在轻微偏差，后续可统一。

### 3.2 KernelContext 的职责

引擎建立在 CoronaFramework 的 `KernelContext` 之上。它相当于底层服务中心，通常负责：

- `SystemManager`：系统注册、初始化、启动、停止、关闭。
- `Logger`：统一日志服务。
- `EventBus` / `EventStream`：系统之间的事件通信。

这种设计说明 CoronaEngine 更偏向“在框架上构建引擎层”，而不是从零单体实现全部基础设施。

### 3.3 系统化设计

系统是引擎功能的主要组织方式。每个系统通常：

- 继承 `Kernel::SystemBase`。
- 拥有明确优先级。
- 实现 `initialize()`、`update()`、`shutdown()` 生命周期。
- 在独立线程中运行，或在特定情况下由主线程更新。

## 4. 当前已注册系统

依据当前 `src/engine.cpp` 实现，核心系统注册顺序为：

1. `DisplaySystem`，优先级 100。
2. `OpticsSystem`，优先级 90。
3. `GeometrySystem`，优先级 85。
4. `KinematicsSystem`，优先级 80。
5. `MechanicsSystem`，优先级 75。
6. `AcousticsSystem`，优先级 70。
7. `ScriptSystem`，优先级 60。
8. `ImguiSystem`，优先级 40，由主线程更新。

这比架构文档中列出的旧顺序更完整，说明项目已经向“脚本系统 + UI 系统”方向推进。

## 5. 构建系统总结

项目使用基于 `CMakePresets.json` 的 CMake 工作流，根 CMake 文件负责：

- 载入模块化脚本。
- 声明全局构建选项。
- 拉取第三方依赖。
- 构建核心引擎静态库。
- 选择性构建示例。
- 处理运行时依赖复制和编辑器资源。

### 5.1 关键构建特征

- 最低要求 CMake 4.0。
- 推荐使用 Ninja。
- 支持 MSVC、Clang、GCC 等工具链。
- 核心库目标为静态库 `CoronaEngine`，并提供别名 `corona::engine`。
- 示例程序统一链接引擎库，并复制所需运行时依赖和资源。

### 5.2 常用预设

文档中列出的常用预设包括：

- 配置预设：`ninja-msvc`、`ninja-clang`、`vs2022`、`ninja-linux-gcc`、`ninja-linux-clang`、`ninja-macos`。
- 构建预设：`msvc-debug`、`msvc-release` 等。

Windows + MSVC 的典型流程是：

1. `cmake --preset ninja-msvc`
2. `cmake --build --preset msvc-debug`

### 5.3 主要 CMake 模块职责

- `corona_options.cmake`：定义总开关。
- `corona_python.cmake`：Python 运行时与依赖检测。
- `corona_third_party.cmake`：第三方依赖管理。
- `corona_compile_config.cmake`：编译器与标准设置。
- `corona_add_system.cmake`：系统模块注册辅助。
- `corona_runtime_deps.cmake`：运行时依赖复制。
- `corona_editor.cmake`：编辑器相关资源处理。
- `corona_cef.cmake`：CEF 相关构建集成。

## 6. 资源与运行时能力

引擎当前显式注册了以下资源解析器：

- 文本资源。
- 图像资源。
- 场景资源。

项目内置大量模型和着色器资源，表明当前仓库不仅是纯框架仓库，也承载了运行时演示素材和渲染实验内容。

## 7. Python 与脚本系统现状

从当前文档和代码可以看出，Python 能力是项目的重要扩展方向。

### 7.1 已有状态

- 项目已经存在 `ScriptSystem` 并在引擎中注册。
- 仓库中包含 Python API 使用文档，说明脚本接口已经形成面向对象风格。
- 构建系统中有 Python 依赖检查与自动安装相关选项。

### 7.2 Python API 风格

当前 Python API 文档显示，脚本层主要围绕以下对象建模：

- `Geometry`
- `Mechanics`
- `Optics`
- `Kinematics`
- `Acoustics`
- `Actor`
- `ActorProfile`
- `Camera`
- `ImageEffects`
- `Environment`
- `Scene`

接口设计强调：

- 面向对象封装。
- 不暴露底层句柄。
- 组件与 Geometry 一致性校验。
- 场景、角色、相机等运行时对象通过对象组合使用。

### 7.3 脚本系统演进方向

`SCRIPT_REFACTORING_TODO_cn.md` 表明脚本系统仍在重构过程中，规划方向包括：

- 将 Python 功能彻底系统化，纳入独立 `ScriptSystem`。
- 引入脚本运行时抽象层，而非 Python 专用耦合实现。
- 用事件系统替代直接桥接。
- 去除硬编码路径，转向配置驱动。
- 改善错误处理、热重载和服务提供者模型。

因此可以判断：脚本能力已经进入正式架构，但整体仍未完全稳定定型。

## 8. 日志系统设计进展

`LOG_CALLBACK_DESIGN_cn.md` 反映出项目正在推进“日志实时回传前端”的能力。该设计提案的重点是：

- 当前日志系统基于 Quill，已经支持控制台与文件输出。
- 前端编辑器需要实时显示日志。
- 直接从 Quill 后端线程调用 Python 回调存在 GIL 死锁风险。
- 推荐方案是引入 `CallbackSink + 线程安全队列 + Python 主动拉取`。

这说明项目不仅关注运行时能力，也在逐步建设编辑器联动和可视化调试基础设施。

## 9. 代码规范总结

项目使用 `.clang-format` 和 `.clang-tidy` 约束代码风格，主要规则包括：

- 基于 Google C++ 风格。
- 使用 4 空格缩进。
- 禁止使用制表符缩进。
- 类型名使用 `CamelCase`。
- 函数和变量使用 `snake_case`。
- 私有成员使用 `snake_case_`。
- 常量和枚举成员使用 `kCamelCase`。

仓库提供 `code-format.ps1` 用于统一格式化。

## 10. 现有文档的使用建议

如果后续要继续开发，建议按下面顺序阅读：

1. `docs/ONE_PAGE_OVERVIEW_cn.md`：先用单页快速理解项目定位、主链路和当前成熟度。
2. `docs/QUICK_START_cn.md`：用最短时间建立对项目主链路的认识。
3. `docs/ARCHITECTURE_MAP_cn.md`：用图快速理解系统关系、主链路和数据模型。
4. `docs/DEVELOPER_GUIDE_cn.md`：了解入门流程与常规开发任务。
5. `docs/ARCHITECTURE_cn.md`：理解高层架构和系统设计。
6. `docs/SYSTEMS_OVERVIEW_cn.md`：按当前代码实现理解各系统职责和成熟度。
7. `docs/DATA_FLOW_OVERVIEW_cn.md`：理解 `SharedDataHub`、渲染帧、UI 和脚本之间的数据流。
8. `docs/SOURCE_INDEX_cn.md`：按入口文件、关键类、关键函数和关键事件快速定位源码。
9. `docs/PYTHON_API_STORAGE_MAPPING_cn.md`：理解 Python API 如何映射到 `SharedDataHub` 与各组件 storage。
10. `docs/CAPABILITY_STATUS_cn.md`：快速判断哪些能力已经可用、哪些仍是部分可用或占位实现。
11. `docs/ISSUES_AND_RECOMMENDATIONS_cn.md`：了解当前已确认的问题、偏差和建议修复顺序。
12. `docs/CMAKE_GUIDE_cn.md`：掌握配置、构建和依赖管理。
13. `docs/CODE_STYLE_cn.md`：遵循项目代码规范。
14. `docs/PYTHON_API_EXAMPLES.md`：理解脚本层对象模型。
15. `docs/LOG_CALLBACK_DESIGN_cn.md`：了解日志到前端链路的设计方向。
16. `docs/SCRIPT_REFACTORING_TODO_cn.md`：掌握脚本系统未来重构计划。

## 11. 当前项目状态判断

结合文档和代码，可以对项目现状做出以下判断：

- 项目核心架构已经成型，具备明确的系统化设计。
- 构建体系较完整，跨平台和依赖管理思路明确。
- 文档覆盖面不错，包含架构、构建、规范、脚本和专题设计。
- README 仍未承担入口文档职责，导致首次进入仓库时信息不足。
- 个别文档内容与实现存在时间差，例如系统列表和主循环帧率描述。
- Python / Script / Editor 相关能力仍在持续迭代，是当前比较活跃的演进方向。

## 12. 一句话结论

CoronaEngine 当前是一个以 `KernelContext + 多系统 + 事件总线 + 模块化 CMake` 为核心的 C++ 引擎工程，已经具备渲染、几何、运动学、力学、声学、脚本和 UI 等系统基础，同时正向 Python 脚本化和编辑器联动方向持续扩展。