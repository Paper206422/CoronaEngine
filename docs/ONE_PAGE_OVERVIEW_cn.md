# CoronaEngine 一页式总览

## 它是什么

CoronaEngine 是一个模块化、多线程、数据驱动的 C++ 游戏引擎，构建在 CoronaFramework 的 `KernelContext` 之上。当前项目已经具备一条可以运行的主链路，但整体仍处于持续演进阶段。

一句话概括：

这是一个以 `Engine + KernelContext + SharedDataHub + 多系统架构` 为核心、同时向 Python 脚本化和编辑器联动扩展的引擎工程。

## 它现在最核心的结构

项目目前最重要的 5 个结构点：

1. `Engine`
   负责引擎生命周期、系统注册和主循环。

2. `KernelContext`
   提供系统管理、日志和事件总线等基础服务。

3. `SharedDataHub`
   是当前运行时世界状态的共享数据中心。

4. `System`
   各功能模块分别以系统形式组织，当前主要包括渲染、显示、物理、脚本和 UI。

5. Python API
   不是独立脚本层，而是当前运行时数据模型的一层 OOP 包装。

## 它现在真正跑起来的主链路

当前最完整、最值得理解的一条链路是：

1. Python / API 构造场景、相机、Actor、Geometry、组件等对象
2. 数据写入 `SharedDataHub`
3. `OpticsSystem` 从共享数据读取场景并输出 3D 图像
4. `VulkanBackend` 输出 UI 图像
5. `DisplaySystem` 合成 optics + UI 图层并显示到 surface
6. `ImguiSystem` 在主线程驱动 UI 生命周期

这意味着项目现在的重点已经不是“有没有架构”，而是“哪些系统真的已经接上主链路”。

## 当前最实装的模块

如果只关心“现在最值得读哪些模块”，答案基本就是下面这几项：

- `OpticsSystem`
- `DisplaySystem`
- `MechanicsSystem`
- `ImguiSystem`
- `ScriptSystem`
- `VulkanBackend`

其中：

- `Optics + Display + VulkanBackend + Imgui` 组成了当前最完整的画面输出链路
- `ScriptSystem + PythonAPI + corona_engine_api` 组成了当前最重要的脚本入口
- `MechanicsSystem` 是当前最实装的计算型系统之一

## 当前明显还在建设中的部分

虽然系统名和 API 已经很丰富，但并不是所有能力都已经完整实现。

当前仍然明显偏骨架或过渡态的部分包括：

- `GeometrySystem`
- `KinematicsSystem`
- `AcousticsSystem`
- `ImageEffects`
- `Camera` 的 viewport / picking 扩展能力

这类模块当前更适合理解为：

- 架构位置已经定下来了
- 但具体系统逻辑或能力闭环还没完成

## 当前代码的真实风格

如果要用一句更工程化的话形容当前项目，可以这样说：

它不是一个“纯事件驱动”的引擎，也不是一个“纯 ECS archetype”式实现，而是一个以共享存储为核心、辅以事件通知和系统线程协作的混合架构。

换成更直白的说法：

- 世界状态主要放在 `SharedDataHub`
- 事件主要用来通知“某件事发生了”
- 系统在线程中消费共享数据并发布结果

## 现在适合拿它做什么

基于当前实现状态，这个项目现在最适合的工作方向是：

- 渲染链路继续增强
- 编辑器 / UI / 前端交互扩展
- Python 驱动的场景构造和工具化开发
- 物理与碰撞相关增强
- 文档、注释、实现之间的对齐和收敛

## 现在不该误判什么

第一次看这个项目时，最常见的误判有几个：

1. 误以为所有系统都已经完整实现
2. 误以为头文件注释一定是最新事实
3. 误以为 Python API 只是“脚本接口”，其实它会直接落到运行时共享存储
4. 误以为 Camera 已经是完整 viewport 抽象
5. 误以为动画和图像后处理已经进入主链路

## 如果只看一个入口

第一次进入仓库，建议顺序是：

1. `README.md`
2. `docs/QUICK_START_cn.md`
3. `docs/ARCHITECTURE_MAP_cn.md`
4. `docs/PROJECT_SUMMARY_cn.md`

如果只看代码，建议顺序是：

1. `src/engine.cpp`
2. `include/corona/shared_data_hub.h`
3. `src/systems/optics/optics_system.cpp`
4. `src/systems/display/display_system.cpp`
5. `src/systems/ui/imgui_system.cpp`
6. `src/systems/script/python/corona_engine_api.cpp`

## 最短构建命令

Windows + MSVC + Ninja：

```powershell
cmake --preset ninja-msvc
cmake --build --preset msvc-debug
```

## 一句话结论

CoronaEngine 当前已经具备“可跑的主链路 + 清晰的系统化架构 + 明确的扩展方向”，最有价值的工作已经开始从“补信息”转向“让文档、注释、实现和未完成能力逐步对齐”。