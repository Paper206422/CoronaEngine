# CoronaEngine 5 分钟上手

## 1. 这是什么

CoronaEngine 是一个模块化、多线程、数据驱动的 C++ 游戏引擎，核心结构是：

- `Engine` 负责生命周期和系统注册
- `KernelContext` 提供日志、事件总线和系统管理
- 各个 `System` 负责渲染、显示、物理、脚本、UI 等模块
- `SharedDataHub` 存放当前运行时世界状态

如果你第一次进入这个仓库，不需要先读完整个 `docs/` 目录。先抓住主链路即可。

## 2. 先看什么

只想快速建立全局认知，按这个顺序读：

1. `README.md`
2. `docs/PROJECT_SUMMARY_cn.md`
3. `docs/SYSTEMS_OVERVIEW_cn.md`
4. `docs/DATA_FLOW_OVERVIEW_cn.md`
5. `docs/SOURCE_INDEX_cn.md`

如果你只想看代码，不想先读长文档，就按这个顺序：

1. `src/engine.cpp`
2. `include/corona/shared_data_hub.h`
3. `src/systems/optics/optics_system.cpp`
4. `src/systems/display/display_system.cpp`
5. `src/systems/ui/imgui_system.cpp`
6. `src/systems/ui/vulk/vulkan_backend.cpp`
7. `src/systems/script/script_system.cpp`
8. `src/systems/script/python/corona_engine_api.cpp`

## 3. 当前最重要的几个结论

现在这个项目最值得先记住的，不是所有细节，而是下面几条。

### 3.1 当前真正跑起来的主链路

当前最完整的链路是：

- Python / API 构造场景对象
- 数据写入 `SharedDataHub`
- `OpticsSystem` 读取场景并输出渲染图像
- `VulkanBackend` 输出 UI 图像
- `DisplaySystem` 合成 optics + UI 并显示到 surface
- `ImguiSystem` 在主线程驱动 UI

### 3.2 当前最实装的模块

优先级最高、最值得读的模块是：

- `OpticsSystem`
- `DisplaySystem`
- `MechanicsSystem`
- `ImguiSystem`
- `ScriptSystem`

### 3.3 当前仍然偏骨架的模块

这些模块名字已经在，但系统逻辑还不完整：

- `GeometrySystem`
- `KinematicsSystem`
- `AcousticsSystem`
- `ImageEffects`

### 3.4 Python API 的真实定位

当前 Python API 不是独立世界模型，而是 `SharedDataHub` 的 OOP 包装层。

换句话说：

- Python 不是在操作一套“脚本层副本”
- Python 直接在构造和修改引擎运行时对象

## 4. 如果你要开始开发

先判断你要改的东西属于哪条链路。

### 4.1 渲染 / 显示

先看：

- `src/systems/optics/optics_system.cpp`
- `src/systems/display/display_system.cpp`
- `src/systems/ui/vulk/vulkan_backend.cpp`

### 4.2 UI / 编辑器 / 前端联动

先看：

- `src/systems/ui/imgui_system.cpp`
- `src/systems/ui/vulk/vulkan_backend.cpp`
- `src/systems/script/script_system.cpp`
- `src/systems/script/python/python_api.cpp`

### 4.3 物理 / 碰撞

先看：

- `src/systems/mechanics/mechanics_system.cpp`
- `include/corona/shared_data_hub.h`
- `src/systems/script/python/corona_engine_api.cpp`

### 4.4 Python 绑定 / 脚本对象

先看：

- `src/systems/script/python/engine_bindings.cpp`
- `include/corona/systems/script/corona_engine_api.h`
- `src/systems/script/python/corona_engine_api.cpp`

## 5. 现在就别误判的几个点

第一次读这个项目时，最容易踩的坑有几个。

1. 不要把所有系统都当成“已经完整实现”
2. 不要把头文件注释全部当成最新事实
3. 不要把 Python API 当成纯脚本层，它实际上会直接改引擎内部存储
4. 不要默认 `Camera` 已经具备完整 viewport 能力，当前只是一部分可用
5. 不要默认 `Kinematics` 和 `ImageEffects` 已经真正落地

## 6. 最短构建路径

Windows + MSVC + Ninja：

```powershell
cmake --preset ninja-msvc
cmake --build --preset msvc-debug
```

如果只想先看工程能否编译，这已经足够。

## 7. 遇到问题先查哪里

按问题类型查文档：

- 想看全局介绍：`docs/PROJECT_SUMMARY_cn.md`
- 想看系统职责：`docs/SYSTEMS_OVERVIEW_cn.md`
- 想看数据怎么流动：`docs/DATA_FLOW_OVERVIEW_cn.md`
- 想快速定位源码：`docs/SOURCE_INDEX_cn.md`
- 想看 Python API 怎么落到存储：`docs/PYTHON_API_STORAGE_MAPPING_cn.md`
- 想看哪些能力真的可用：`docs/CAPABILITY_STATUS_cn.md`
- 想看现在最值得修的问题：`docs/ISSUES_AND_RECOMMENDATIONS_cn.md`

## 8. 一句话结论

第一次进入 CoronaEngine 时，先把它理解成“`Engine + SharedDataHub + Optics/Display + UI + Python API` 的主链路工程”，这样后面无论看渲染、脚本还是物理，都不会迷路。