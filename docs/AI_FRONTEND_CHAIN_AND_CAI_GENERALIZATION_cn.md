# 前端调用 AI 链路与 CAI 通用库化方案

> **创建日期**: 2026年5月7日  
> **适用范围**: CabbageEditor 前端、CEF/Python 桥接、AITool 插件、CoronaArtificialIntelligence（CAI）  
> **目标**: 梳理当前从前端调用 AI 的完整链路，识别可优化点，并给出将 CAI 演进为通用 AI 库的开发方案。

---

## 1. 总览

当前 AI 能力由 CabbageEditor 前端触发，通过 CEF `window.cefQuery` 进入 C++，再调用 Python 编辑器核心，最终由 AITool 插件调用内嵌的 CAI 库完成模型、Agent、工具和工作流执行。返回结果采用“前端发起请求 + Python 主动执行 JS 回调”的流式模式。

当前链路可以概括为：

```text
Vue AITalkBar
  -> bridge.js / window.cefQuery
  -> C++ CEF MessageRouter
  -> Python CoronaEditor.deal_func_from_js
  -> AITool.send_message_to_ai_stream
  -> CAI ai_entrance.handle_integrated_entrance_stream
  -> workflow route / LangChain Agent / tools / media registry
  -> CAI stream chunk
  -> CoronaEditor.js_call_func
  -> C++ execute_javascript
  -> Vue window.receiveAIMessageChunk
```

当前 CAI 仍然更像“插件内的 AI 后端”，而不是独立可复用库。由于 `CoronaArtificialIntelligence` 是 Editor 的 submodule，通用库化不应移动它的物理目录；关键是保持 submodule 位置不变，在内部建立稳定 API、runtime 边界和宿主适配边界。

---

## 2. 当前调用链路详解

### 2.1 前端输入层

入口页面为 `Frontend/src/views/sidebar/AITalkBar.vue`。

主要职责：

- 维护聊天消息列表、发送状态、流式状态、审核面板状态。
- 将用户输入拆分为文本 part、slash command part、图片 part。
- 生成并维护 `session_id`。
- 调用 `aiService.sendMessageToAIStream(payload)` 发送消息。
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

`Bridge.callCEF(moduleName, methodName, args)` 将请求转换为：

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

这个调用只代表“请求已交给 Python 侧”，不代表 AI 生成已经完成。AI 流式结果不通过 `onSuccess` 返回，而是通过后续 JS 回调进入 `receiveAIMessageChunk`。

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

AITool 当前承担以下职责：

- 安装 `cai_extensions`，向 CAI 注入 CabbageEditor 专属路径、工具和工作流。
- 启动独立 asyncio event loop。
- 使用 `ThreadPoolExecutor` 在线程池中运行 CAI 的同步 generator。
- 将 CAI chunk 转换为 JS 回调。
- 处理图片 base64 上传、token 透传和错误响应。

流式处理的核心流程：

```text
send_message_to_ai_stream(ai_message)
  -> ensure_loop_running()
  -> _process_ai_message_stream(ai_message)
  -> json.loads(ai_message)
  -> upload image if needed
  -> get_ai_entrance().handle_integrated_entrance_stream(payload)
  -> for chunk in generator: queue.put(chunk)
  -> async loop consumes queue
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

- 前端发送入口确认为 `aiService.sendMessageToAIStream(payload)`，其内部调用 `Bridge.callCEF('AITool', 'send_message_to_ai_stream', [payload])`。
- `AITalkBar.vue` 当前确实构造 `session_id`、`llm_content[].part[]` 和 `metadata`；图片 part 目前包含 `content_url`、`content_path`、`content_text` 和 `parameter`。
- `CoronaEditor.deal_func_from_js` 当前确实按 `{module, function, args}` 反射分发，并通过 `create_success_response` / `create_error_response` 返回 CEF 请求结果。
- AITool 当前确实在线程池中同步消费 `get_ai_entrance().handle_integrated_entrance_stream(payload)`，再通过 `CoronaEditor.js_call_func('/AITalkBar', 'receiveAIMessageChunk', [result])` 回调前端。
- CAI integrated 入口当前确实通过 `session_concurrency` 做同一会话并发保护，并由 `handle_integrated_entrance_stream_inner` 优先路由 workflow，未命中时再走 Agent。
- CAI 当前响应 envelope 使用 `session_id`、`error_code`、`status_info`、`llm_content`、`metadata`；`stream_done` 和 `heartbeat` 仍通过 `metadata` 表达，新 `event_type` 是迁移目标而非现状。
- workflow 执行器还会发送带 `metadata.workflow_node_boundary` 的 heartbeat，前端当前会据此结束当前流式气泡的等待态。
- 前端除 `window.receiveAIMessageChunk` 外仍保留 `window.receiveAIMessage` 兼容旧非流式响应；主链路当前走流式 chunk。
- `CoronaEditor.js_call_func` 当前通过拼接 JS 字符串调用 `window.<function_name>(...)`，因此函数名仍是字符串级约定，不是类型化事件通道。
- `request_id`、`ai_rpc`、`CAIApp`、`CAIRuntime`、runtime scoped registry、事件总线化前端接收等内容是本方案建议，当前尚未实现。

---

## 3. 当前链路中的主要问题

### 3.1 RPC 协议过于松散

前端向 Python 发送的是通用 `{module, function, args}`。这种方式简单，但存在问题：

- 无正式 schema，参数错误只能运行时发现。
- Python 侧直接反射调用，缺少权限边界。
- AI 请求和普通 UI 请求混用同一套弱类型通道。
- 错误码、异常类型、超时语义不统一。

### 3.2 流式请求缺少 request_id

当前有 `session_id`，但没有独立的 `request_id`。这会导致：

- 多轮请求并发时，前端难以准确归属 chunk。
- 只能依赖“最后一条用户消息”更新状态。
- 取消、重试、恢复、日志追踪都缺少稳定键。

### 3.3 请求返回与 AI 结果返回是两套语义

`Bridge.callCEF(...send_message_to_ai_stream...)` 的成功只表示 Python 已接收请求。真正 AI 结果通过 `execute_javascript` 回调。

这本身可以接受，但需要明确建模为：

- `accepted`: 请求已进入后端队列。
- `stream_event`: 后续流式事件。
- `done`: 请求完成。
- `error`: 请求失败。
- `cancelled`: 请求取消。

当前代码没有显式区分这些阶段。

### 3.4 AITool 职责偏重

AITool 同时承担宿主桥接、异步调度、图片上传、token 处理、CAI 调用、JS 回调等职责，容易让插件层变成新的“大对象”。

建议拆分为：

- `AIPluginController`: 暴露给 CEF 的插件 API。
- `AIRequestService`: 处理 request lifecycle。
- `CAIClient`: 调用 CAI runtime。
- `StreamDispatcher`: 负责把 stream event 派发回前端。
- `MediaIngress`: 负责文件/base64/path 进入媒体仓库。

### 3.5 CAI 依赖全局单例和 import side effect

当前 CAI 使用：

- `ai_entrance.collector` 全局配置收集器。
- `get_ai_config()` 模块级缓存。
- `WorkflowRegistry` 全局单例。
- tool registry、media registry、conversation store 等全局对象。
- 通过 import 模块触发装饰器注册。
- 修改 `sys.path` 解决内部绝对 import。

这些设计在插件原型阶段效率很高，但作为通用库会带来问题：

- 同一进程难以创建多个独立 AI runtime。
- 测试隔离困难。
- 宿主无法明确控制生命周期。
- 外部集成者难以理解哪些 import 会产生副作用。
- 配置热重载、插件卸载、工作流覆盖容易互相污染。

### 3.6 宿主专属逻辑仍贴近 CAI 通用核心

`cai_extensions` 已经把 CabbageEditor 相关能力集中起来，这是正确方向。但目前它仍然通过安装阶段修改路径、预加载模块、注册工作流来影响 CAI 全局状态。

理想状态是：

```text
CAI 通用核心不知道 CabbageEditor
CabbageEditor adapter 持有 CAI runtime 实例并向其注册能力
```

### 3.7 大文件通过 base64 过桥效率较低

图片当前可在前端转成 base64，再穿过 CEF 和 Python。对于大图、视频、音频、3D 文件，这会导致：

- JS 内存占用增加。
- JSON payload 变大。
- CEF/Python 边界复制成本增加。
- 日志误打印时风险变高。

应优先使用路径、文件 ID、临时资源句柄或宿主文件选择结果。

### 3.8 已发现的小型实现不一致

`Frontend/src/utils/bridge.js` 中 `aiService.readLocalFileAsBase64` 当前写法是：

```javascript
readLocalFileAsBase64: (filePath) =>
  Bridge.callCEF('AITool', 'read_local_file_as_base64', filePath),
```

而 `Bridge.callCEF` 期望第三个参数是数组，并且 Python 分发层会执行 `getattr(module, func_name)(*args)`。如果这里传入字符串，Python 侧可能按字符展开参数。建议改为：

```javascript
readLocalFileAsBase64: (filePath) =>
  Bridge.callCEF('AITool', 'read_local_file_as_base64', [filePath]),
```

这不是通用库化的主线问题，但属于当前桥接层需要一并修正的参数形态问题。

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

---

## 5. CAI 通用库化目标架构

本方案默认 **不移动** `editor/CabbageEditor/plugins/AITool/CoronaArtificialIntelligence` 目录。CAI 继续作为 Editor 下的 submodule 存在，通用库化通过内部 API、运行时实例化和宿主适配解耦完成。

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
editor/CabbageEditor/plugins/AITool/
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

- 可以在 `editor/CabbageEditor/plugins/AITool/CoronaArtificialIntelligence` 目录执行 editable install 或直接以 submodule 方式被外部项目引用。
- 可以在编辑器外用 Python 脚本调用 `CAIApp.chat_stream()`。

实施说明：

- `CoronaArtificialIntelligence/pyproject.toml` 使用 setuptools 原地打包 submodule，安装包名为 `corona-artificial-intelligence`，导入包名为 `CoronaArtificialIntelligence`。
- Editor 侧代码也按该导入名引用 CAI，即 `from CoronaArtificialIntelligence.cai import CAIApp`，从而和编辑器外使用方式保持一致。
- optional dependencies 已按能力拆为 `langchain`、`workflow`、`media`、`cabbage`、`web`、`object-recognition` 和 `all`；其中 `cabbage` 保持为空，因为 CabbageEditor adapter 位于 submodule 外侧的 `plugins/AITool/cai_extensions`。
- 新增 console script `cai-chat`，入口为 `CoronaArtificialIntelligence.cai.cli:main`。
- 新增 `examples/cli_chat.py` 与 `examples/fastapi_websocket.py`，用于演示编辑器外直接调用 `CAIApp.chat_stream()`。
- 新增 `docs/API_REFERENCE.md`，记录 `CAIApp`、`CAIRuntime`、`ChatRequest`、`StreamEvent` 与 plugin API。

---

## 7. 推荐任务拆分

### 7.1 前端任务

- [x] 新增 `aiClient.chatStream`、`cancelRequest`、`getRequestStatus`，保留旧 `aiService`。
- [x] 引入 `request_id`。
- [x] `messages` 改为 request-aware 数据结构。
- [ ] 把 `window.receiveAIMessageChunk` 降级为事件总线入口。
- [ ] 增加请求取消按钮和超时状态展示。
- [ ] 媒体输入优先传 path/resource，而不是 base64。

### 7.2 Python AITool 任务

- [x] 新增 `ai_rpc` 统一入口。
- [x] 新增 request lifecycle registry。
- [x] 新增 bounded stream queue。
- [ ] 支持 cancellation token。
- [x] 拆分 media ingress、stream dispatcher、CAI client。
- [ ] 统一错误 envelope。

### 7.3 CAI 通用核心任务

- [x] 定义 `ChatRequest`、`StreamEvent`、`AIError`。
- [x] 新增 `CAIApp` facade。
- [x] 新增 `CAIRuntime`。
- [x] runtime 挂载 config/tool/workflow/media/conversation registry 引用。
- [x] 新增 `CAIApp.chat_stream` 兼容包装 `handle_integrated_entrance_stream`。
- [x] 建立 plugin register 机制，并在阶段 4 补齐显式 `CAIPlugin` 协议。
- [x] 新增 `PluginManager` 和 `LegacyModulePlugin`，接管 `module_settings.yaml` 的模块加载编排。

### 7.4 CabbageEditor adapter 任务

- [x] 将 `cai_extensions.install()` 改造成 `install(app, context)`，并保留无参兼容入口。
- [x] 路径 provider 改为 runtime scoped capability（legacy 全局 setter 暂保留兼容）。
- [x] engine tools 注册到 runtime scoped tool registry。
- [x] workflow 注册到 runtime scoped workflow registry。
- [x] 删除 adapter import-time `sys.path` 副作用。
- [x] 删除 legacy 绝对 import 对显式 `bootstrap_paths()` 的兼容依赖。

### 7.5 测试任务

- [x] 协议解析测试。
- [x] stream done/heartbeat 测试。
- [x] request cancel 测试。
- [ ] session concurrency 测试。
- [ ] media fileid resolve 测试。
- [ ] workflow route 测试。
- [ ] tool recoverable error 测试。
- [x] Cabbage adapter smoke test。
- [x] CAI core 独立 import smoke test。

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
- [x] AITool 主类只负责 CEF 暴露，不承载大量业务逻辑。

CAI 通用库化阶段完成后，应满足：

- [x] 可以在无 CabbageEditor 环境下 import CAI 通用核心。
- [x] 可以创建多个注入式 CAIApp facade 实例。
- [ ] 工具、工作流、媒体仓库、会话存储属于 runtime 实例。
- [x] CabbageEditor 能力通过 adapter 注册。
- [x] 旧 `get_ai_entrance()` 兼容入口仍可工作。
- [x] 有最小 CLI 或脚本示例证明 CAI 可独立使用。

---

## 11. 推荐优先级

建议按以下顺序推进：

1. **request_id 全链路透传**：收益最大，风险最低。
2. **AI RPC Envelope**：让请求/响应语义稳定。
3. **AITool 内部拆分**：降低插件维护成本。
4. **CAIApp facade**：给通用库化建立稳定入口。
5. **runtime scoped registries**：解决全局单例和测试隔离。
6. **cai_extensions adapter**：在保留目录位置的前提下，把宿主能力从 CAI 通用核心中彻底分离。

这条路线可以在不打断当前编辑器功能的前提下，让 CAI 逐步从插件内核演进为通用 AI runtime。

---

## 12. AI 调用链路简化方案

可以简化，但不建议直接绕过 CEF/Python/插件体系。当前编辑器的前端运行在 CEF 中，Python 插件系统又承担页面注册、引擎能力访问和资源路径适配，因此完全砍掉这些边界会破坏现有架构。更现实的简化方向是：**保留宿主边界，压缩 AI 专属链路层数**。

### 12.1 当前链路的问题

当前 AI 调用链路中真正显得冗长的部分是：

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

### 12.3 第一阶段：只做入口收敛

第一阶段不要改 CAI 内部逻辑，只增加一层兼容 facade。

前端新增：

```javascript
export const aiClient = {
  chatStream: (request) => Bridge.callCEF('AITool', 'ai_rpc', [request]),
  cancel: (requestId) => Bridge.callCEF('AITool', 'ai_rpc', [{
    operation: 'request.cancel',
    request_id: requestId,
  }]),
};
```

Python AITool 新增：

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

CAI 侧先不大改，只包一层：

```python
class CAIApp:
    def chat_stream(self, request):
        payload = request.to_legacy_payload()
        yield from get_ai_entrance().handle_integrated_entrance_stream(payload)
```

这一阶段的目标是让新链路跑起来，但底层仍复用旧 `handle_integrated_entrance_stream`。

### 12.4 第二阶段：替换 AITool 手写流式队列

当前 AITool 用 `ThreadPoolExecutor` 跑 CAI generator，再用 `queue.Queue` 转给 asyncio loop。阶段 2 已先把这段逻辑拆成服务模块，底层流式桥接机制暂时保持不变。

建议抽成：

```text
AIRequestService
  -> 管理 request_id、状态、取消、future/task

CAIClient
  -> 当前消费 get_ai_entrance().handle_integrated_entrance_stream
  -> 后续切换到 CAIApp.chat_stream

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

### 12.7 最小可落地版本

最小改造可以只做四件事：

1. 前端新增 `aiClient.chatStream(request)`，保留旧 `aiService.sendMessageToAIStream(payload)`。
2. AITool 新增 `ai_rpc(request)`，内部暂时仍调用旧 `_process_ai_message_stream`。
3. 每个请求生成 `request_id`，并把它透传到 metadata。
4. 前端 `receiveAIMessageChunk` 先兼容读取 `metadata.request_id`，按 request 归属消息。

这个版本不会动 CAI 内部，只先缩短前端和插件之间的认知链路。等稳定后，再把 `CAIApp.chat_stream()` 和 runtime scoped registry 往里推进。