# Vue 层接管多 Dock 窗口管理 — 设计方案

## 1. 文档目的

本文档定义将编辑器窗口管理从 Python 层迁移至 Vue 层的完整方案，包括：

- Vue 直接控制 SDL + ImGui + CEF 多 dock 窗口的架构设计
- 同名页面多实例的创建、寻址与通信机制
- 各层职责划分与接口定义
- 具体的 C++ / Vue 改造步骤

## 2. 当前架构分析

### 2.1 现有通信通道

代码库中已经存在两条 CEF 通信通道，性质不同：

| 通道 | 底层机制 | JS 侧 API | C++ 侧入口 | 是否经过 Python |
|---|---|---|---|---|
| **业务查询通道** | `CefMessageRouter` (Browser-Router-Renderer) | `window.cefQuery()` | `BrowserSideJSHandler::OnQuery()` → `main.editor.deal_func_from_js()` | **是** — 获取 GIL，调用 Python |
| **实时通道** | `CefProcessMessage` (V8 Handler) | `window.coronaBridge.cameraMove()` | `OffscreenCefClient::OnProcessMessageReceived()` → `handle_camera_move_fast()` | **否** — 纯 C++ |

实时通道的关键代码路径：

```
[Renderer] cef_subprocess/main.cpp
  SubprocessRenderHandler::OnContextCreated()
    → 注入 window.coronaBridge = { cameraMove: V8Function }
    → FastCameraMoveHandler::Execute()
        → CefProcessMessage::Create("CameraMoveFast")
        → frame->SendProcessMessage(PID_BROWSER, message)

[Browser] cef_client.cpp
  OffscreenCefClient::OnProcessMessageReceived()
    → handle_realtime_process_message(message)   // cef_realtime_bridge.cpp
        → handle_camera_move_fast(message)        // 直接写入 SharedDataHub
```

### 2.2 现有窗口管理流程

```
Vue 组件调用 appService.addDockWidget(routePath)
  → Bridge.callCEF('CoronaEditor', 'open_browser', [routePath, pos, w, h, fixed])
    → window.cefQuery({request: JSON.stringify(...)})
      → CefMessageRouter → BrowserSideJSHandler::OnQuery()
        → PyGILState_Ensure()
        → Python: editor.deal_func_from_js(json_str)
          → CoronaEditor.open_browser(route_path, ...)
            → CoronaEditor.tab_list[path] 查重  ← 以 path 为 key，不支持多实例
            → CoronaEngine.create_browser_tab(...)  ← nanobind 调用 C++
              → BrowserManager::create_tab()
```

**痛点**：

1. Python `tab_list` 以 `route_path` 为 key，同名路由只能存在一个标签页
2. 每个 UI 操作都经过 Python GIL，增加延迟
3. 窗口管理逻辑分散在 Python (`CoronaEditor`)、C++ (`BrowserManager`)、Vue (`bridge.js`) 三层

### 2.3 目标状态

```
Vue (useDockManager) → CefProcessMessage("DockCommand") → C++ (DockCommandHandler)
                                                              ↓
                                                     BrowserManager (物理操作)
                                                              ↓
                                                     SDL + ImGui (停靠渲染)

Python: 仅响应 cefQuery 业务请求（场景操作、AI 调用、脚本执行），不参与窗口管理
```

## 3. 核心设计

### 3.1 三层职责

| 层 | 职责 | 不负责 |
|---|---|---|
| **Vue** | 布局决策、标签页生命周期管理、实例寻址、页面间消息路由 | 不直接操作 SDL/ImGui/Vulkan |
| **C++** | 执行窗口命令（创建/关闭/恢复/停靠）、CEF 标签页物理管理、帧渲染、ImGui 停靠空间布局 | 不决定何时创建/关闭标签页 |
| **Python** | 角色脚本执行、AI 工具调用、场景数据操作 | 不参与窗口管理 |

### 3.2 通信通道重新划分

保留两条通道，职责重新分配：

| 通道 | JS 侧 API | C++ 侧 | Python 参与 | 用途 |
|---|---|---|---|---|
| **Dock 命令通道** | `window.coronaBridge.dockCommand()` (新增) | 新增 `handle_dock_command()` | **否** | 创建/关闭/恢复/停靠标签页、标签页间消息投递 |
| **业务查询通道** | `window.cefQuery()` (不变) | `BrowserSideJSHandler::OnQuery()` (不变) | **是** | 场景操作、AI 调用、脚本执行 |

### 3.3 实例标识模型

每个标签页拥有四层标识：

```
BrowserTab 新增字段:
  path         = "/Object"                 ← 路由路径，用于按路由查找
  instance_id  = "props_Actor_A"           ← 调用方指定的逻辑标识
  context_json = '{"actorId":"Actor_A"}'   ← 业务上下文 (JSON 字符串)
  tab_id       = 5                         ← BrowserManager 自增 (已有)
```

| 标识 | 存储位置 | 分配者 | 用途 |
|---|---|---|---|
| `tab_id` | `BrowserTab` (已有) | C++ `BrowserManager` | C++ 物理寻址，`ExecuteJavaScript` 的目标 frame |
| `path` | `BrowserTab` (新增) | Vue 调用方 | 按路由查找标签页列表 |
| `instance_id` | `BrowserTab` (新增) | Vue 调用方 | 业务层逻辑标识，发送方据此找到目标 tab_id |
| `context_json` | `BrowserTab` (新增) | Vue 调用方 | 页面初始化参数，接收方据此知道自己在展示哪个对象 |

### 3.4 URL 构造

Vue Router 使用 `createWebHashHistory`，身份参数放在 hash fragment 的 query 中：

```
file:///C:/.../dist/index.html#/Object?tabId=5&instanceId=props_Actor_A&context=%7B%22actorId%22%3A%22Actor_A%22%7D
                                          └──────────────────────────────────────────────────────────────┘
                                          window.location.hash → Vue Router 解析
                                          route.path = '/Object'
                                          route.query = { tabId: '5', instanceId: 'props_Actor_A', context: '{"actorId":"Actor_A"}' }
```

C++ 侧在 `BrowserManager::create_tab()` 中拼接 URL 时需将 `tab_id`、`instance_id`、`context_json` 作为 query 参数附加到 hash fragment 中。

## 4. 多实例通信方案

### 4.1 精确投递（点对点）— 主要模式

```
发送方组件                       C++ Browser Process               目标 tab 的 Renderer Process
  │                                  │                                    │
  │ dockCommand({                    │                                    │
  │   cmd: 'sendToTab',              │                                    │
  │   tabId: 5,                      │                                    │
  │   message: {type, payload}       │                                    │
  │ })                               │                                    │
  │──→ CefProcessMessage ──────────→│                                    │
  │                                  │ get_tab(5) → browser              │
  │                                  │ frame->ExecuteJavaScript(          │
  │                                  │   "window.__onTabMessage(...)")    │
  │                                  │──────────────────────────────────→│
  │                                  │                                    │ 执行 JS
```

发送方在创建标签页时记录返回的 `tab_id`，后续直接向该 `tab_id` 投递消息。C++ 将 JS 注入目标 frame，**接收方不需要判断"是不是发给我的"**——C++ 已经保证了消息只到达目标 frame。

### 4.2 广播 — 辅助模式

```
发送方                           C++                              所有匹配 path 的 tab
  │                                │                                    │
  │ dockCommand({                  │                                    │
  │   cmd: 'broadcastToRoute',     │                                    │
  │   path: '/Object',             │                                    │
  │   message: {type, payload}     │                                    │
  │ })                             │                                    │
  │──→ CefProcessMessage ────────→│                                    │
  │                                │ get_tabs_by_path('/Object')        │
  │                                │ for each tab:                      │
  │                                │   frame->ExecuteJavaScript(...) ──→│ (每个 tab)
```

### 4.3 完整流程示例

```
场景：场景树页面选中 Actor_A，打开属性页面，后续修改 Actor_A 名字后通知属性页刷新

1. 用户点击"属性"按钮

2. 场景树 Vue 组件调用:
   const { tabId } = await dockCommand({
       cmd: 'createTab',
       path: '/Object',
       instanceId: 'props_Actor_A',
       context: { actorId: 'Actor_A' }
   })
   // 返回 { tabId: 5 }

3. 场景树记录映射:
   openTabs.set('Actor_A', { tabId: 5, instanceId: 'props_Actor_A' })

4. 用户又选中 Actor_B，同样操作 → tabId = 6

5. 用户修改了 Actor_A 的名字，场景树需要通知属性页刷新:
   dockCommand({
       cmd: 'sendToTab',
       tabId: 5,
       message: { type: 'actorUpdated', payload: { actorId: 'Actor_A', name: '新名字' } }
   })

6. C++ 只在 tabId=5 的 frame 中执行 JS:
   window.__onTabMessage({ type: 'actorUpdated', payload: { actorId: 'Actor_A', name: '新名字' } })

7. /Object 页面 (tabId=5) 收到消息 → 刷新显示
   /Object 页面 (tabId=6) 不受影响
```

### 4.4 发送方如何知道目标 tabId

**场景 1：发送方是创建者（最常见）**

```js
// 场景树组件中
const openTabs = new Map()  // logicalKey → { tabId, instanceId }

async function openPropertyPage(actorId) {
    const existing = openTabs.get(actorId)
    if (existing) {
        await dockCommand({ cmd: 'showTab', tabId: existing.tabId })
        return
    }
    const result = await dockCommand({
        cmd: 'createTab',
        path: '/Object',
        instanceId: `props_${actorId}`,
        context: { actorId }
    })
    openTabs.set(actorId, { tabId: result.tabId, instanceId: `props_${actorId}` })
}

function notifyPropertyPage(actorId, type, payload) {
    const entry = openTabs.get(actorId)
    if (entry) {
        dockCommand({ cmd: 'sendToTab', tabId: entry.tabId, message: { type, payload } })
    }
}
```

**场景 2：发送方不是创建者（如 AITool 想通知某个属性页）**

```js
// 方式 A：查询已打开标签页，按 context 匹配
const tabs = await dockCommand({ cmd: 'listTabs', path: '/Object' })
// tabs = [{ tabId: 5, instanceId: 'props_Actor_A', context: { actorId: 'Actor_A' } }, ...]
const target = tabs.find(t => t.context.actorId === 'Actor_A')
if (target) {
    dockCommand({ cmd: 'sendToTab', tabId: target.tabId, message: {...} })
}

// 方式 B：通过全局 Pinia store 查询
const dockStore = useDockStore()
const target = dockStore.findTab('/Object', { actorId: 'Actor_A' })
```

### 4.5 接收方初始化

每个 Vue 页面在 `setup` 中从 `route.query` 读取身份并注册消息监听：

```js
// /Object 页面组件 (views/sidebar/Object.vue)
import { useRoute } from 'vue-router'
import { onMounted, onUnmounted } from 'vue'

const route = useRoute()

const myTabId    = parseInt(route.query.tabId)         // 5
const myInstance = route.query.instanceId              // 'props_Actor_A'
const myContext  = JSON.parse(route.query.context)     // { actorId: 'Actor_A' }

function handleTabMessage(msg) {
    switch (msg.type) {
        case 'actorUpdated':
            if (msg.payload.actorId === myContext.actorId) {
                refreshDisplay(msg.payload)
            }
            break
    }
}

onMounted(() => {
    window.__onTabMessage = handleTabMessage
})

onUnmounted(() => {
    window.__onTabMessage = null
})
```

**要点**：精确投递时，`handleTabMessage` 不需要判断 `tabId`——C++ 已将 JS 注入正确的 frame。内部按 `actorId` 做二次校验是防御性编程，防止同 tab 内路由切换后的残留回调。

## 5. 接口定义

### 5.1 C++ nanobind 接口变更

`cef_py_bind.cpp` 的变更：

```cpp
// 移除 — 窗口管理移至 Vue
// minimize_browser_tab(tab_id, if_close)
// restore_browser_tab(tab_id)
// set_tab_drag_regions(tab_id, regions)

// 移除 — Python 不再创建标签页
// create_browser_tab(url, path, docking_pos, dock_width, dock_height, dock_fixed)

// 保留 — AI 流式响应需要 Python 向指定 tab 推送数据
// execute_javascript(tab_id, js_code) → str
```

`execute_javascript` 保留的理由：AI 对话流式响应场景中，Python 侧 LLM 逐 token 生成回复，需要通过 `execute_javascript` 将每个 chunk 推送到 AITalkBar 所在的 tab。这种推送模式不适合用 cefQuery 的请求-响应模式。

### 5.2 C++ BrowserTab 结构变更

```cpp
// browser_manager.h — BrowserTab 新增字段
struct BrowserTab {
    // ... 现有字段保持不变 ...

    std::string path;           // 新增：路由路径，如 "/Object"
    std::string instance_id;    // 新增：业务实例标识
    std::string context_json;   // 新增：业务上下文 JSON
};
```

### 5.3 C++ BrowserManager 新增方法

```cpp
// browser_manager.h

// 按路由路径查找所有标签页
std::vector<BrowserTab*> get_tabs_by_path(const std::string& path);

// 向指定标签页发送消息 (封装 ExecuteJavaScript)
void send_to_tab(int tab_id, const std::string& js_code);

// 向指定路由的所有标签页广播消息
void broadcast_to_route(const std::string& path, const std::string& js_code);

// 列出标签页信息 (返回 JSON，供 Vue 查询)
std::string list_tabs_json(const std::string& path_filter = "");
```

### 5.4 Renderer 进程 — V8 Handler 注入

在 `cef_subprocess/main.cpp` 的 `SubprocessRenderHandler::OnContextCreated()` 中新增：

```cpp
// 新增：Dock 命令 V8 Handler
class DockCommandHandler : public CefV8Handler {
public:
    bool Execute(const CefString& name,
                 CefRefPtr<CefV8Value> object,
                 const CefV8ValueList& arguments,
                 CefRefPtr<CefV8Value>& retval,
                 CefString& exception) override
    {
        if (name != "dockCommand" || arguments.size() < 1) {
            return false;
        }

        // 将 JS 参数序列化为 JSON 字符串
        CefRefPtr<CefV8Context> context = CefV8Context::GetCurrentContext();
        if (!context) return false;

        CefRefPtr<CefV8Value> json_string = CefV8Value::CreateString("");
        if (!arguments[0]->ConvertToStringRestricted(json_string)) {
            retval = CefV8Value::CreateBool(false);
            return true;
        }

        CefRefPtr<CefProcessMessage> message =
            CefProcessMessage::Create("DockCommand");
        message->GetArgumentList()->SetString(0, json_string->GetStringValue());

        context->GetFrame()->SendProcessMessage(PID_BROWSER, message);
        retval = CefV8Value::CreateBool(true);
        return true;
    }

    IMPLEMENT_REFCOUNTING(DockCommandHandler);
};

// OnContextCreated 中注入:
void OnContextCreated(...) override {
    // ... 现有 cefQuery 和 coronaBridge.cameraMove 注入 ...

    // 新增 coronaBridge.dockCommand
    CefRefPtr<CefV8Value> bridge = ...; // 获取已有的 coronaBridge 对象
    CefRefPtr<CefV8Value> dockFn =
        CefV8Value::CreateFunction("dockCommand", new DockCommandHandler());
    bridge->SetValue("dockCommand", dockFn, V8_PROPERTY_ATTRIBUTE_NONE);
}
```

### 5.5 C++ Browser 进程 — 命令分发

在 `cef_realtime_bridge.cpp` 中新增：

```cpp
// 新增 DockCommand 处理
bool handle_dock_command(const CefRefPtr<CefProcessMessage>& message) {
    auto args = message->GetArgumentList();
    if (!args || args->GetSize() < 1) return true;

    std::string json_str = args->GetString(0).ToString();
    // 解析 JSON: { cmd, path, instanceId, tabId, context, message, ... }
    // 分发到具体操作

    // 根据 cmd 调用:
    //   "createTab"  → BrowserManager::create_tab(...)
    //   "closeTab"   → BrowserManager::remove_tab(...)
    //   "showTab"    → BrowserManager::show_tab(...)
    //   "hideTab"    → BrowserManager::hide_tab(...)
    //   "sendToTab"  → BrowserManager::send_to_tab(...)
    //   "broadcastToRoute" → BrowserManager::broadcast_to_route(...)
    //   "listTabs"   → BrowserManager::list_tabs_json(...)
    //                   → 通过 frame->ExecuteJavaScript 回调结果

    return true;
}

// 在 handle_realtime_process_message() 中新增:
bool handle_realtime_process_message(const CefRefPtr<CefProcessMessage>& message) {
    if (message->GetName() == "CameraMoveFast") {
        return handle_camera_move_fast(message);
    }
    if (message->GetName() == "DockCommand") {       // 新增
        return handle_dock_command(message);
    }
    return false;
}
```

### 5.6 Vue Bridge 接口

```js
// utils/dockBridge.js

/**
 * 发送 Dock 命令（通过 CefProcessMessage，不经过 Python）
 * @param {Object} params - 命令参数
 * @returns {Promise} 部分命令（如 createTab, listTabs）需要返回值
 */
export function dockCommand(params) {
    return new Promise((resolve, reject) => {
        // 对于需要返回值的命令，生成 requestId
        const requestId = params.cmd === 'createTab' || params.cmd === 'listTabs'
            ? generateRequestId()
            : null;

        if (requestId) {
            params._requestId = requestId;
            pendingRequests.set(requestId, { resolve, reject, timeout: setTimeout(...) });
        }

        try {
            window.coronaBridge.dockCommand(JSON.stringify(params));
            if (!requestId) resolve();
        } catch (e) {
            if (requestId) pendingRequests.delete(requestId);
            reject(e);
        }
    });
}

// 便捷方法
export const DockBridge = {
    createTab({ path, instanceId, context, dockingPos, dockWidth, dockHeight, dockFixed }) {
        return dockCommand({
            cmd: 'createTab',
            path, instanceId, context,
            dockingPos, dockWidth, dockHeight, dockFixed
        })
    },
    closeTab(tabId)   { return dockCommand({ cmd: 'closeTab', tabId }) },
    showTab(tabId)    { return dockCommand({ cmd: 'showTab', tabId }) },
    hideTab(tabId)    { return dockCommand({ cmd: 'hideTab', tabId }) },
    sendToTab(tabId, message) { return dockCommand({ cmd: 'sendToTab', tabId, message }) },
    broadcastToRoute(path, message) { return dockCommand({ cmd: 'broadcastToRoute', path, message }) },
    listTabs(path)    { return dockCommand({ cmd: 'listTabs', path }) },
}
```

### 5.7 Vue 状态管理

使用 Pinia store（替代组件内 composable，确保全局唯一）：

```js
// stores/dockStore.js
import { defineStore } from 'pinia'

export const useDockStore = defineStore('dock', () => {
    const tabRegistry = reactive(new Map()) // tabId → { instanceId, path, context }

    async function openTab(config, dedupStrategy = 'allowDuplicate') {
        if (dedupStrategy === 'singleton') {
            const existing = findTabs(config.path)[0]
            if (existing) {
                await DockBridge.showTab(existing.tabId)
                return existing.tabId
            }
        }
        if (dedupStrategy === 'byContext') {
            const existing = findTabs(config.path, config.context)[0]
            if (existing) {
                await DockBridge.showTab(existing.tabId)
                return existing.tabId
            }
        }
        const result = await DockBridge.createTab(config)
        tabRegistry.set(result.tabId, {
            instanceId: config.instanceId,
            path: config.path,
            context: config.context
        })
        return result.tabId
    }

    function closeTab(tabId) {
        DockBridge.closeTab(tabId)
        tabRegistry.delete(tabId)
    }

    function findTabs(path, contextFilter) {
        return [...tabRegistry.values()].filter(t =>
            t.path === path &&
            (!contextFilter || matchContext(t.context, contextFilter))
        )
    }

    function onTabClosedFromCpp(tabId) {
        // 由 window.__onTabClosed 调用
        tabRegistry.delete(tabId)
    }

    return { tabRegistry, openTab, closeTab, findTabs, onTabClosedFromCpp }
})
```

## 6. 同名多实例的去重策略

### 6.1 创建时的去重判断

去重决策由**调用方**（打开标签页的组件）负责，而非 Dock 系统：

| 策略 | 行为 | 适用场景 | 示例 |
|---|---|---|---|
| **allowDuplicate** | 每次都创建新标签页 | 属性面板（不同对象）、日志视图 | 同时查看 Actor_A 和 Actor_B 的属性 |
| **byContext** | 相同 context 时聚焦已有标签页 | 属性面板（同一对象） | 重复点击 Actor_A 的属性按钮 |
| **singleton** | 相同 path 时聚焦已有标签页 | 项目设置、启动器、文件管理器 | 只允许一个设置页面 |

```js
// 使用示例
const dockStore = useDockStore()

// 属性面板 — 不同对象允许多开，同一对象去重
dockStore.openTab({
    path: '/Object',
    instanceId: `props_${actorId}`,
    context: { actorId }
}, 'byContext')

// 项目设置 — 单例
dockStore.openTab({
    path: '/ProjectSettings',
    instanceId: 'settings'
}, 'singleton')
```

### 6.2 关闭时的清理路径

有三种关闭路径，都需要正确清理：

```
路径 1: Vue 主动关闭
  dockStore.closeTab(tabId)
    → DockBridge.closeTab(tabId)
      → dockCommand({ cmd: 'closeTab', tabId })
        → BrowserManager::remove_tab(tabId)
          → ImGui dock 窗口销毁

路径 2: 用户点击 ImGui dock 窗口 X 按钮
  ImGui 窗口关闭
    → imgui_ui.cpp: tabs_to_close 列表
      → BrowserManager::remove_tab(tabId)
        → 通知主视图 frame（通过 ExecuteJavaScript）
          → window.__onTabClosed(tabId)
            → dockStore.onTabClosedFromCpp(tabId)

路径 3: Vue 页面内自行关闭
  页面组件调用 dockStore.closeTab(myTabId)
    → 同路径 1
```

**关键**：`BrowserManager::remove_tab()` 中需新增通知逻辑：

```cpp
void BrowserManager::remove_tab(int tab_id) {
    // ... 现有清理逻辑 ...

    // 通知主视图：标签页已关闭
    // 向 path == "/" (MainPage) 的标签页发送通知
    auto main_tabs = get_tabs_by_path("/");
    for (auto* tab : main_tabs) {
        if (tab->client && tab->client->GetBrowser()) {
            std::string js = "window.__onTabClosed&&window.__onTabClosed("
                           + std::to_string(tab_id) + ")";
            tab->client->GetBrowser()->GetMainFrame()->ExecuteJavaScript(js, "", 0);
        }
    }
}
```

## 7. Vue 层返回值机制

### 7.1 问题

`window.cefQuery()` 天然支持回调（`onSuccess`/`onFailure`），但 `CefProcessMessage` 是单向的。对于 `createTab`（需要返回 `tabId`）和 `listTabs`（需要返回列表），需要设计异步返回值机制。

### 7.2 方案：requestId + 回调注入

```
Vue: dockCommand({ cmd: 'createTab', ..., _requestId: 'req_001' })
  → CefProcessMessage("DockCommand") → C++ Browser Process
  → 执行 create_tab() → 得到 tabId = 5
  → frame->ExecuteJavaScript(
      "window.__dockCallback('req_001', null, {tabId: 5})"
    )

Vue: pendingRequests['req_001'].resolve({ tabId: 5 })
```

```js
// dockBridge.js 中的回调注册
const pendingRequests = new Map()
let requestIdCounter = 0

function generateRequestId() {
    return 'dock_' + (++requestIdCounter) + '_' + Date.now()
}

// 全局回调函数（C++ 执行此函数返回结果）
window.__dockCallback = (requestId, error, result) => {
    const pending = pendingRequests.get(requestId)
    if (!pending) return
    clearTimeout(pending.timeout)
    pendingRequests.delete(requestId)
    if (error) pending.reject(new Error(error))
    else pending.resolve(result)
}
```

### 7.3 无需返回值的命令

以下命令不需要返回值，直接 fire-and-forget：

- `closeTab`、`showTab`、`hideTab` — 操作结果由侧效应体现（窗口消失/出现）
- `sendToTab`、`broadcastToRoute` — 消息投递不保证送达，业务层自行处理失败

## 8. 改造步骤

### 第一阶段：C++ 基础设施

| # | 变更 | 文件 |
|---|---|---|
| 1 | `BrowserTab` 增加 `path`、`instance_id`、`context_json` 字段 | `browser_manager.h` |
| 2 | `BrowserManager` 新增 `get_tabs_by_path()`、`send_to_tab()`、`broadcast_to_route()`、`list_tabs_json()` | `browser_manager.h` / `.cpp` |
| 3 | `BrowserManager::create_tab()` 接收 `instance_id`、`context_json` 参数，存储到 `BrowserTab` | `browser_manager.cpp` |
| 4 | `BrowserManager::remove_tab()` 中新增通知主视图逻辑 | `browser_manager.cpp` |
| 5 | `cef_realtime_bridge.cpp` 新增 `handle_dock_command()` | `cef_realtime_bridge.cpp` |
| 6 | `cef_subprocess/main.cpp` 新增 `DockCommandHandler` V8 类，注入 `coronaBridge.dockCommand` | `cef_subprocess/main.cpp` |
| 7 | `cef_py_bind.cpp` 移除 `minimize_browser_tab`、`restore_browser_tab`、`set_tab_drag_regions`、`create_browser_tab` | `cef_py_bind.cpp` |

### 第二阶段：Vue 基础设施

| # | 变更 | 文件 |
|---|---|---|
| 8 | 新增 `utils/dockBridge.js` — `dockCommand()` 及 `DockBridge` 便捷方法 | `Frontend/src/utils/dockBridge.js` (新建) |
| 9 | 新增 `stores/dockStore.js` — 全局标签页状态管理 | `Frontend/src/stores/dockStore.js` (新建) |
| 10 | `MainPage.vue` 注册 `window.__onTabClosed`、`window.__dockCallback` | `MainPage.vue` |
| 11 | `MainPage.vue` 中 `setupListener()` 改为使用 `dockStore` 替代 `appService.addDockWidget` | `MainPage.vue` |

### 第三阶段：页面改造

| # | 变更 | 文件 |
|---|---|---|
| 12 | 所有 Vue 页面组件在 `setup` 中从 `route.query` 读取 `tabId`、`instanceId`、`context` | 各 `views/**/*.vue` |
| 13 | 各页面注册 `window.__onTabMessage` 处理逻辑 | 各 `views/**/*.vue` |
| 14 | 调用方组件（场景树等）使用 `useDockStore().openTab()` 替代 `appService.addDockWidget()` | 各调用方组件 |

### 第四阶段：Python 清理

| # | 变更 | 文件 |
|---|---|---|
| 15 | `CoronaEditor` 删除 `tab_list`、`open_browser()`、`minimize_browser()`、`close_browser_for_js()`、`update_drag_regions()`、`js_call_func()` | `corona_editor.py` |
| 16 | `PluginBase` 删除 `docking_pos`、`dock_width`、`dock_height`、`dock_fixed` 属性 | `corona_plugin_base.py` |
| 17 | 插件 `register_web` 装饰器删除停靠相关参数 | `corona_plugin_base.py` |

## 9. 风险与注意事项

| 风险 | 缓解措施 |
|---|---|
| `CefProcessMessage` 参数大小限制 | 消息体限制约几十 KB，仅传元数据（tabId、instanceId、path、小型 JSON）。不传大数据。 |
| 用户直接关闭 ImGui dock 窗口导致 Vue 状态不一致 | C++ `remove_tab()` 时通知主视图 frame → `__onTabClosed` → store 清理 |
| `createTab`/`listTabs` 返回值依赖 JS 回调，可能丢包 | `dockBridge.js` 中设置 5 秒超时，超时 reject 并清理 `pendingRequests` |
| 页面刷新（`window.location.reload()`）后丢失消息监听 | `onMounted` 时从 `route.query` 恢复身份并重新注册 `__onTabMessage`；窗口层面无影响 |
| CEF renderer 进程崩溃后标签页重建 | `OnRenderProcessTerminated` 中通知主视图，store 移除对应 tab 记录 |
| 多个调用方同时操作同一标签页 | `BrowserManager` 内操作幂等——`show_tab` 对已显示的 tab 是 no-op，`remove_tab` 对不存在的 tab 是 no-op |

## 10. 旧方案 vs 新方案对比

| 维度 | 旧方案（Python 管理） | 新方案（Vue 管理） |
|---|---|---|
| 同名多实例 | 不支持（`tab_list` 以 path 为 key） | 支持（以 `instance_id` 区分） |
| 页面间定向通信 | 需要 Python `js_call_func(path, fn, args)` 中转，必须知道 path | C++ 直接向 `tabId` 投递，无需知道 path |
| 页面间广播通信 | 不支持（一个 path 只有一个 tab） | 支持 `broadcastToRoute(path, msg)` |
| 通信延迟 | Vue → CefMessageRouter → BrowserSideJSHandler → GIL → Python → nanobind → BrowserManager | Vue → CefProcessMessage → BrowserManager (无 GIL，无 Python) |
| 热路径阻塞 | Python GIL 在 UI 操作路径上 | 窗口操作完全不经过 Python |
| 布局配置 | Python 插件类属性 | Vue 路由 meta 或 store 配置 |
| 可调试性 | 跨 Vue/C++/Python 三层 | 窗口逻辑集中在 Vue + C++ |
| 通信返回值 | `cefQuery` 原生支持 Promise | 需 `requestId` + `__dockCallback` 机制 |
