# CoronaEngine 现状问题与改进建议

## 1. 文档目的

本文档基于当前仓库代码与前面整理出的总览文档，汇总 CoronaEngine 现阶段最值得关注的问题、偏差和可执行改进建议。

它关注的是“现在代码里已经能确认的问题”，而不是远期规划。

## 2. 总体判断

CoronaEngine 当前已经具备一条可运行的核心链路，但项目存在比较明显的“实现先行、文档和注释滞后”现象。对后续开发效率影响最大的，不一定是缺功能本身，而是以下三类问题：

- 注释和实际实现不一致
- API / 数据结构已经暴露，但底层能力尚未完全接通
- 某些实现细节可能存在逻辑缺口，需要尽快确认

## 3. 高优先级问题

### 3.1 ScriptSystem 头文件注释与真实职责严重不符

现象：

- `include/corona/systems/script/script_system.h` 仍把 `ScriptSystem` 描述成“管理窗口、输入事件和显示设备”的系统。
- 初始化、更新、关闭三个注释也都写成了“显示系统”。
- 实际实现中，`ScriptSystem` 负责的是 Python 运行入口和 UI 到 Python 的事件桥接。

影响：

- 这是最容易误导阅读者和后续维护者的地方之一。
- 新人读头文件会直接得出错误结论。

建议：

1. 立即修正文档注释，使其与实际实现一致。
2. 在注释中明确写出它当前依赖 `PythonAPI` 和 `ImguiToPythonEvent` / `ImguiCallPythonEvent`。

### 3.2 Engine 与相关文档中存在 FPS 注释不一致

现象：

- `src/engine.cpp` 中主循环限帧使用 `16666` 微秒，实际更接近 60 FPS。
- 同一段代码下注释仍写着“120 FPS”。
- 一些历史文档和系统头文件也延续了旧的 120 FPS 描述。

影响：

- 阅读者容易误判性能模型和主循环频率。
- 后续做同步、统计和调优时容易产生认知偏差。

建议：

1. 统一把主循环注释改成 60 FPS。
2. 系统头文件中的目标 FPS 注释也按实现同步修正。
3. 如果后续真的要恢复到 120 FPS，应同时修改代码和文档，而不是只改一侧。

### 3.3 OpticsSystem 头文件目标 FPS 与实现不一致

现象：

- `include/corona/systems/optics/optics_system.h` 写的是 120 FPS。
- `src/systems/optics/optics_system.cpp` 的构造函数实际调用 `set_target_fps(60)`。

影响：

- 影响对渲染系统吞吐和节奏的理解。

建议：

1. 以实现为准修正文档注释。
2. 如果设计上确实希望 Optics 跑 120 FPS，则需要重新验证显示/UI/资源同步链路能否承受。

### 3.4 Actor::add_profile() 中 ProfileStorage 的 geometry_handle 未写入

现象：

- `src/systems/script/python/corona_engine_api.cpp` 中 `Actor::add_profile()` 会写入 `optics_handle`、`acoustics_handle`、`mechanics_handle`、`kinematics_handle`。
- 但 `geometry_handle` 被明确写成了 `0`。

影响：

- 这和 `ProfileDevice` 的设计不一致。
- 依赖 `ProfileStorage.geometry_handle` 的代码未来很可能拿不到真实几何句柄。
- 这可能是一个未完成实现，也可能已经是逻辑缺陷。

建议：

1. 优先确认这是不是有意为之。
2. 如果不是设计要求，应补写 `profile.geometry->get_handle()` 对应值。
3. 同时为 profile 关联逻辑补一个最小验证用例。

## 4. 中优先级问题

### 4.1 Kinematics API 已暴露，但核心行为全部未实现

现象：

- `Kinematics` 已经暴露给 Python。
- 但 `set_animation()`、`play_animation()`、`stop_animation()`、`get_animation_index()`、`get_current_time()` 都是 `Not implemented yet`。

影响：

- 文档和 API 会给使用者一种“动画已可用”的印象。
- 实际调用时只能得到警告日志。

建议：

1. 在文档中明确标注 `Kinematics` 仍是占位接口。
2. 如果短期不实现，可以考虑在示例和 README 中弱化其可用性描述。

### 4.2 ImageEffects 已有 API，但未接入引擎数据模型

现象：

- `ImageEffects` 类已暴露。
- `Camera::set_image_effects()` 只是保存本地指针。
- 代码注释明确写着“如果有 image_effects_storage，在此写入”。

影响：

- 当前这是一个“看起来存在，实际上不进入系统链路”的接口。

建议：

1. 如果短期不会实现，应在文档里明确为占位能力。
2. 如果准备落地，应先补 `SharedDataHub` 存储设计，再接 OpticsSystem 消费逻辑。

### 4.3 Camera 扩展接口未完成

现象：

- `Camera::set_viewport_rect()` 明确未实现。
- `Camera::pick_actor_at_pixel()` 明确未实现。
- `Camera::set_size()` 当前只改本地包装对象状态，没有完整进入共享存储。

影响：

- 相机目前更像“基础渲染视角 + screenshot + surface”接口，而不是完整 viewport 抽象。

建议：

1. 在文档中明确当前 Camera 能力边界。
2. 若编辑器或工具层依赖 viewport 语义，应优先补齐尺寸、矩形、拾取链路。

### 4.4 GeometrySystem / KinematicsSystem / AcousticsSystem 名义存在，系统逻辑仍为空

现象：

- 三个系统都有类、头文件、注册和生命周期壳。
- 但 `update()` 基本为空。

影响：

- 容易让人误以为系统层已经具备对应能力。
- 实际上当前很多能力是通过 Python API 数据模型先存在，系统线程逻辑还没补上。

建议：

1. 文档上持续标注这些是骨架系统。
2. 后续开发时优先决定哪些系统需要真正落地，避免长期存在“空系统 + 富 API”的反差。

## 5. 低优先级但值得跟踪的问题

### 5.1 ScriptSystem 中的注释文字残留“显示系统”语义

现象：

- `ScriptSystem` 构造函数旁的注释写着“显示系统高刷新率以提升响应速度”。

建议：

- 这类细节一起修掉，避免继续复制错误语义。

### 5.2 Vision 后端代码存在，但默认关闭

现象：

- `src/systems/optics/optics_system.cpp` 顶部 `#undef CORONA_ENABLE_VISION`。

影响：

- 仓库中保留了实验性或平台特化代码路径，但默认并不参与当前主链路。

建议：

1. 在文档中明确它是实验性 / 可选分支。
2. 若后续不用，应考虑隔离或精简；若要继续用，应补构建说明与启用条件。

### 5.3 引擎级事件定义存在，但当前主链路更多依赖共享存储与少量事件通知

现象：

- `FrameBeginEvent`、`FrameEndEvent`、`EngineShutdownEvent` 已定义。
- 但当前最活跃的跨系统路径仍然是 `SharedDataHub + Display/UI/Screenshot/Script 事件`。

建议：

- 后续如果要统一事件架构，应明确“哪些信息走 storage，哪些信息走 event”，避免进一步混乱。

## 6. 建议的修复优先顺序

### 第一批：低成本高收益

1. 修正文档和头文件注释
2. 统一 FPS 注释和描述
3. 在 README / 中文总览中明确未实现接口范围

### 第二批：确认潜在逻辑缺陷

1. 核查 `ProfileStorage.geometry_handle = 0` 是否为 bug
2. 核查 `Camera::set_size()` 是否应该进入 `camera_storage`
3. 核查 `ImageEffects` 是否准备进入正式渲染链路

### 第三批：补系统能力

1. 先补 `Kinematics`
2. 再补 `Camera` viewport / picking
3. 再补 `Acoustics` 和 `ImageEffects`

## 7. 如果只做一件事，应该先做什么

如果只能做一件小而确定的事情，建议先做：

- 修正源码注释与实现不一致的问题

原因很简单：

- 成本低
- 风险低
- 对后续所有开发者都有直接收益
- 可以立刻减少误读和错误修改

## 8. 一句话结论

CoronaEngine 目前最需要的不是盲目扩功能，而是先把“实现、注释、文档、数据模型”对齐，再围绕已经跑通的主链路补齐真正缺失的系统能力。