### 自然语言驱动的 3D 场景自动生成与组装引擎 &emsp;&emsp; 2025.05-至今

**项目描述**：3D 编辑器通过自然语言生成室内场景时，存在单次 LLM 布局出错率高、多场景串行耗时过长的问题。基于 LangGraph 构建从场景分析、3D 模型生成到智能组装的全自动管线，实现"输入文字需求 → 输出可编辑 3D 场景"的端到端能力。

**技术实现**：LangGraph StateGraph 串联三阶段 DAG（multi_scene → model_retrieval → scene_composition），支持 Checkpoint 节点级断点恢复与审核回环路由；多场景并行采用两阶段分治——IO 密集型模型生成用 ThreadPoolExecutor + BoundedSemaphore 并发控制，GPU 密集型导入串行防 Vulkan 溢出；Hunyuan3D API 集成（ImageBase64 格式适配、PBR 四通道材质管线），object_id 语义化目录缓存实现跨运行模型复用；DeepSeek V4 Pro 驱动智能布局，object_id 精确匹配 + 索引回退兜底 LLM 输出不稳定。

**量化成果**：单场景端到端生成可用；多场景并行 3 路耗时从串行 750s 降至约 325s（提效 57%）；模型缓存命中跳过 API 调用，单次节省 3-5 分钟；布局匹配率从 LLM 裸输出 60% 提升至 100%（精确匹配 + 回退兜底）。
