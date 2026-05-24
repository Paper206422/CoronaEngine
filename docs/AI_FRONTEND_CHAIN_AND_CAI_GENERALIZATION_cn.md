# 前端调用 AI 链路与 CAI 通用库化方案

> **创建日期**: 2026年5月7日  
> **适用范围**: CabbageEditor 前端、CEF/Python 桥接、AITool 插件、CoronaArtificialIntelligence（CAI）  
> **目标**: 梳理当前从前端调用 AI 的完整链路，识别可优化点，并给出将 CAI 演进为通用 AI 库的开发方案。

---

## 1. 总览

当前 AI 能力由 CabbageEditor 前端触发，通过 CEF `window.cefQuery` 进入 C++，再调用 Python 编辑器核心，最终由 AITool 插件调用 CAI 库完成模型、Agent、工具和工作流执行。返回结果仍采用“前端发起请求 + Python 主动执行 JS 回调”的流式模式，但入口已经从早期的弱类型 AI 调用逐步收敛到 `aiClient.chatStream`、`AITool.ai_rpc` 和 `CAIApp.chat_stream`。

当前推荐链路可以概括为：

```text
Vue AITalkBar
  -> aiClient.chatStream(request)
  -> bridge.js / window.cefQuery
  -> C++ CEF MessageRouter
  -> Python CoronaEditor.deal_func_from_js
  -> AITool.ai_rpc(request)
  -> AIPluginController / AIRequestService
  -> CAIClient
  -> CAIApp.chat_stream(request)
  -> workflow route / LangChain Agent / tools / media registry
  -> stream chunk / StreamEvent-compatible envelope
  -> CoronaEditor.js_call_func
  -> C++ execute_javascript
  -> Vue window.receiveAIMessageChunk
```

CAI 已经具备独立导入、`CAIApp` facade、`CAIRuntime`、插件管理器、CabbageEditor adapter 和 `pyproject.toml` 包化入口，可以视为“初步通用化完成”。它尚未完全成为多实例隔离的通用 runtime，因为默认 registry 仍通过 `LazyRegistryRef` 指向 legacy 全局对象，部分旧模块仍依赖 import side effect 和兼容单例。由于 `CoronaArtificialIntelligence` 是 Editor 的 submodule，后续通用库化仍应保持物理目录不变，在内部继续推进 runtime scoped registry 和显式插件化。

---

## 2. 当前调用链路详解

### 2.1 前端输入层

入口页面为 `Frontend/src/views/sidebar/AITalkBar.vue`。

主要职责：

- 维护聊天消息列表、发送状态、流式状态、审核面板状态。
- 将用户输入拆分为文本 part、slash command part、图片 part。
- 生成并维护 `session_id`。
- 优先调用 `aiClient.chatStream(request)` 发送消息，旧 `aiService.sendMessageToAIStream(payload)` 保留兼容。
- 通过全局函数 `window.receiveAIMessageChunk` 接收 Python 回调。

当前请求结构大致如下：

```json
{
  "session_id": "uuid-or-sid",
  "llm_content": [
    {
      "role": "user",
      "interface_type": "integrated",
      "sent_time_stamp": 1778112000000,
      "part": [
        {
          "content_type": "text",
          "content_text": "帮我生成一个场景"
        },
        {
          "content_type": "image",
          "content_url": "data:image/png;base64,...",
          "content_path": "optional/local/path.png",
          "content_text": "product",
          "parameter": {}
        }
      ]
    }
  ],
  "metadata": {}
}
```

其中 `llm_content[].part[]` 是当前 AI 协议的核心承载结构，负责承载 text/image/audio/video/file/review 等多种内容。

### 2.2 前端桥接层

入口文件为 `Frontend/src/utils/bridge.js`。

`Bridge.callCEF(moduleName, methodName, args)` 将请求转换为通用 CEF RPC。AI 新入口使用：

```json
{
  "module": "AITool",
  "function": "ai_rpc",
  "args": [{ "operation": "chat.stream", "request_id": "req_..." }]
}
```

旧兼容入口仍支持：

```json
{
  "module": "AITool",
  "function": "send_message_to_ai_stream",
  "args": ["{...payload json string...}"]
}
```

并调用：

```javascript
window.cefQuery({
  request: JSON.stringify(request),
  persistent: false,
  onSuccess,
  onFailure
});
```

这个调用只代表“请求已交给 Python 侧”，不代表 AI 生成已经完成。AI 流式结果不通过 `onSuccess` 返回，而是通过后续 JS 回调进入 `receiveAIMessageChunk`。当前 `bridge.js` 同时暴露 `aiClient.chatStream`、`cancelRequest`、`getRequestStatus` 和旧 `aiService`。

### 2.3 CEF 与 C++ 桥接层

CEF 初始化时将 JS 查询函数设置为：

```cpp
message_router_config.js_query_function = "cefQuery";
message_router_config.js_cancel_function = "cefQueryCancel";
```

前端调用 `window.cefQuery` 后，C++ 侧 `BrowserSideJSHandler::OnQuery` 会：

1. 拿到 JSON 字符串请求。
2. 确保 Python 初始化。
3. 调用 Python 中的 `main.editor.deal_func_from_js`。
4. 将 Python 返回值通过 `callback->Success(result)` 返回给前端。

这里 C++ 层目前基本是透明转发层，没有理解 AI 业务，也没有做 RPC schema 校验。

### 2.4 Python 编辑器分发层

入口为 `CoronaCore/core/corona_editor.py` 的 `CoronaEditor.deal_func_from_js(json_str)`。

处理流程：

1. `json.loads(json_str)` 解析请求。
2. 读取 `module`、`function`、`args`。
3. 在 `CoronaEditor.module_list` 中查找对应插件类。
4. 使用 `getattr(module, func_name)(*args)` 反射调用。
5. 使用 `create_success_response(result)` 或 `create_error_response(...)` 包装结果返回给 CEF。

插件注册由 `PluginBase.register_web(...)` 完成，例如 AITool 注册为：

```python
@PluginBase.register_web("AITool", "/Pet", "AI插件", 1, "bottom_right", 200, 200, False, True)
class AITool(PluginBase):
    ...
```

因此前端的 `module: "AITool"` 最终会映射到该 Python 类。

### 2.5 AITool 插件桥接层

入口为 `plugins/AITool/main.py`。

AITool 当前已经拆成薄入口和服务层：

- `AITool.main`: 只保留 CEF 暴露方法、服务装配和 cleanup。
- `AIPluginController`: 承接旧入口、新 `ai_rpc`、流式消费、错误转发和 cleanup 编排。
- `AIRequestService`: 管理 request lifecycle、状态查询、取消请求和 task 绑定。
- `MediaIngress`: 处理现有 base64 图片上传、token 提取和媒体入站兼容。
- `CAIClient`: 调用 `CAIApp.chat_stream()`，并将同步 generator 桥接到 bounded stream queue。
- `StreamDispatcher`: 识别 `data/heartbeat/done/error` 并派发 JS 回调。
- `EventLoopRunner`: 管理 AITool 原有 asyncio loop 线程和任务提交。

流式处理的核心流程：

```text
ai_rpc(request) / send_message_to_ai_stream(legacy_payload)
  -> AIPluginController
  -> AIRequestService accepts request_id/session_id
  -> MediaIngress preprocesses image/base64 parts
  -> CAIClient.start_stream(payload)
  -> CAIApp.chat_stream(payload)
  -> bounded stream queue
  -> StreamDispatcher.send_to_frontend(chunk)
  -> CoronaEditor.js_call_func("/AITalkBar", "receiveAIMessageChunk", [chunk])
```

### 2.6 CAI 动态入口层

入口为 `CoronaArtificialIntelligence/ai_service/entrance.py`。

CAI 使用 `module_settings.yaml` 决定模块加载顺序。每个模块可能包含：

- `configs/settings.py`: 注册配置。
- `base.py`: 注册功能入口。
- `tools/loader.py`: 注册 loader 或工具。

模块函数通过装饰器注册到 `ai_entrance`：

```python
@register_entrance(handler_name="handle_integrated_entrance_stream")
def handle_integrated_entrance_stream(payload):
    ...
```

`get_ai_entrance()` 首次调用时会执行 `reimport()`，触发模块加载与注册。

### 2.7 CAI integrated stream 层

入口为 `ai_modules/integrated/base.py`。

职责：

- 解析 payload。
- 获取 `session_id` 和 `metadata`。
- 读取 AI 配置。
- 通过 `session_concurrency` 做同一会话并发保护。
- 调用 `handle_integrated_entrance_stream_inner(...)`。

内部处理位于 `ai_modules/integrated/stream_handler.py`：

1. 校验 `llm_content`。
2. 尝试 `resolve_and_stream_workflow(...)`，命中 slash command 或 workflow route 时走工作流。
3. 未命中工作流时，构造 LangChain message history。
4. 调用 `stream_agent(pending_history)`。
5. 将 `AIMessage` 转换为 text part。
6. 将 `ToolMessage` 转换为 image/audio/video/file/review 等 part。
7. 输出 heartbeat、success chunk、error chunk、stream done。

### 2.8 前端流式接收层

前端通过 `window.receiveAIMessageChunk(data)` 接收结果。

主要逻辑：

- 更新 `session_id`。
- 检测错误响应。
- 检测 `metadata.stream_done`，结束当前气泡。
- 检测 `metadata.heartbeat`，刷新断连计时器。
- 遍历 `llm_content` 中的 assistant parts。
- 将 text 合并到当前流式气泡。
- 将 image/video/audio/review 渲染为对应 UI。
- 收到 review pending 时初始化审核编辑状态。

### 2.9 技术自检结论

本节链路已按当前代码核对，结论如下：

- 前端已有 `aiClient.chatStream`、`cancelRequest`、`getRequestStatus`，旧 `aiService.sendMessageToAIStream(payload)` 仍保留兼容。
- `AITalkBar.vue` 已引入 `request_id`，消息模型已按 request 归属 chunk；图片 part 仍以 `content_url`、`content_path`、`content_text` 和 `parameter` 为主，资源句柄化尚未完成。
- `CoronaEditor.deal_func_from_js` 仍按 `{module, function, args}` 反射分发，并通过 `create_success_response` / `create_error_response` 返回 CEF 请求结果；AI 专用入口通过 `AITool.ai_rpc(request)` 收敛。
- AITool 主类已拆薄，流式处理由 `AIPluginController`、`AIRequestService`、`MediaIngress`、`CAIClient`、`StreamDispatcher` 和 `EventLoopRunner` 承接。
- AITool 当前通过 `CAIApp.chat_stream()` 调用 CAI，不再由 `CAIClient` 直接持有 `get_ai_entrance()`；但 `_cai_app` 仍通过 `CAIApp.from_legacy_entrance(lambda: get_ai_entrance())` 保持旧入口兼容。
- CAI integrated 入口仍通过 `session_concurrency` 做同一会话并发保护，并由 `handle_integrated_entrance_stream_inner` 优先路由 workflow，未命中时再走 Agent。
- CAI 响应仍兼容 legacy envelope：`session_id`、`error_code`、`status_info`、`llm_content`、`metadata`；`stream_done` 和 `heartbeat` 仍通过 `metadata` 表达，同时新入口已能识别 `data/heartbeat/done/error`。
- workflow 执行器还会发送带 `metadata.workflow_node_boundary` 的 heartbeat，前端当前会据此结束当前流式气泡的等待态。
- 前端除 `window.receiveAIMessageChunk` 外仍保留 `window.receiveAIMessage` 兼容旧非流式响应；`window.receiveAIMessageChunk` 尚未完全降级为事件总线入口。
- `CoronaEditor.js_call_func` 当前通过拼接 JS 字符串调用 `window.<function_name>(...)`，因此函数名仍是字符串级约定，不是类型化事件通道。
- `CAIApp`、`CAIRuntime`、`PluginManager`、CabbageEditor adapter 和包化入口已经落地；runtime scoped registry 仍未完成，默认 runtime 仍会解析 legacy 全局 registry。

---

## 3. 当前链路中的主要问题

### 3.1 RPC 协议过于松散

前端向 Python 发送的是通用 `{module, function, args}`。这种方式简单，但存在问题：

- 无正式 schema，参数错误只能运行时发现。
- Python 侧直接反射调用，缺少权限边界。
- AI 请求和普通 UI 请求混用同一套弱类型通道。
- 错误码、异常类型、超时语义不统一。

### 3.2 request_id 问题已基本解决

早期链路只有 `session_id`，没有独立 `request_id`，导致多轮请求并发时前端难以准确归属 chunk，也不利于取消、重试、恢复和日志追踪。当前阶段已经完成 `request_id` 的生成、透传和前端按 request 归属消息。

剩余工作主要是把 `request_id` 继续用于更完整的可观测性：后端日志、错误 envelope、取消 token、workflow 节点事件和模型调用 trace 应统一输出同一个 `request_id/session_id`。

### 3.3 请求返回与 AI 结果返回仍是两套语义

`Bridge.callCEF(...send_message_to_ai_stream...)` 的成功只表示 Python 已接收请求。真正 AI 结果通过 `execute_javascript` 回调。

这本身可以接受，但需要明确建模为：

- `accepted`: 请求已进入后端队列。
- `stream_event`: 后续流式事件。
- `done`: 请求完成。
- `error`: 请求失败。
- `cancelled`: 请求取消。

当前新入口已经能识别 `data/heartbeat/done/error`，并支持 `request.cancel`，但协议层仍未完全统一：错误结构、取消传播和部分 legacy chunk 仍依赖 `metadata.stream_done`、`metadata.heartbeat` 等兼容字段。因此这里已经从“缺少阶段建模”变成“新旧事件模型并存”。

### 3.4 AITool 主类已拆薄

早期 AITool 同时承担宿主桥接、异步调度、图片上传、token 处理、CAI 调用、JS 回调等职责，容易让插件层变成新的“大对象”。当前已经拆分为：

- `AIPluginController`: 暴露给 CEF 的插件 API。
- `AIRequestService`: 处理 request lifecycle。
- `CAIClient`: 调用 CAI runtime。
- `StreamDispatcher`: 负责把 stream event 派发回前端。
- `MediaIngress`: 负责文件/base64/path 进入媒体仓库。

因此 AITool 主类现在主要保留 CEF 暴露方法，内部处理委托给 controller/service。后续重点不再是“拆薄主类”，而是继续补齐 cancellation token、统一错误 envelope 和资源句柄式媒体入口。

### 3.5 CAI 全局状态已收敛但未完全实例化

早期 CAI 依赖 `ai_entrance.collector`、`get_ai_config()` 模块级缓存、`WorkflowRegistry` 全局单例、tool/media/conversation 等全局 registry，并通过 import 模块触发装饰器注册。这些设计已经被阶段 3-6 明显缓解：

- 新增 `CAIApp` 与 `CAIRuntime`，外部宿主可以通过 facade 调用 `chat_stream()`。
- `PluginManager` 接管 `module_settings.yaml` 的加载编排，新插件可以显式注册到 runtime。
- `CAIRuntime` 已提供 `capabilities`、`set_registry()`、`get_registry()`，允许注入 runtime scoped registry。
- `cai_extensions` 不再在 import 或 install 时修改 `sys.path`。
- CAI 已有 `pyproject.toml`、CLI 示例、FastAPI/WebSocket 示例和 API reference，具备编辑器外引用的基础形态。

但 CAI 还没有达到“所有运行状态都 runtime scoped”的最终形态。当前 `CAIRuntime._create_default_registries()` 仍通过 `LazyRegistryRef` 指向 legacy 全局 registry；`get_default_runtime()` / `get_default_app()` 仍作为兼容单例存在；`LegacyModulePlugin` 仍会通过导入旧模块触发装饰器注册。因此它已经从“插件内 AI 后端”演进为“可独立使用的通用库雏形”，但还不是完全隔离、可多租户并行的 runtime library。

### 3.6 宿主专属逻辑已进入 adapter

`cai_extensions` 已经整理为 CabbageEditor adapter，并通过 `CabbagePathsPlugin`、`CabbageAppConfigPlugin`、`CabbageEngineToolsPlugin`、`CabbageWorkflowPlugin`、`CabbageEngineModulesPlugin` 向指定 `CAIApp/runtime` 注册宿主能力。CabbageEditor 专属路径解析、engine tools、workflow 和预加载模块不再放入 CAI 通用核心。

当前边界已经接近目标状态：

```text
CAI 通用核心不知道 CabbageEditor
CabbageEditor adapter 持有 CAI runtime 实例并向其注册能力
```

剩余风险主要来自 adapter 内部仍为 legacy 兼容保留了少量全局 setter，例如路径 resolver 和 app config provider 会同时写入 runtime capability 与旧全局入口。只要旧模块仍读取这些全局 provider，宿主能力就还没有完全实例隔离。

### 3.7 大文件通过 base64 过桥效率较低

图片当前可在前端转成 base64，再穿过 CEF 和 Python。对于大图、视频、音频、3D 文件，这会导致：

- JS 内存占用增加。
- JSON payload 变大。
- CEF/Python 边界复制成本增加。
- 日志误打印时风险变高。

应优先使用路径、文件 ID、临时资源句柄或宿主文件选择结果。

### 3.8 小型桥接不一致已修正

`Frontend/src/utils/bridge.js` 中 `aiService.readLocalFileAsBase64` 已按 `Bridge.callCEF` 的参数约定传入数组：

```javascript
readLocalFileAsBase64: (filePath) =>
  Bridge.callCEF('AITool', 'read_local_file_as_base64', [filePath]),
```

该问题已不再列入后续任务。当前桥接层剩余重点是把 AI 事件接收从全局函数降级为事件总线入口，并把错误、取消和资源句柄协议统一起来。

---

## 4. 链路优化方案

### 4.1 定义 AI 专用 RPC Envelope

建议将 AI 请求从通用 CEF RPC 中抽象出专用协议。

前端发起请求：

```json
{
  "module": "AITool",
  "function": "ai_rpc",
  "args": [
    {
      "version": 1,
      "request_id": "req_...",
      "session_id": "sid_...",
      "operation": "chat.stream",
      "payload": {
        "llm_content": []
      },
      "metadata": {
        "source": "AITalkBar"
      }
    }
  ]
}
```

Python 立即返回：

```json
{
  "success": true,
  "request_id": "req_...",
  "status": "accepted"
}
```

后续 stream event：

```json
{
  "version": 1,
  "request_id": "req_...",
  "session_id": "sid_...",
  "event_type": "data",
  "sequence": 12,
  "payload": {
    "llm_content": []
  },
  "metadata": {}
}
```

推荐事件类型：

| event_type | 含义 |
| --- | --- |
| `accepted` | 后端已接受请求 |
| `data` | 普通内容 chunk |
| `heartbeat` | 心跳 |
| `review` | 需要用户审核/确认 |
| `progress` | 工作流进度 |
| `done` | 流结束 |
| `error` | 请求失败 |
| `cancelled` | 请求被取消 |

### 4.2 增加 request lifecycle 管理

AITool 侧维护请求表：

```python
class AIRequestState:
    request_id: str
    session_id: str
    status: Literal["accepted", "running", "done", "error", "cancelled"]
    task: asyncio.Task | None
    future: Future | None
    created_at: float
    updated_at: float
```

需要支持的操作：

- `chat.stream`: 开始流式请求。
- `request.cancel`: 取消请求。
- `request.status`: 查询请求状态。
- `session.reset`: 清空会话历史。
- `session.info`: 查看会话缓存状态。

### 4.3 前端改为 request_id 驱动

前端消息模型建议增加：

```javascript
{
  id: "ui_msg_...",
  requestId: "req_...",
  sessionId: "sid_...",
  sender: "AI",
  parts: [],
  status: "streaming"
}
```

接收 chunk 时按 `request_id` 找到对应消息，而不是依赖 `currentStreamingMessage` 单一全局变量。

这样可以支持：

- 多请求并发。
- 多窗口复用同一 AI service。
- 请求重试后保留原消息关系。
- 日志按 request 追踪。

### 4.4 JS 回调从全局函数改为事件分发

保留兼容入口：

```javascript
window.receiveAIMessageChunk = (event) => {
  aiStreamBus.dispatch(event);
};
```

组件内部订阅：

```javascript
const unsubscribe = aiStreamBus.subscribe(requestId, handleStreamEvent);
```

这样可以降低全局函数和页面组件之间的耦合。

### 4.5 媒体输入改为资源句柄优先

推荐优先级：

1. `file_id`: 已进入 CAI media registry 的资源。
2. `file_path`: 宿主可访问的本地路径。
3. `file_url`: file/http/https URL。
4. `data_url`: base64，仅作为兜底。

建议 part 结构扩展为：

```json
{
  "content_type": "image",
  "content_text": "product",
  "resource": {
    "kind": "file_path",
    "value": "D:/project/assets/input.png",
    "mime_type": "image/png"
  },
  "parameter": {}
}
```

CAI 内部统一转换为 media registry 的 `fileid://...`。

### 4.6 统一错误模型

建议统一错误结构：

```json
{
  "event_type": "error",
  "request_id": "req_...",
  "session_id": "sid_...",
  "error": {
    "code": "MODEL_TIMEOUT",
    "message": "模型请求超时",
    "recoverable": true,
    "detail": "...",
    "source": "model.openai"
  }
}
```

错误分类建议：

| code | 场景 |
| --- | --- |
| `INVALID_REQUEST` | 请求结构错误 |
| `SESSION_BUSY` | 同一 session 并发冲突 |
| `MODEL_TIMEOUT` | 模型请求超时 |
| `MODEL_RATE_LIMIT` | 模型限流 |
| `TOOL_FAILED` | 工具执行失败 |
| `MEDIA_RESOLVE_FAILED` | 媒体资源解析失败 |
| `WORKFLOW_FAILED` | 工作流执行失败 |
| `CANCELLED` | 用户取消 |
| `INTERNAL_ERROR` | 未分类后端错误 |

### 4.7 明确 stream done 的唯一职责

建议规定：

- CAI 通用核心产生业务 chunk。
- stream wrapper 负责补齐 `done/error/cancelled`。
- workflow 内部不直接发最终 done，除非协议明确允许。

这样可以避免重复 done 或漏 done。

### 4.8 前端消息界面支持富文本

当前 `AITalkBar.vue` 对 text part 主要使用纯文本渲染。AI 输出通常包含 Markdown、代码块、表格、列表、引用、链接和工具执行摘要，因此前端消息模型需要从“纯字符串气泡”升级为“富文本 part 渲染”。

建议分两层处理：

- 协议层仍保留 `content_type: "text"` 兼容旧 chunk，并通过 `metadata.format` 或 part 字段标记文本格式。
- 渲染层将 text part 解析为安全的富文本视图，避免直接信任模型输出的 HTML。

推荐 part 扩展：

```json
{
  "content_type": "text",
  "content_text": "## 方案\n\n```cpp\n...\n```",
  "metadata": {
    "format": "markdown"
  }
}
```

前端渲染建议：

- 默认把 `text/plain` 按当前 `whitespace-pre-wrap` 渲染。
- 对 `markdown` 文本使用 Markdown parser 转为受限 HTML，再经 sanitizer 清洗后渲染。
- 支持标题、段落、列表、引用、行内代码、代码块、表格、链接和分隔线。
- 代码块支持语言标记、复制按钮和横向滚动，避免撑破聊天面板。
- 链接默认只允许 `http/https/file` 等白名单协议，并统一使用安全打开方式。
- 流式输出时先以增量文本缓存，按节流策略重新解析，避免每个 token 都触发完整重排。
- review/image/video/audio/file 等非文本 part 继续按现有组件渲染，不混入 Markdown HTML。

安全要求：

- 不允许模型输出的 `<script>`、事件属性、内联危险 URL 执行。
- 不直接对未清洗内容使用 `v-html`。
- 富文本样式限制在 AI 消息容器内，避免影响编辑器全局样式。
- Markdown 解析失败时回退为纯文本渲染。

---

## 5. CAI 通用库化目标架构

本方案默认 **不移动** `editor/plugins/AITool/CoronaArtificialIntelligence` 目录。CAI 继续作为 Editor 下的 submodule 存在，通用库化通过内部 API、运行时实例化和宿主适配解耦完成。

### 5.1 分层目标

建议将 CAI 在逻辑上拆成三层，而不是物理移动成多个顶层目录：

```text
CoronaArtificialIntelligence / 通用核心逻辑层
  通用 AI runtime：协议、配置、会话、媒体、模型、工具、Agent、Workflow。

CoronaArtificialIntelligence / 外部集成逻辑层
  可选外部集成：LangChain、LangGraph、OpenAI-compatible provider、账号池、HTTP client。

CabbageEditor cai_extensions 适配层
  CabbageEditor 专属适配：路径解析、引擎工具、场景工作流、CEF bridge。
```

核心原则：

- CAI 通用核心不 import CabbageEditor、CoronaEngine、CEF、前端路径。
- 宿主能力通过 adapter/plugin 注册进 runtime。
- 同一进程可创建多个 CAI runtime。
- 配置、工具、工作流、媒体仓库、会话存储都归属于 runtime 实例。
- 旧全局入口保留为兼容层，但不作为新代码依赖。

### 5.2 建议目录结构

长期结构建议是在 submodule 原地增加新抽象，不改变 `CoronaArtificialIntelligence` 的挂载位置：

```text
editor/plugins/AITool/
  main.py
  utils/
  cai_extensions/                 # CabbageEditor 专属适配层，保留在 AITool 下
    register.py                   # 兼容入口，后续演进为 install(app, context)
    paths_provider.py
    engine_tools/
    flows/

  CoronaArtificialIntelligence/   # Editor submodule，物理位置不移动
    pyproject.toml                # 可选：用于 editable install / 独立测试
    cai/                          # 新增：通用 facade 与 runtime API
      __init__.py
      app.py
      runtime.py
      protocol/
        request.py
        response.py
        stream.py
        errors.py
      plugins/
        manager.py

    ai_agent/                     # 现有目录，逐步由 runtime 管理
    ai_config/
    ai_media_resource/
    ai_models/
    ai_modules/
    ai_service/
    ai_tools/
    ai_workflow/
```

短期只需要在现有 `CoronaArtificialIntelligence` 内引入 `CAIApp`、`CAIRuntime`、协议对象和 plugin manager。后续如果需要独立分发，也建议通过 `pyproject.toml`、submodule tag、editable install 或 wheel 打包完成，而不是改变 Editor 内的目录布局。

### 5.3 CAIApp Facade

建议新增面向宿主的 facade：

```python
from cai import CAIApp, CAIConfig

config = CAIConfig.from_file("ai_settings.yaml")
app = CAIApp(config)

app.register_tools(...)
app.register_workflows(...)

for event in app.chat_stream(request):
    ...
```

核心 API：

```python
class CAIApp:
    def __init__(self, config: CAIConfig, runtime: CAIRuntime | None = None): ...

    def chat_stream(self, request: ChatRequest) -> Iterator[StreamEvent]: ...
    def chat(self, request: ChatRequest) -> ChatResponse: ...

    def register_tool(self, tool: ToolSpec) -> None: ...
    def register_tools(self, tools: Iterable[ToolSpec]) -> None: ...

    def register_workflow(self, workflow: WorkflowSpec) -> None: ...
    def register_plugin(self, plugin: CAIPlugin) -> None: ...

    def reset_session(self, session_id: str) -> None: ...
    def get_session_info(self, session_id: str) -> SessionInfo: ...

    def shutdown(self) -> None: ...
```

### 5.4 CAIRuntime 实例化

将当前多个全局单例收敛到 runtime：

```python
class CAIRuntime:
    config: CAIConfig
    tool_registry: ToolRegistry
    workflow_registry: WorkflowRegistry
    command_registry: WorkflowCommandRegistry
    media_registry: MediaRegistry
    conversation_store: ConversationStore
    model_registry: ModelRegistry
    plugin_manager: PluginManager
```

旧函数兼容方式：

```python
_DEFAULT_RUNTIME = CAIRuntime.from_default_config()

def get_workflow_registry():
    return _DEFAULT_RUNTIME.workflow_registry
```

新代码不再直接依赖这些全局函数。

### 5.5 插件机制替代 import side effect

当前模块加载依赖 import 触发装饰器。建议逐步改为显式插件注册：

```python
class CAIPlugin(Protocol):
    name: str

    def register(self, runtime: CAIRuntime) -> None:
        ...
```

模块示例：

```python
class TextGeneratePlugin:
    name = "text_generate"

    def register(self, runtime):
        runtime.config_registry.register_loader("text_generate", load_config)
        runtime.entrance_registry.register("handle_text_generation", handle_text_generation)
```

插件配置：

```yaml
plugins:
  - name: text_generate
    module: cai.plugins.text_generate
    enabled: true
  - name: integrated
    module: cai.plugins.integrated
    enabled: true
```

兼容阶段可以保留 `module_settings.yaml`，但内部转换为 plugin spec。

### 5.6 宿主适配层

CabbageEditor 适配层应该只做宿主相关工作：

- 提供项目路径、资源目录、截图目录。
- 注册引擎工具，例如场景查询、模型导入、相机控制。
- 注册 CabbageEditor 专属 workflow。
- 将 CAI stream event 转换为前端 bridge event。
- 将前端文件输入转换为 CAI media resource。

示例：

```python
def install_cabbage_editor_extension(app: CAIApp, context: CabbageContext) -> None:
    app.register_plugin(CabbagePathsPlugin(context))
    app.register_plugin(CabbageEngineToolsPlugin(context))
    app.register_plugin(CabbageWorkflowPlugin(context))
```

这比当前 `cai_extensions.install()` 更清晰，因为它作用于具体 `app/runtime`，而不是修改全局状态。

---

## 6. 迁移路线

### 阶段 0：建立基线

目标：不改行为，先保证可观测。

- [x] 为当前 AI 请求生成并记录 `request_id`。
- [x] 日志中统一输出 `request_id/session_id/event_type`。
- [x] 为 `stream_done`、`heartbeat`、error chunk 添加最小测试。
- [x] 记录当前 supported part 类型：text/image/audio/video/file/review。

验收标准：

- 一次前端请求可在前端、AITool、CAI 日志中用同一个 request id 串起来。
- 当前聊天、图片、workflow review 功能不退化。

### 阶段 1：桥接协议升级

目标：引入 AI RPC Envelope，但保留旧入口。

- [x] 新增 `AITool.ai_rpc(request)`。
- [x] 前端新增 `aiClient.chatStream(request)`，旧 `aiService` 保持兼容。
- [x] `send_message_to_ai_stream` 保留为兼容包装。
- [x] 前端接收 chunk 时按 `request_id` 更新消息。
- [x] 新增 `request.cancel`。

验收标准：

- 新旧入口均能发送消息。
- 新入口支持取消。
- 并发两条请求时 UI 不串消息。

### 阶段 2：AITool 内部拆分

目标：降低插件主类职责。

- [x] 在 AITool 内新增最小 request lifecycle registry，后续再拆为 `AIRequestService`。
- [x] 新增 `AIRequestService` 承接 request lifecycle registry。
- [x] 新增 `StreamDispatcher` 管理 JS 回调。
- [x] 新增 `MediaIngress` 承接现有 base64 图片入站，path/fileid 后续扩展。
- [x] 新增 `CAIClient` 封装 CAI 调用。
- [x] AITool 类只保留 CEF 暴露方法，内部处理委托给 controller/service。
- [x] 新增 bounded stream queue，并在消费者结束时停止后台 stream worker。

验收标准：

- AITool 主文件明显变薄。
- 请求状态、取消、错误处理集中在 request service。
- 流式事件格式统一。
- 当前阶段已通过 `plugins.AITool.tests.test_ai_rpc` 的 7 个标准库单元测试验证。

### 阶段 3：CAI Facade 与 Runtime

目标：建立通用库 API 的雏形。

- [x] 新增 `CAIApp`。
- [x] 新增 `CAIRuntime`。
- [x] 将 tool/workflow/media/conversation/config registry 以 lazy runtime registry ref 形式挂到 runtime，后续再替换底层全局单例。
- [x] 旧 `get_ai_entrance()` 内部委托默认 runtime。
- [x] AITool 改为调用 `CAIApp.chat_stream()`。

验收标准：

- 可以在单元测试中创建注入 legacy entrance 的独立 CAIApp。
- 旧入口仍兼容现有模块。
- 当前阶段已通过 `plugins.AITool.tests.test_ai_rpc` 的 9 个标准库单元测试验证。

### 阶段 4：插件系统显式化

目标：逐步替代 import side effect。

- [x] 定义 `CAIPlugin` 协议。
- [x] 将 `module_settings.yaml` 转换为 plugin manifest 兼容加载入口。
- [x] 以 `LegacyModulePlugin` 兼容包装 integrated/text/image/video/music/3d 等现有模块，统一通过 `PluginManager` 注册加载。
- [x] 装饰器注册保留兼容，并同步写入 runtime entrance registry。

验收标准：

- 新模块可以不依赖 import side effect 注册。
- 现有模块仍通过旧装饰器工作，但加载编排已进入 `PluginManager`。
- 插件启停、测试隔离更容易。
- 当前阶段已通过 `plugins.AITool.tests.test_ai_rpc` 的 12 个标准库单元测试验证。

### 阶段 5：宿主适配原地解耦

目标：在不移动 submodule 的前提下，形成 CAI 通用核心与 CabbageEditor adapter 的清晰边界。

- [x] 保留 `cai_extensions` 目录位置，将其整理为 CabbageEditor adapter。
- [x] CabbageEditor 专属 workflow 保留在 `cai_extensions/flows`，不进入 CAI 通用核心。
- [x] CabbageEditor 路径解析、engine tools 只在 adapter 中注册。
- [x] CAI 通用核心可在不加载 CabbageEditor adapter 的情况下 import。
- [x] 删除 `cai_extensions.register` 的 import-time `sys.path` 副作用，改为 AITool / install / plugin register 显式 bootstrap。
- [x] 彻底删除 legacy 绝对 import 对 `bootstrap_paths()` / `sys.path` 的兼容依赖。

验收标准：

- CAI 通用核心可在无 CabbageEditor 环境下 import。
- CabbageEditor 插件通过 adapter 安装宿主能力。
- 当前阶段已通过 `plugins.AITool.tests.test_ai_rpc` 的 16 个标准库单元测试验证。

实施说明：

- `cai_extensions/register.py` 保持原目录不变，新增 `CabbageContext`、`bootstrap_paths(context)`、`create_plugins(context)` 和 `install(app, context)`。
- adapter 被拆为 `CabbagePathsPlugin`、`CabbageAppConfigPlugin`、`CabbageEngineToolsPlugin`、`CabbageWorkflowPlugin`、`CabbageEngineModulesPlugin` 五类 CAI runtime plugin。
- `install()` 仍保留无参兼容模式；无参时安装到默认 `CAIApp`，传入 app 时安装到指定 `CAIApp/runtime`。
- CAI 根目录新增 package 标记，CAI 内部 `ai_config`、`ai_tools`、`ai_modules`、`ai_workflow` 等 legacy 顶层绝对导入已迁移为包内相对导入。
- AITool 与 `cai_extensions` 作为 Editor adapter，引用 CAI 时统一使用 `CoronaArtificialIntelligence...` 包绝对导入；只有 adapter 自身内部模块仍使用相对导入。
- `ai_service/entrance.py` 不再向 `sys.path` 写入 CAI 根目录；`PluginManager.load_module_settings()` 支持 package-relative `package_base`，用于加载 `module_settings.yaml` 中的 legacy module。
- AITool 不再调用 `bootstrap_paths()`；创建 `CAIApp` 后直接调用 `install(_cai_app)` 注册 CabbageEditor 宿主能力。
- `CAIRuntime` 新增 `capabilities`、`set_capability()`、`get_capability()`、`set_registry()` 和 `register_tool_loader_registrar()`，adapter 可将宿主能力挂到当前 runtime。
- `CabbagePathsPlugin` 和 `CabbageAppConfigPlugin` 已把 resolver/provider 写入 runtime capability，同时保留 legacy 全局 setter 兼容旧调用方。
- `CabbageEngineToolsPlugin` 已直接把 engine loader 注册到当前 runtime tool registry；`ai_tools.load_tools` 改为用 `_cai_builtin_loaders_registered` 标记判断内置 loader 是否已安装，避免宿主 loader 先注册后阻止 CAI 内置 loader。
- `cai_extensions.register` 不再在模块 import、`install(app, context)`、`create_plugins(context)` 或 plugin `register(runtime)` 时修改 `sys.path`；`bootstrap_paths(context)` 保留为兼容 no-op，只返回 `CabbageContext`。

### 阶段 6：独立发布准备

目标：具备通用库交付能力。

- [x] 新增 `pyproject.toml`。
- [x] 拆分 optional dependencies：`langchain`、`workflow`、`media`、`cabbage`。
- [x] 提供 CLI 示例。
- [x] 提供 FastAPI/WebSocket 示例。
- [x] 提供最小 README 和 API reference。

验收标准：

- 可以在 `editor/plugins/AITool/CoronaArtificialIntelligence` 目录执行 editable install 或直接以 submodule 方式被外部项目引用。
- 可以在编辑器外用 Python 脚本调用 `CAIApp.chat_stream()`。

实施说明：

- `CoronaArtificialIntelligence/pyproject.toml` 使用 setuptools 原地打包 submodule，安装包名为 `corona-artificial-intelligence`，导入包名为 `CoronaArtificialIntelligence`。
- Editor 侧代码也按该导入名引用 CAI，即 `from CoronaArtificialIntelligence.cai import CAIApp`，从而和编辑器外使用方式保持一致。
- optional dependencies 已按能力拆为 `langchain`、`workflow`、`media`、`cabbage`、`web`、`object-recognition` 和 `all`；其中 `cabbage` 保持为空，因为 CabbageEditor adapter 位于 submodule 外侧的 `plugins/AITool/cai_extensions`。
- 新增 console script `cai-chat`，入口为 `CoronaArtificialIntelligence.cai.cli:main`。
- 新增 `examples/cli_chat.py` 与 `examples/fastapi_websocket.py`，用于演示编辑器外直接调用 `CAIApp.chat_stream()`。
- 新增 `docs/API_REFERENCE.md`，记录 `CAIApp`、`CAIRuntime`、`ChatRequest`、`StreamEvent` 与 plugin API。

---

## 7. 下一步任务拆分

已完成的 request_id、AI RPC、AITool 拆分、CAIApp/CAIRuntime facade、CabbageEditor adapter 解耦、富文本渲染和独立发布准备不再列入活跃任务。后续只跟踪仍会影响通用化程度、协议一致性和用户体验的事项。

### 7.1 前端任务

- [ ] 将 `window.receiveAIMessageChunk` 降级为事件总线入口，组件内部按 `request_id` 订阅和解绑，避免全局函数直接驱动页面状态。
- [ ] 增加请求取消按钮、超时状态和重试入口，让 `request.cancel` 不只停留在 API 层。
- [ ] 媒体输入优先传 `file_path` / `resource` / `file_id`，仅在宿主无法提供资源句柄时回退到 base64。
- [ ] 将前端错误展示改为读取统一 error envelope，区分可恢复错误、用户取消、模型限流和工具失败。

### 7.2 Python AITool 任务

- [ ] 实现真实 cancellation token，从 `AIRequestService.cancel()` 传递到 `CAIClient` worker、CAI stream、workflow 和工具执行层。
- [ ] 统一错误 envelope，将当前 `build_error_response`、异常 chunk、legacy `error_code/status_info` 收敛为 `AIError` / `StreamEvent(event_type="error")`。
- [ ] 扩展 `MediaIngress`，支持 `file_id`、`file_path`、`file_url` 和 `data_url` 的统一解析，并限制大体积 base64 过桥。
- [ ] 为 request lifecycle 增加更完整的状态记录和日志字段：`accepted/running/done/error/cancelled`、耗时、chunk 数量和最后错误。

### 7.3 CAI 通用核心任务

- [ ] 把 config/tool/workflow/workflow_command/media/conversation/model registry 从默认 `LazyRegistryRef` 迁入 `CAIRuntime` 实例，旧全局 getter 只作为兼容代理。
- [ ] 将 integrated/text/image/video/music/3d 等 legacy module 逐步改为显式 `CAIPlugin.register(runtime)`，让 `LegacyModulePlugin` 只负责过渡兼容。
- [ ] 让 `CAIApp.chat_stream()` 输出统一 `StreamEvent` 对象或稳定 JSON envelope，减少调用方直接理解 legacy `metadata.stream_done` / `metadata.heartbeat`。
- [ ] 将 session concurrency、conversation store、media registry 和 model pool 的生命周期绑定到 runtime，支持同进程多 runtime 隔离。

### 7.4 CabbageEditor adapter 任务

- [ ] 移除路径 resolver、app config provider 等 adapter 插件对 legacy 全局 setter 的依赖，改为所有旧调用方通过 runtime capability 读取。
- [ ] 将 CabbageEditor 专属 workflow 和 engine modules 的预加载从 import side effect 迁移为显式 plugin register。
- [ ] 明确 adapter smoke test 的覆盖范围：无 CabbageEditor 环境只 import CAI core，有 CabbageEditor 环境才安装 `cai_extensions`。

### 7.5 测试任务

- [ ] 增加 session concurrency 测试，覆盖同一 session 并发请求的拒绝、排队或取消策略。
- [ ] 增加 media fileid/path resolve 测试，覆盖 `file_id`、`file_path`、`file_url`、`data_url` 和失败分支。
- [ ] 增加 workflow route 测试，验证 slash command / workflow route 命中、heartbeat、review 和 done 语义。
- [ ] 增加 tool recoverable error 测试，验证工具失败能进入统一 error envelope 且不破坏 stream 收尾。
- [ ] 增加独立库 CI smoke，验证无 CabbageEditor adapter 环境下的 import、editable install、CLI 和 `CAIApp.chat_stream()` 最小调用。

---

## 8. 风险与注意事项

### 8.1 不移动 submodule 目录

`CoronaArtificialIntelligence` 是 Editor 的 submodule，目录位置应保持稳定。CAI 当前依赖较多 import 路径和注册副作用，建议先加 facade/runtime，再逐步迁移内部依赖。不要通过移动目录来实现通用库化，否则容易破坏 submodule 管理、运行时路径和隐式 import。

### 8.2 保留旧协议兼容层

前端和插件可以先支持两套入口：

- 旧：`send_message_to_ai_stream(json_string)`。
- 新：`ai_rpc(request_object)`。

等新入口稳定后，再删除旧入口。

### 8.3 控制 stream 语义变化

前端现在依赖 `metadata.stream_done` 和 `metadata.heartbeat`。迁移到 `event_type` 时，应先同时输出两种字段，避免 UI 立即失效。

### 8.4 工作流与 Agent 统一事件模型

workflow chunk 和 agent chunk 应统一转换为 `StreamEvent`，不要让前端感知来源差异。前端只关心 event 类型和 parts。

### 8.5 避免宿主能力进入 core

通用库化过程中要坚持：

- CAI 通用核心不 import editor。
- CAI 通用核心不假设项目目录。
- CAI 通用核心不直接调用 C++/CEF。
- CAI 通用核心只暴露注册点和抽象接口。

---

## 9. 目标形态示例

### 9.1 编辑器内使用

```python
from cai import CAIApp, CAIConfig
from cai_extensions.register import CabbageContext, install

config = CAIConfig.from_default_locations()
app = CAIApp(config)

context = CabbageContext.from_default_locations()
install(app, context)

for event in app.chat_stream(request):
    stream_dispatcher.send_to_frontend(event)
```

### 9.2 编辑器外使用

```python
from cai import CAIApp, CAIConfig
from cai.protocol import ChatRequest, TextPart

app = CAIApp(CAIConfig.from_file("ai.yaml"))

request = ChatRequest.from_text(
    session_id="demo",
    text="请总结这段文字"
)

for event in app.chat_stream(request):
    if event.event_type == "data":
        print(event.text_delta(), end="")
```

### 9.3 Web 服务使用

```python
@app.websocket("/ai/chat")
async def chat(ws):
    request = await ws.receive_json()
    for event in cai_app.chat_stream(ChatRequest.model_validate(request)):
        await ws.send_json(event.model_dump())
```

---

## 10. 验收清单

短期链路优化完成后，应满足：

- [x] 每个 AI 请求都有 `request_id`。
- [x] 前端能按 `request_id` 归属 chunk。
- [x] 支持请求取消。
- [ ] 错误结构统一。
- [x] stream event 至少可识别 `data/heartbeat/done/error`。
- [ ] 图片不再强依赖 base64 过桥。
- [x] AI 文本消息支持安全富文本渲染，Markdown、代码块、表格、链接、列表和引用在流式与完成态下都能稳定显示。
- [x] 富文本渲染具备 sanitizer、链接协议白名单和纯文本回退，不允许模型输出执行脚本或污染全局样式。
- [x] AITool 主类只负责 CEF 暴露，不承载大量业务逻辑。

CAI 通用库化阶段完成后，应满足：

- [x] 可以在无 CabbageEditor 环境下 import CAI 通用核心。
- [x] 可以创建多个注入式 CAIApp facade 实例。
- [ ] 工具、工作流、媒体仓库、会话存储属于 runtime 实例。
- [x] CabbageEditor 能力通过 adapter 注册。
- [x] 旧 `get_ai_entrance()` 兼容入口仍可工作。
- [x] 有最小 CLI 或脚本示例证明 CAI 可独立使用。

### 10.1 CAI 库是否已经通用化

结论：**CAI 已经具备通用库的入口、打包形态和宿主适配边界，可以被视为“初步通用化完成”；但它尚未完成 runtime 级状态隔离，因此还不能判定为完全通用的多实例 AI runtime。**

已通用化的证据：

- **独立导入**：`CoronaArtificialIntelligence.cai` 可以在不加载 CabbageEditor adapter 的情况下 import。
- **稳定 facade**：`CAIApp.chat_stream()` 已成为编辑器内外统一调用入口，AITool 的 `CAIClient` 也已改为消费 `CAIApp`。
- **runtime 对象**：`CAIRuntime` 已承载入口 handler、capabilities、registry 注入点和 plugin manager。
- **插件边界**：`cai_extensions` 已成为 CabbageEditor adapter，宿主路径、工具和 workflow 通过 plugin 注册，而不是直接进入 CAI core。
- **包化准备**：CAI 已有 `pyproject.toml`、optional dependencies、`cai-chat` CLI、独立脚本示例、FastAPI/WebSocket 示例和 API reference。
- **兼容可控**：旧 `get_ai_entrance()` 与旧装饰器入口仍保留，降低了从插件后端迁移到通用库 facade 的风险。

尚未完全通用化的原因：

- **registry 仍未全部实例化**：默认 `CAIRuntime` 通过 `LazyRegistryRef` 解析 `get_ai_config()`、`get_tool_registry()`、`get_workflow_registry()`、`get_media_registry()`、`get_conversation_store()` 等 legacy 全局对象。
- **默认 app/runtime 仍是单例兼容层**：`get_default_runtime()` 和 `get_default_app()` 适合兼容旧代码，但不适合作为多租户隔离边界。
- **旧模块仍有 import side effect**：`LegacyModulePlugin` 统一编排了旧模块加载，但 integrated/text/image/video/music/3d 等模块本身还没有全部改成纯显式 `register(runtime)` 插件。
- **宿主 adapter 仍保留 legacy 全局 setter**：路径 resolver、app config provider 等能力已写入 runtime capability，但为了兼容旧调用方仍同步写入全局 provider。
- **协议与资源层仍有缺口**：错误 envelope、cancellation token、media fileid/path 资源句柄和 session concurrency 测试尚未全部完成。

因此当前最准确的定位是：

```text
CAI = 可独立安装/引用的通用 AI 库雏形
  + 已完成 CabbageEditor adapter 解耦
  + 已具备 CAIApp/CAIRuntime facade
  - 尚未完成所有状态的 runtime scoped 隔离
```

如果目标是“给外部项目单实例调用”，当前形态已经基本可用；如果目标是“同一 Python 进程内多个项目、多套配置、多套工具/工作流互不污染”，还需要继续推进 runtime scoped registries 和显式插件化。

---

## 11. 项目现状分析与下一步

### 11.1 当前判断

项目已经完成从“插件内 AI 后端”到“通用库雏形”的关键跨越：前端有 request-aware AI client，AITool 主类已拆薄，CAI 有 `CAIApp/CAIRuntime` facade，CabbageEditor 能力已进入 adapter，CAI submodule 也具备独立安装和示例入口。此时继续堆叠新功能的收益低于清理兼容层、统一协议和补测试。

当前主要风险集中在四类：

- **运行时隔离不足**：默认 `CAIRuntime` 仍解析 legacy 全局 registry，多个 app/runtime 在同一进程内仍可能共享配置、工具、工作流、媒体和会话状态。
- **协议双轨并存**：新入口能识别 `data/heartbeat/done/error`，但 legacy `metadata.stream_done`、`metadata.heartbeat`、`error_code/status_info` 仍参与主链路。
- **取消与错误不可贯穿**：前端已有 `request.cancel` API，但取消信号尚未可靠传入 CAI generator、workflow、Agent streaming 和工具执行层；错误也尚未统一成可恢复/不可恢复的 envelope。
- **媒体路径仍偏重 base64 兼容**：大文件经 CEF/Python JSON 过桥成本高，后续应以 file id/path/url/resource handle 为主。

### 11.2 下一步优先级

1. **runtime scoped registries**：把 config/tool/workflow/media/conversation/model 从 `LazyRegistryRef` 指向的 legacy 全局对象迁入 `CAIRuntime` 实例。这是 CAI 从“可单实例复用”走向“可多实例隔离”的核心任务。
2. **统一 stream/error envelope**：把模型、工具、workflow、媒体解析、取消和内部异常统一成 `AIError` / `StreamEvent(event_type="error")`，同时保留 legacy 字段做过渡。
3. **真实 cancellation token**：让前端 cancel 传递到 AITool worker、CAI workflow、Agent streaming 和工具执行层，并补齐取消后的 done/cancelled 收尾语义。
4. **资源句柄优先的媒体入口**：优先支持 `file_id`、`file_path`、`file_url`，把 `data_url/base64` 降为兜底，并为大文件加大小限制和错误提示。
5. **显式插件化替代 import side effect**：逐个模块提供 `CAIPlugin.register(runtime)`，让 `LegacyModulePlugin` 只负责旧模块过渡。
6. **事件总线化前端接收**：保留 `window.receiveAIMessageChunk` 作为兼容入口，但内部只负责 dispatch，组件用订阅机制消费事件。
7. **补齐关键测试**：优先补 session concurrency、media resolve、workflow route、tool recoverable error 和独立库 CI smoke。

### 11.3 建议近期迭代顺序

第一轮建议聚焦协议和可观测性：统一 error envelope、补 request lifecycle 日志、补 session concurrency 和 tool error 测试。这一轮风险较低，却能显著提升调试效率。

第二轮推进 cancellation token 和媒体 resource handle。它们会跨前端、AITool、CAI 和工具层，适合在协议稳定后再动。

第三轮再处理 runtime scoped registries 和显式插件化。它们是通用库化的核心，但会触碰底层全局状态，最好在测试网铺好后逐步迁移。

---

## 12. AI 调用链路简化方案

可以简化，但不建议直接绕过 CEF/Python/插件体系。当前编辑器的前端运行在 CEF 中，Python 插件系统又承担页面注册、引擎能力访问和资源路径适配，因此完全砍掉这些边界会破坏现有架构。更现实的简化方向是：**保留宿主边界，压缩 AI 专属链路层数**。

### 12.1 早期链路的问题

早期 AI 调用链路中真正显得冗长的部分是：

```text
前端 aiService
  -> Bridge.callCEF(module/function/args)
  -> CoronaEditor.deal_func_from_js 反射分发
  -> AITool.send_message_to_ai_stream
  -> AITool 内部 event loop + thread queue
  -> get_ai_entrance().handle_integrated_entrance_stream
  -> CAI integrated stream handler
```

这里至少有三层职责混在一起：

- 通用 CEF RPC 分发：`Bridge.callCEF` 与 `CoronaEditor.deal_func_from_js`。
- 编辑器 AI 插件桥接：`AITool.send_message_to_ai_stream`。
- CAI 内部运行时：`ai_entrance`、integrated handler、workflow/Agent。

当前阶段已经完成入口收敛：前端新增 `aiClient.chatStream(request)`，AITool 新增 `ai_rpc(request)`，内部通过 `AIPluginController`、`AIRequestService`、`CAIClient` 和 `StreamDispatcher` 分层处理，CAI 调用入口也已收敛到 `CAIApp.chat_stream()`。旧链路仍作为兼容入口存在，但不再是新代码的目标形态。

简化时不需要把三层全部合并，而是让每层只保留一个明确入口。

### 12.2 推荐目标链路

推荐目标链路是：

```text
Vue AITalkBar
  -> aiClient.chatStream(request)
  -> CEF ai_rpc
  -> Python AITool.ai_rpc(request)
  -> CAIApp.chat_stream(request)
  -> StreamEvent
  -> aiClient.onStreamEvent(event)
```

对应关系：

| 当前层 | 简化后 |
| --- | --- |
| `aiService.sendMessageToAIStream(payload)` | `aiClient.chatStream(request)` |
| `{module,function,args}` AI 专用调用 | `AITool.ai_rpc(request)` |
| `send_message_to_ai_stream` + 手写 queue | `AIRequestService.start_stream(request)` |
| `get_ai_entrance().handle_integrated_entrance_stream` | `CAIApp.chat_stream(request)` |
| `receiveAIMessageChunk(string)` | `onStreamEvent(StreamEvent)` |

简化后的核心收益：

- 前端只知道 `chatStream/requestId/StreamEvent`。
- AITool 只负责接收请求、管理任务、转发事件。
- CAI 只暴露 `CAIApp.chat_stream()`，隐藏 `ai_entrance`、import side effect 和 integrated handler。
- stream 结束、心跳、错误、取消都变成统一事件，不再靠多个字段散落判断。

### 12.3 已完成：入口收敛

入口收敛阶段已经落地。该阶段没有大改 CAI 内部逻辑，而是通过兼容 facade 先把前端、AITool 和 CAI 的认知入口统一起来。

前端已新增：

```javascript
export const aiClient = {
  chatStream: (request) => Bridge.callCEF('AITool', 'ai_rpc', [request]),
  cancel: (requestId) => Bridge.callCEF('AITool', 'ai_rpc', [{
    operation: 'request.cancel',
    request_id: requestId,
  }]),
};
```

Python AITool 已新增：

```python
@classmethod
def ai_rpc(cls, request: dict) -> str:
    operation = request.get("operation")
    if operation == "chat.stream":
        return cls._request_service.start_stream(request)
    if operation == "request.cancel":
        return cls._request_service.cancel(request.get("request_id"))
    return build_rpc_error("UNKNOWN_OPERATION")
```

CAI 侧已通过 facade 包装 legacy integrated 入口：

```python
class CAIApp:
    def chat_stream(self, request):
        payload = request.to_legacy_payload()
        yield from get_ai_entrance().handle_integrated_entrance_stream(payload)
```

这一阶段的结果是新链路已经跑通，但底层仍复用旧 `handle_integrated_entrance_stream`。后续重点是逐步替换 legacy registry、legacy envelope 和 import side effect。

### 12.4 第二阶段：替换 AITool 手写流式队列

当前 AITool 用 `ThreadPoolExecutor` 跑 CAI generator，再用 `queue.Queue` 转给 asyncio loop。阶段 2 已先把这段逻辑拆成服务模块，底层流式桥接机制暂时保持不变。

建议抽成：

```text
AIRequestService
  -> 管理 request_id、状态、取消、future/task

CAIClient
  -> 消费 CAIApp.chat_stream
  -> 后续随 CAIApp 切换到 runtime scoped stream implementation

StreamDispatcher
  -> 专门把 StreamEvent 发回前端
```

已落地的中间形态是：

- `AIRequestService` 管理 `request_id`、状态查询、取消请求和 task 绑定。
- `MediaIngress` 处理现有 base64 图片上传与 token 提取。
- `CAIClient` 封装 CAI generator 到 bounded queue 的桥接，并提供 stop 信号避免提前结束时后台 worker 堵塞。
- `StreamDispatcher` 统一识别 `data/heartbeat/done/error` 并派发 JS 回调。
- `EventLoopRunner` 承接 AITool 原有 asyncio loop 线程、任务创建和 shutdown。
- `AIPluginController` 承接旧入口、新 `ai_rpc`、流式消费、错误转发和 cleanup 编排。
- `LocalFileService` 承接 `read_local_file_as_base64` 的文件读取与 data URL 编码。

当前 AITool 主类已收敛为 CEF 暴露方法的薄委托层：

```python
class AITool(PluginBase):
    @classmethod
    def ai_rpc(cls, request):
        return cls.controller.handle(request)
```

### 12.5 第三阶段：CAI 内部入口简化

CAI 内部可以把当前：

```text
ai_entrance
  -> handle_integrated_entrance_stream
  -> handle_integrated_entrance_stream_inner
  -> workflow or agent
```

收敛为：

```text
CAIApp.chat_stream
  -> IntegratedRuntime.stream
  -> WorkflowRouter.try_route
  -> AgentRuntime.stream
```

保留旧入口：

```python
@register_entrance(handler_name="handle_integrated_entrance_stream")
def handle_integrated_entrance_stream(payload):
    yield from get_default_app().chat_stream(ChatRequest.from_legacy(payload))
```

这样外部新代码走 `CAIApp`，旧模块仍可继续走 `ai_entrance`。

当前已落地的阶段 3 中间形态是：

- 在 `CoronaArtificialIntelligence/cai` 下新增 `CAIApp`、`CAIRuntime` 和 `protocol` 包。
- `CAIApp.chat_stream(request)` 接受 `ChatRequest` 或 legacy dict，并内部转成旧 integrated payload。
- `CAIRuntime` 通过 lazy registry ref 暴露 config/tool/workflow/media/conversation/model 等现有 registry。
- `ai_service.entrance.get_ai_entrance()` 改为通过默认 `CAIRuntime` 返回 legacy entrance。
- AITool 的 `CAIClient` 已改为消费 `CAIApp.chat_stream()`，不再直接持有 `get_ai_entrance()`。

这一版仍是兼容 facade，不是最终 runtime 隔离：底层 registry 仍来自现有全局单例，后续阶段需要把这些 registry 的创建和写入真正迁到 `CAIRuntime` 实例上。

### 12.5.1 第四阶段：插件加载显式化

阶段 4 已把旧的模块加载编排从 `ai_service.entrance.reimport()` 中移入 `cai.plugins.PluginManager`：

- `CAIPlugin` 定义了插件对象的最小协议：`name/enabled/register(runtime)`。
- `ModulePluginSpec` 从 `module_settings.yaml` 读取模块 manifest。
- `LegacyModulePlugin` 按现有约定导入 `configs/settings.py`、`base.py`、`tools/loader.py`，继续触发旧装饰器注册。
- `PluginManager.load_module_settings(...)` 统一处理 enabled/disabled、加载统计、失败统计，并写入 `runtime.metadata`。
- `register_entrance(...)` 仍会写 legacy `ai_entrance` 静态方法，同时也写入 `CAIRuntime.entrance_handlers`。

这一阶段没有要求每个旧模块立刻改成独立插件类，因此风险较低。后续可以逐个模块把 import side effect 迁移为显式 `register(runtime)`，最终让 `LegacyModulePlugin` 只作为兼容层存在。

### 12.6 不建议的简化方式

以下方式不建议：

- **前端直接调用 CAI**：前端运行在 CEF 页面中，无法安全直接访问 Python runtime、文件系统、引擎工具和模型密钥。
- **绕过 PluginBase**：会破坏当前页面注册、dock 管理和插件生命周期。
- **把 CAI submodule 移出 Editor**：会破坏 submodule 管理和当前运行时路径假设。
- **一次性删除 `ai_entrance`**：现有模块依赖装饰器注册和动态加载，应先通过 `CAIApp` 兼容代理逐步替换。

### 12.7 已落地的最小版本

最小改造已落地，核心包括四件事：

1. 前端新增 `aiClient.chatStream(request)`，保留旧 `aiService.sendMessageToAIStream(payload)`。
2. AITool 新增 `ai_rpc(request)`，并委托 `AIPluginController` / `AIRequestService` 管理 request lifecycle。
3. 每个请求生成 `request_id`，并把它透传到 metadata。
4. 前端 `receiveAIMessageChunk` 兼容读取 `metadata.request_id`，按 request 归属消息。

后续不再是“让新入口跑起来”，而是继续消除兼容层：把旧全局 registry 迁到 `CAIRuntime` 实例，把 legacy module import side effect 改为显式 plugin register，并让 stream event、错误和取消全部走统一协议。
