# AI 生成链路协程化与资源可控优化计划

## Summary

将当前图片/模型生成从多个线程并发执行完整任务，改为一个专用调度线程加 asyncio 协程队列。目标是在保持较高网络并发的同时，降低线程、CPU、磁盘和内存占用，并为用户介入、暂停、取消、改提示词、调整优先级提供统一基础。

核心原则：

- 只允许一个 AI 任务调度线程。
- 不使用生成线程池，不新开后台下载线程，不新开进程。
- 高并发只用于网络 I/O：提交、轮询、下载。
- 本地重资源阶段低并发或串行：后处理、文件写入、模型导入、Actor 创建。
- 所有任务状态集中在调度器内，UI/LANChat 通过命令队列介入。

## Architecture

新增或扩展 `GenerationScheduler`，复用现有 `event_loop_runner` 的单线程 asyncio event loop。

调度器负责：

- 管理每个 `session_id` 的生成状态。
- 管理图片生成、模型生成、下载、导入任务。
- 提供同步兼容入口，供现有同步工作流节点调用。
- 提供控制入口：暂停、恢复、取消、跳过、修改 prompt、调整优先级。

必须避免死锁：

- 非调度线程可以通过 `run_sync()` 等待结果。
- 调度线程内部不能阻塞等待自身 future。
- 调度线程内只能 `await`。

## Stage Model

把模型生成拆成阶段：

1. `prepare`
   - 整理 prompt。
   - 查缓存。
   - 检查本地模型库。

2. `submit`
   - 提交远端生成任务。
   - 使用低并发限制。

3. `poll`
   - 轮询远端任务状态。
   - 使用高并发限制。
   - 不能长期占用 submit token。

4. `download`
   - 下载模型、预览图、贴图等资源。
   - 使用中等并发限制。

5. `postprocess`
   - 解压、整理目录、写入本地库。
   - 使用低并发限制。

6. `import`
   - 导入引擎。
   - 创建 Actor。
   - 写场景状态。
   - 必须串行或严格低并发。

建议默认并发：

- 图片提交：`4`
- 模型提交：`2`
- 模型轮询：`32`
- 下载：`4`
- 后处理：`1`
- 引擎导入：`1`

## Required Refactors

### 图片生成

替换 `generate_images.py` 中的 `ThreadPoolExecutor`。

改为：

- 每张图作为 scheduler coroutine。
- 图片请求异步提交。
- 图片下载进入统一 download queue。
- 本地图库写入受写入限流保护。

### 模型生成

替换 `model_retrieval_workflow/generate.py` 中的 `ThreadPoolExecutor/as_completed`。

改为：

- 每个模型生成项进入 scheduler。
- `generate_single_item()` 拆为 async 阶段。
- six-view capture 不再使用独立 worker thread，改为低优先级 scheduler task。

### Hunyuan/Rodin Client

将同步 HTTP 调用改为真正 async：

- `httpx.Client` 改为 `httpx.AsyncClient`。
- `threading.BoundedSemaphore` 改为 `asyncio.Semaphore`。
- `time.sleep()` 改为 `await asyncio.sleep()`。
- 后台 daemon 下载线程改为 scheduler download queue。

### 下载链路

所有模型、贴图、预览图、six-view 资源下载统一进入 scheduler。

禁止：

- 单个模型生成完成后新开后台下载线程。
- 批量下载使用固定 `ThreadPoolExecutor(max_workers=8)`。
- 取消任务后下载仍继续运行。

## User Intervention

每个生成项维护状态：

- `queued`
- `waiting_user`
- `submitting`
- `polling`
- `downloading`
- `postprocessing`
- `importing`
- `done`
- `failed`
- `cancelled`
- `abandoned`

支持介入点：

- 提交前：修改 prompt、取消、跳过。
- 轮询中：取消本地等待。
- 下载前：取消下载或降低优先级。
- 导入前：确认、替换资源、取消导入。
- 批次中：暂停或恢复整个 session。

远端服务如果不支持 cancel API：

- 本地任务标记为 `abandoned`。
- 后续远端结果忽略。
- 不下载、不导入、不写场景。

## Resource Controls

新增配置项，优先读取环境变量，其次读取 AI settings：

- `CORONA_AI_IMAGE_SUBMIT_CONCURRENCY`
- `CORONA_AI_MODEL_SUBMIT_CONCURRENCY`
- `CORONA_AI_MODEL_POLL_CONCURRENCY`
- `CORONA_AI_DOWNLOAD_CONCURRENCY`
- `CORONA_AI_IMPORT_CONCURRENCY`
- `CORONA_AI_QUEUE_LIMIT`

需要队列背压：

- 单 session 最大排队数量。
- 全局下载队列最大等待数量。
- 超限时任务保持排队或返回资源等待状态，不能无限提交。

## Risk Controls

必须规避以下问题：

- 不能用 `asyncio.to_thread()` 包装整段同步生成逻辑作为主方案。
- 不能让远端 submit 无限并发。
- poll 阶段不能占用 submit token。
- 不能在调度线程中同步等待自身 future。
- 引擎写入必须串行。
- UI/LANChat 不能直接修改任务对象。
- 取消后的任务不能继续下载、导入或创建 Actor。
- 后台 daemon 下载线程必须移除。

## Test Plan

### Unit Tests

- 调度器只启动一个线程。
- 高并发 poll 不增加工作线程数量。
- submit token 在进入 poll 后释放。
- cancel 后不会进入 download/import。
- pause 后不会推进新阶段。
- `run_sync()` 不会在调度线程内死锁。
- import 阶段严格串行。

### Fake Provider Tests

- 模拟 50 个远端任务长轮询，线程数保持稳定。
- 模拟下载慢、失败、重试、取消。
- 模拟远端任务完成但本地已取消，结果被忽略。
- 模拟用户在 queued 阶段修改 prompt，提交使用新 prompt。

### Static Guards

- 生成主链路禁止 `ThreadPoolExecutor`。
- 下载链路禁止新建 daemon `threading.Thread`。
- 生成链路禁止 `time.sleep()`。
- Hunyuan/Rodin 主请求路径必须使用 async HTTP client。
- 引擎导入必须经过串行 gate。

### Manual Acceptance

- 批量生成 20 张图，UI 不冻结，线程数稳定。
- 批量生成 10 个模型，远端可并行等待，本地下载和导入不过载。
- 生成中暂停后，不继续进入后续阶段。
- 生成中取消后，不出现迟到导入。
- 修改排队中 prompt 后，生成使用新 prompt。
- LANChat agent 任务同时运行时，聊天室和网络协同不被生成任务拖慢。

## Assumptions

- 允许一个专用 AI 调度线程。
- 不新增进程。
- 不新增生成线程池。
- 远端取消是 best-effort，本地取消以 abandoned/ignore late result 实现。
- 旧同步工作流节点短期保留，但只能通过 scheduler 兼容入口调用。
- 本轮优先解决资源可控和用户介入，不重写完整 Agent 架构。