# CoronaEngine 双脚本三层架构技术文档

## 1. 文档目的

本文档系统性地描述 CoronaEngine 的双脚本三层架构设计，涵盖：

- C++ 引擎核心层、Python 业务脚本层、JavaScript 前端脚本层的职责划分与交互机制
- 基于 SharedDataHub 的三层共享数据模型
- 嵌入式浏览器（CEF）双通道通信架构
- Vue 驱动的多实例 Dock 窗口管理系统
- Python 脚本层热重载系统
- 多线程优先级编排模型

本文档面向架构理解、技术评审和专利撰写场景。

---

## 2. 总体架构

### 2.1 三层模型

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                  │
│   Layer 3 — JavaScript 前端脚本层 (CEF 渲染进程)                   │
│   ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐             │
│   │ SceneTree│ │ /Object  │ │ /Object  │ │ AITool  │  ...        │
│   │ (路由 /) │ │ (Actor_A)│ │ (Actor_B)│ │(/AITool)│             │
│   └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬────┘             │
│        └───────────┴────────────┴────────────┘                   │
│                          │                                       │
│          ┌───────────────┴───────────────┐                       │
│          │   Dock 命令通道  │ 业务查询通道 │                       │
│          │ (CefProcessMsg)  │  (cefQuery)  │                      │
│          │   不经 Python     │   经 Python   │                     │
│          └───────────────┬───────────────┘                       │
│                          │                                       │
├──────────────────────────┼───────────────────────────────────────┤
│                          │                                       │
│   Layer 2 — Python 业务脚本层 (ScriptSystem 线程)                  │
│   ┌──────────────────────┴──────────────────────────┐            │
│   │           Corona::API (C++ OOP 封装)              │            │
│   │  Scene  Actor  Geometry  Optics  Mechanics  ...  │            │
│   │           nanobind 绑定 → Python 可调用           │            │
│   │  editor.deal_func_from_js()  ← 业务查询统一入口   │            │
│   └──────────────────────┬──────────────────────────┘            │
│                          │                                       │
│              ┌───────────┴───────────┐                           │
│              │    SharedDataHub       │                           │
│              │  (类型化 Handle 存储)   │                           │
│              └───────────┬───────────┘                           │
│                          │                                       │
├──────────────────────────┼───────────────────────────────────────┤
│                          │                                       │
│   Layer 1 — C++ 引擎核心层 (多线程子系统)                           │
│                                                                  │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│   │ Display  │ │ Optics   │ │ Scene    │ │ Mechanics │           │
│   │ prio 100 │ │ prio 90  │ │ prio 88  │ │ prio 75  │           │
│   └─────┬────┘ └─────┬────┘ └─────┬────┘ └─────┬────┘           │
│         └────────────┴────────────┴────────────┘                 │
│                                                                  │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│   │ Geometry │ │Kinematics│ │ Acoustics│ │ Script   │           │
│   │ prio 85  │ │ prio 80  │ │ prio 70  │ │ prio 60  │           │
│   └──────────┘ └──────────┘ └──────────┘ └─────┬────┘           │
│                                                │                │
│   ┌──────────┐                                 │                │
│   │ Imgui    │ (主线程, prio 40)                │                │
│   └──────────┘                                 │                │
│                                                │                │
│   ┌────────────────────────────────────────────┴──┐              │
│   │  KernelContext (SystemManager + EventBus + Logger) │          │
│   │  BrowserManager (CEF 标签页物理管理)              │          │
│   └───────────────────────────────────────────────┘              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 各层职责

| 层级 | 技术栈 | 核心职责 | 明确不负责 |
|------|--------|---------|-----------|
| **Layer 1** | C++17/20, Vulkan, SDL, ImGui | 高性能渲染、物理模拟、空间索引、共享数据中心、事件总线、系统编排、CEF 标签页物理管理、ImGui 停靠空间布局 | 不决定何时创建/关闭标签页 |
| **Layer 2** | Python 3.x, nanobind | 场景运行时对象构造、AI 工具调用、业务逻辑编排、脚本执行 | 不参与窗口管理和 UI 交互 |
| **Layer 3** | Vue.js 3, TypeScript, CEF | 编辑器 UI 渲染、用户交互处理、布局决策、标签页生命周期管理、实例寻址、页面间消息路由 | 不直接操作 SDL/ImGui/Vulkan |

---

## 3. Layer 1 — C++ 引擎核心层

### 3.1 KernelContext 服务中心

`KernelContext` 是引擎的单例服务中心，提供三项基础能力：

- **SystemManager**：管理所有子系统的生命周期（注册、优先级排序、初始化、线程启动、关闭）
- **EventBus / EventStream**：同步和异步的系统间事件通信
- **Logger**：集中式日志服务

### 3.2 多线程优先级编排

每个子系统继承 `Kernel::SystemBase`，声明优先级并重写 `initialize()`、`update()`、`shutdown()`。SystemManager 按优先级降序初始化各系统，除 ImguiSystem 绑定主线程外，每个系统在独立线程中执行 `update()` 循环。

| 系统 | 优先级 | 线程模型 | 核心功能 |
|------|--------|---------|---------|
| DisplaySystem | 100 | 独立线程 | 合成 Optics + UI 双层图像到显示表面 |
| OpticsSystem | 90 | 独立线程 | 3D 场景渲染，Vulkan 光追/计算管线 |
| SceneSystem | 88 | 独立线程 | 八叉树空间索引，视锥剔除，LRU 淘汰 |
| GeometrySystem | 85 | 独立线程 | 模型加载，网格管理 |
| KinematicsSystem | 80 | 独立线程 | 骨骼动画 |
| MechanicsSystem | 75 | 独立线程 | 物理模拟，碰撞回调 |
| AcousticsSystem | 70 | 独立线程 | 音频（骨架阶段） |
| ScriptSystem | 60 | 独立线程 | Python 脚本宿主，热重载编排 |
| ImguiSystem | 40 | 主线程 | SDL 窗口 + ImGui + CEF 浏览器 UI |

### 3.3 引擎主循环

引擎以 60 FPS 目标帧率驱动主循环 `Engine::run()`：

1. `ImguiSystem::update()` 在主线程 `tick()` 中执行（处理 SDL 事件、ImGui 渲染、CEF 消息泵）
2. 其余系统在各自线程中独立执行 `update()`
3. 系统间通过 SharedDataHub 共享状态，通过 EventBus 传递事件通知

### 3.4 运行时数据模型

数据组织为场景对象图而非经典 ECS archetype：

```
Scene
 ├── Environment (太阳方向、地面网格、重力参数)
 ├── Camera[]  (位置、FOV、绑定表面、输出模式)
 └── Actor[]
      └── Profile
           ├── Geometry     (模型句柄、位置/旋转/缩放、AABB)
           ├── Optics       (Disney Principled BRDF 参数)
           ├── Mechanics    (质量、弹性、阻尼、碰撞回调)
           ├── Kinematics   (动画索引、播放/停止/速度)
           └── Acoustics    (音量)
```

---

## 4. SharedDataHub — 三层共享数据中心

### 4.1 设计动机

传统引擎中，脚本层与 C++ 核心通过序列化/反序列化交换数据，存在性能损耗和双副本一致性问题。SharedDataHub 的设计目标是让所有层直接操作同一份运行时数据。

### 4.2 存储模型

SharedDataHub 采用单例形式，内部包含多类类型化 Storage 容器。每个 Storage 通过句柄（handle）分配和引用对象，提供 `acquire_read()` / `acquire_write()` 进行线程安全访问。

| Storage | 存储内容 | 主要生产者 | 主要消费者 |
|---------|---------|-----------|-----------|
| SceneStorage | 场景对象 | Python API | OpticsSystem, ScriptSystem |
| ActorStorage | Actor 对象 | Python API | OpticsSystem, MechanicsSystem |
| ProfileStorage | Profile 组件聚合 | Python API | OpticsSystem |
| GeometryStorage | 几何体描述 | Python API, GeometrySystem | OpticsSystem |
| OpticsStorage | BRDF 材质参数 | Python API | OpticsSystem |
| MechanicsStorage | 物理参数 | Python API | MechanicsSystem |
| KinematicsStorage | 动画参数 | Python API | KinematicsSystem |
| AcousticsStorage | 音频参数 | Python API | AcousticsSystem |
| CameraStorage | 相机参数 | Python API | OpticsSystem |
| EnvironmentStorage | 环境参数 | Python API | OpticsSystem |
| ImageStorage | 渲染帧图像 | OpticsSystem, VulkanBackend | DisplaySystem |

### 4.3 图像帧三元同步协议

图像帧的流转采用 "Storage + Event + GPU Executor" 三元同步协议，解决生产者-消费者 GPU 访问竞争：

```
生产者 (OpticsSystem / VulkanBackend):
  1. 等待 consumed_executor 完成（上一帧已被消费）
  2. 渲染新帧
  3. 将图像 + executor 写入 ImageStorage[handle]
  4. 发布 FrameReadyEvent

消费者 (DisplaySystem):
  1. 收到 FrameReadyEvent
  2. 从 ImageStorage[handle] 取出图像
  3. 等待 executor 完成（GPU 渲染完成）
  4. 合成两层图像
  5. 将 consumed_executor 写回 ImageStorage[handle]
```

### 4.4 三层访问模式

```
Layer 3 (Vue/JS) ──(cefQuery/DockCommand)──→ CEF 通道
                                                   │
Layer 2 (Python)  ──(nanobind)──→ Corona::API ──→ SharedDataHub.acquire_write()
                                                            │
Layer 1 (C++)     ──(直接调用)──→ SharedDataHub.acquire_read() ──→ 各 System
```

关键特征：Python API 不是维护独立数据副本，而是直接读写 SharedDataHub 中的存储对象。这消除了脚本-引擎间的数据序列化开销。

---

## 5. Layer 2 — Python 业务脚本层

### 5.1 Corona::API 封装层

`Corona::API` 命名空间提供一组 C++ 类（Scene, Actor, Geometry, Optics, Mechanics, Kinematics, Acoustics, Camera, Environment），每个类的方法内部直接操作 SharedDataHub 对应 Storage：

- 构造时从 Storage 分配句柄并写入初始数据
- 属性修改通过 `acquire_write()` 原地更新
- 属性读取通过 `acquire_read()` 直接返回

### 5.2 nanobind 绑定

这些 C++ 类通过 nanobind 暴露给 Python（`engine_bindings.cpp`），使 Python 脚本可以直接：

```python
scene = CoronaEngine.Scene("MainScene")
camera = CoronaEngine.Camera("MainCamera")
camera.set_surface(surface_handle)
actor = CoronaEngine.Actor("Player")
actor.add_geometry(geom)
scene.add_actor(actor)
```

所有操作直接写入 SharedDataHub，渲染系统在同一帧或下一帧即可消费。

### 5.3 与 JS 前端的交互入口

Python 层提供三个关键回调函数，在初始化时由 C++ 缓存引用：

- `main.run()` → 脚本启动入口，初始化场景
- `main.editor.deal_func_from_js(json_str)` → 处理来自 Vue 前端的业务查询
- `main.editor.show_log_on_js()` → 日志推送到前端

### 5.4 Python 热重载系统

#### 5.4.1 文件变更检测

基于轮询的检测机制，核心参数：

- 扫描间隔：100ms（最高 10Hz）
- 变更检测窗口：1000ms（`kFileRecentWindowMs`）
- 检测方式：`std::filesystem::last_write_time()` 比对
- 自动跳过：`__pycache__`、`__init__.py`、`.pyc`

编辑模式下，先自动将修改文件从编辑器源路径同步到运行时路径，再启动热重载流程。

#### 5.4.2 依赖图构建与拓扑排序

```
算法步骤：

1. 遍历被修改模块集合 packageSet

2. 快照 sys.modules，构建反向依赖图：
   dependencyGraph[被导入模块名] = {所有导入者模块名}

3. 从 packageSet 中各模块出发，BFS 收集所有受影响模块
   到 dependencyVec（拓扑序）

4. 逆序重载 dependencyVec（叶子模块优先）：
   for i = len-1 down to 0:
       importlib.reload(dependencyVec[i])
```

逆序重载确保当父模块被重载时，其导入的子模块已经是最新版本。

#### 5.4.3 根模块刷新与引用更新

依赖重载完成后，单独重载根模块 `main`，并重新获取所有缓存的 nanobind 对象引用：

```cpp
mod = importlib.import_("main");
reload(mod);

pStartFunc  = mod.run;                        // 重新绑定
pJsCallFunc = mod.editor.deal_func_from_js;   // 重新绑定
messageFunc = mod.editor.show_log_on_js;      // 重新绑定
```

这确保 C++ 侧持有的 Python 对象引用始终指向重载后的最新模块版本。

---

## 6. Layer 3 — JavaScript 前端脚本层

### 6.1 运行环境

Vue.js 3 应用运行在 Chromium Embedded Framework (CEF) 渲染进程中，通过 SDL + ImGui 将浏览器视图嵌入引擎窗口的 Dock 空间。

### 6.2 双通道通信架构

C++ 与 JS 之间设计两条性质不同的 CEF 通信通道，按消息特征选择使用：

| 特性 | 通道 A — 业务查询通道 | 通道 B — Dock 命令通道 |
|------|----------------------|------------------------|
| **底层机制** | `CefMessageRouter` (请求-响应) | `CefProcessMessage` (单向推送) |
| **JS 侧 API** | `window.cefQuery(request)` | `window.coronaBridge.dockCommand(params)` |
| **C++ 侧入口** | `BrowserSideJSHandler::OnQuery()` | `OffscreenCefClient::OnProcessMessageReceived()` |
| **Python GIL** | 需要（经 Python 处理业务逻辑） | 不需要（纯 C++ 直接执行） |
| **返回值** | Promise（原生支持回调） | `requestId + window.__dockCallback` 异步回调 |
| **延迟特征** | 较高（经 Python GIL） | 极低（绕过 Python） |
| **适用场景** | 场景操作、AI 调用、脚本执行 | 窗口创建/关闭/停靠、摄像机移动、标签页消息投递 |

#### 6.2.1 通道 A — 业务查询通道

```
[Vue]
  window.cefQuery({request: JSON.stringify({cmd, params})})
         │
[CEF Renderer]
  CefMessageRouter (Browser ↔ Renderer 双向)
         │
[CEF Browser Process]
  BrowserSideJSHandler::OnQuery(request)
         │
[Python]
  PyGILState_Ensure()
  main.editor.deal_func_from_js(json_str)
         │
[Corona::API]
  Scene/Actor/Geometry/... → SharedDataHub
         │
[返回路径]
  OnQuery 回调 → CefMessageRouter → cefQuery Promise resolve
```

#### 6.2.2 通道 B — Dock 命令通道

```
[Vue]
  window.coronaBridge.dockCommand(JSON.stringify({cmd, tabId, ...}))
         │
[CEF Renderer — V8 Handler]
  DockCommandHandler::Execute()
    → CefProcessMessage::Create("DockCommand")
    → frame->SendProcessMessage(PID_BROWSER, message)
         │
[CEF Browser Process]
  OffscreenCefClient::OnProcessMessageReceived()
    → handle_dock_command(message)
         │
[BrowserManager — 纯 C++]
  create_tab() / close_tab() / show_tab() / send_to_tab() / ...
         │
[异步返回值]
  frame->ExecuteJavaScript("window.__dockCallback(requestId, null, result)")
```

#### 6.2.3 通道 B 异步返回值机制

`CefProcessMessage` 为单向推送，不具备原生返回值。通过 `requestId + 全局回调` 模式实现异步返回值：

```
Vue 侧:
  ┌─────────────────────────────────────────────┐
  │ const pendingRequests = new Map()            │
  │                                             │
  │ function dockCommand(params) {              │
  │   if (需要返回值) {                          │
  │     params._requestId = generateId()        │
  │     pendingRequests.set(id, {resolve,       │
  │       reject, timeout: setTimeout(...)})     │
  │   }                                         │
  │   window.coronaBridge.dockCommand(          │
  │     JSON.stringify(params))                 │
  │   return pendingPromise                     │
  │ }                                           │
  │                                             │
  │ window.__dockCallback = (id, err, res) => { │
  │   const p = pendingRequests.get(id)         │
  │   clearTimeout(p.timeout)                   │
  │   err ? p.reject(err) : p.resolve(res)      │
  │ }                                           │
  └─────────────────────────────────────────────┘

C++ 侧:
  ┌─────────────────────────────────────────────┐
  │ handle_dock_command(msg):                   │
  │   auto result = create_tab(...)  // tab_id  │
  │   std::string js =                          │
  │     "window.__dockCallback('" + requestId + │
  │     "', null, {tabId:" + tab_id + "})"      │
  │   frame->ExecuteJavaScript(js, "", 0)       │
  └─────────────────────────────────────────────┘
```

超时保护设置为 5 秒，超时自动 reject 并清理 pendingRequests。

### 6.3 多实例窗口标识模型

为支持同名路由页面的多实例共存（如同时打开 Actor_A 和 Actor_B 的属性面板），设计四层标识体系：

```
BrowserTab {
    tab_id       = 5                          // 引擎全局自增，C++ 物理寻址
    path         = "/Object"                  // Vue Router 路由路径
    instance_id  = "props_Actor_A"            // 业务层逻辑标识
    context_json = '{"actorId":"Actor_A"}'    // 页面初始化业务上下文
}
```

| 标识 | 分配者 | 作用域 | 用途 |
|------|--------|--------|------|
| `tab_id` | C++ BrowserManager | 引擎全局 | 物理寻址 —— `ExecuteJavaScript` 注入哪个 frame，`remove_tab` 操作哪个标签页 |
| `path` | Vue 调用方 | 路由级别 | 按路由查找标签页列表（`get_tabs_by_path`），广播消息的匹配键 |
| `instance_id` | Vue 调用方 | 业务级别 | 区分同一路由下的不同业务实例，发送方据此找到目标 tab_id |
| `context_json` | Vue 调用方 | 实例级别 | 页面初始化参数，接收方在 `route.query.context` 中读取，确定展示哪个对象 |

#### 6.3.1 URL 身份注入

Vue Router 使用 `createWebHashHistory`，身份参数编码在 hash fragment 的 query string 中：

```
file:///.../dist/index.html#/Object?tabId=5&instanceId=props_Actor_A&context=%7B%22actorId%22%3A%22Actor_A%22%7D
                                      └──────────────────────────────────────────────────────────────────┘
                                      route.path  = '/Object'
                                      route.query = { tabId: '5', instanceId: 'props_Actor_A', context: '{"actorId":"Actor_A"}' }
```

每个页面组件在 `setup` 中从 `route.query` 读取自身身份，无需外部注入。

### 6.4 标签页间消息路由

#### 6.4.1 精确投递（点对点）

发送方持有目标 `tab_id`，C++ 将消息直接注入该 frame：

```
发送方:
  dockCommand({ cmd: 'sendToTab', tabId: 5, message: {type, payload} })

C++:
  auto* tab = get_tab(5);
  tab->browser->GetMainFrame()->ExecuteJavaScript(
    "window.__onTabMessage({type, payload})", "", 0);

目标 frame:
  window.__onTabMessage = (msg) => { /* 处理消息 */ }
```

**关键特征**：接收方不需要判断 `tabId` 匹配 —— C++ 已将 JS 注入限定到目标 frame，消除了消息过滤开销和错误投递可能。

#### 6.4.2 路由广播（一对多）

```
发送方:
  dockCommand({ cmd: 'broadcastToRoute', path: '/Object', message: {...} })

C++:
  auto tabs = get_tabs_by_path("/Object");  // [tab_5, tab_6]
  for (auto* tab : tabs) {
    tab->frame->ExecuteJavaScript("window.__onTabMessage({...})", "", 0);
  }
```

### 6.5 标签页去重策略

创建标签页时的去重决策由调用方组件负责，支持三种策略：

| 策略 | 行为 | 适用场景 |
|------|------|---------|
| `allowDuplicate` | 每次创建新标签页 | 属性面板（不同对象需同时查看） |
| `byContext` | `context` 相同时聚焦已有标签页 | 重复点击同一对象的属性按钮 |
| `singleton` | `path` 相同时聚焦已有标签页 | 项目设置、启动器等全局唯一页面 |

### 6.6 标签页关闭状态一致性

标签页关闭存在三条路径，均需保证 Vue 侧 `tabRegistry` 与 C++ 侧 `BrowserTab` 的最终一致：

```
路径 1 — Vue 主动关闭:
  dockStore.closeTab(tabId)
    → dockCommand({cmd:'closeTab', tabId})
      → BrowserManager::remove_tab(tabId)
        → ImGui dock 窗口销毁 ✓

路径 2 — 用户点击 ImGui dock X 按钮:
  ImGui 窗口关闭 → tabs_to_close 列表
    → BrowserManager::remove_tab(tabId)
      → frame->ExecuteJavaScript("window.__onTabClosed(tabId)")
        → dockStore.onTabClosedFromCpp(tabId)
          → tabRegistry.delete(tabId) ✓

路径 3 — CEF 渲染进程崩溃:
  OnRenderProcessTerminated
    → 通知主视图 frame
      → store 移除对应 tab 记录 ✓
```

### 6.7 Vue 前端热重载系统

Vue/JS 前端层的热重载采用与 Python 层类似的 **"文件变更检测 → 自动构建 → 页面重载"** 机制，无需重启引擎即可使前端修改生效。

#### 6.7.1 总体流程

```
┌──────────────────────────────────────────────────────┐
│              Vue 前端热重载流程                         │
│                                                      │
│  1. 文件扫描                                          │
│     C++ 侧周期性扫描 Vue 项目源目录                     │
│     (src/, public/ 等)                                │
│     检测 .vue / .ts / .js / .css 文件修改              │
│     ↓                                                │
│  2. 触发构建                                          │
│     检测到变更后，调用 npm run build                   │
│     等待构建进程退出，检查退出码                        │
│     ↓                                                │
│  3. 页面重载                                          │
│     构建成功后，通过 CEF API 重载目标页面               │
│     browser->Reload() 或 ExecuteJavaScript           │
│     ↓                                                │
│  4. 新版本生效                                        │
│     CEF 重新加载 dist/ 目录下的新构建产物               │
└──────────────────────────────────────────────────────┘
```

#### 6.7.2 文件变更检测

与 Python 热重载共用文件系统轮询基础设施，核心参数：

- 扫描间隔：可配置（建议 500ms~2000ms，前端构建较重不宜过频）
- 检测方式：`std::filesystem::last_write_time()` 比对
- 变更聚合：在构建进行中的新变更纳入下一次构建周期，避免并发构建冲突
- 自动跳过：`node_modules/`、`dist/`、`.git/` 目录

#### 6.7.3 增量/全量构建策略

```
检测到变更文件类型:
  ├── .vue / .ts / .js 文件 → 触发 npm run build（生产构建）
  ├── .css / .scss 文件     → 触发 npm run build（样式变更也需构建）
  └── public/ 静态资源      → 触发 npm run build（资源路径可能变化）
```

构建命令由引擎配置指定（默认 `npm run build`），C++ 侧通过 `CreateProcess` 或 `popen` 调用 npm，捕获标准输出和错误流用于日志记录。

#### 6.7.4 CEF 页面重载

构建产物输出到 `dist/` 目录后，通过 CEF Browser API 重载页面：

```
C++ 侧:
  BrowserManager::reload_all_tabs()         // 重载所有标签页
  或
  browser->GetMainFrame()->ExecuteJavaScript(
    "window.location.reload()", "", 0);     // 单页面重载
```

重载后各 Vue 页面组件在 `setup` 阶段从 `route.query` 恢复身份（`tabId`、`instanceId`、`context`），通过 `useDockStore` 重新注册到标签页管理系统，实现无状态丢失的页面重建。

#### 6.7.5 与 Python 热重载的对称设计

| 维度 | Python 热重载 | Vue 前端热重载 |
|------|-------------|---------------|
| **检测方式** | `last_write_time()` 轮询 | `last_write_time()` 轮询（共用基础设施） |
| **变更动作** | `importlib.reload()` 逆序重载 | `npm run build` 重新构建 |
| **生效方式** | 重载 Python 模块对象 | CEF `browser->Reload()` 重新加载页面 |
| **引用恢复** | 重新获取 nanobind 对象引用 | 从 `route.query` 恢复身份标识 |
| **最低间隔** | 100ms | 视构建耗时，通常 ≥ 2000ms |
| **跳过目录** | `__pycache__`、`__init__.py` | `node_modules`、`dist`、`.git` |

两种热重载共享相同的文件轮询基础设施，采用不同的生效路径适配各自运行时的特性（Python 解释器内模块替换 vs CEF 浏览器页面重载），共同构成引擎的双脚本热重载体系。

---

## 7. 事件总线与系统间通信

### 7.1 事件类型

引擎定义了 10 类事件，位于 `include/corona/events/`：

| 事件类 | 关键事件 | 用途 |
|--------|---------|------|
| EngineEvents | 生命周期通知 | 引擎状态切换 |
| DisplaySystemEvents | `DisplaySurfaceChangedEvent` | 表面创建/变更 |
| OpticsSystemEvents | `OpticsFrameReadyEvent` | 3D 帧渲染完成 |
| UIFrameReadyEvent | 帧就绪 | UI 帧渲染完成 |
| ImguiSystemEvents | `ImguiToPythonEvent`, `ImguiCallPythonEvent` | UI → Python 桥接 |
| ScriptSystemEvents | `ScriptFinishStartEvent` | Python 初始化完成 |
| GeometrySystemEvents | 几何体变更 | 模型加载/卸载通知 |
| MechanicsSystemEvents | 碰撞事件 | 物理碰撞通知 |
| SceneSystemEvents | 场景变更 | Actor 增删通知 |

### 7.2 通信模式

CoronaEngine 采用 **"共享存储 + 事件通知"** 混合模式：

- **状态共享**：结构化运行时对象存放在 SharedDataHub 的各 Storage 中，系统通过 handle 读写
- **时机通知**：事件总线仅携带轻量信号（如 "帧 X 已就绪，图像在 handle Y"），不携带大数据
- **同步协议**：GPU 资源通过 executor 句柄在生产者-消费者间协调访问顺序

---

## 8. 渲染主链路

当前最完整的一条端到端链路：

```
1. Python API 构造运行时对象
   Scene → Camera → Actor → Profile → {Geometry, Optics, Mechanics, ...}
   ↓ 写入 SharedDataHub

2. OpticsSystem 从 SharedDataHub 读取场景数据
   遍历 Scene/Camera/Actor/Profile/Optics/Geometry/ModelTransform Storage
   构建 Instance Table + Material Table + GPU Buffers
   ↓ Vulkan 渲染 → 3D 图像写入 ImageStorage
   ↓ 发布 OpticsFrameReadyEvent

3. VulkanBackend (UI) 渲染 ImGui + CEF 视图
   ↓ UI 图像写入 ImageStorage
   ↓ 发布 UIFrameReadyEvent

4. DisplaySystem 订阅两类 FrameReadyEvent
   从 ImageStorage 取出两层图像
   ↓ GPU 合成 Optics 层 + UI 层
   ↓ 提交到 Display Surface
```

---

## 9. 架构决策与权衡

### 9.1 为什么三层而不是两层

| 考量 | 两层 (C++ + Python) | 三层 (C++ + Python + JS) |
|------|---------------------|--------------------------|
| UI 开发效率 | Python 做 UI 受限 | Vue 生态丰富，组件化开发 |
| 编辑器交互 | 命令行/简单 GUI | 完整 Dock 面板系统 |
| 热路径延迟 | 所有 UI 操作经过 GIL | 实时操作绕过 Python |
| 前端人力 | 需要 Python GUI 技能 | 前端工程师可直接参与 |

### 9.2 为什么双通道而不是单通道

| 考量 | 仅 cefQuery | 仅 CefProcessMessage | 双通道 |
|------|-----------|---------------------|--------|
| Python 业务逻辑 | ✓ 天然支持 | ✗ 需要桥接层 | ✓ 业务走 cefQuery |
| 低延迟实时交互 | ✗ GIL 阻塞 | ✓ 纯 C++ 执行 | ✓ 实时走 ProcessMessage |
| 请求-响应语义 | ✓ 原生 Promise | ✗ 需自行实现 | ✓ 各取所长 |
| 复杂度 | 低 | 中 | 中（但职责清晰） |

### 9.3 为什么 SharedDataHub 而不是纯事件驱动

- 大数据（图像帧、场景对象）通过事件传递会产生拷贝开销
- 事件总线适合"通知"，不适合"状态"
- SharedDataHub 作为单一事实来源，避免了多副本一致性问题
- Python API 直接写 SharedDataHub，消除了脚本-C++ 间的序列化步骤
