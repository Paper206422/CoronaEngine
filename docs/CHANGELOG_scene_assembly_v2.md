# 场景组装 Agent v2 — 变更清单

> 分支: `feature/scene-assembly-v2`
> 日期: 2026-06-08 ~ 2026-06-11
> 提交: `07d7f8d9` (室内盒子测试第一版)

---

## 一、概述

本次开发在 LANChat 聊天室内集成了完整的 **场景组装 Agent 系统**，实现「自然语言 → 方案规划 → 3D 物体建模 → 智能布局 → 场景组合」的端到端能力。

核心链路：
```
用户在 LANChat 聊天室说"生成欧式卧室"
  → 意图分类 + 场景组合检测
  → 提取物体清单（LLM + 黑名单过滤）
  → 文生图 → 图生3D（Hunyuan3D）→ 模型下载
  → 生成整体房间盒子（半透明六面体）
  → LLM 智能布局（AABB 真实尺寸辅助）
  → import_to_engine 批量导入
  → 受控物理沉降 + 位置钳制 + 地面整平
  → 房间盒子碰撞约束，物体整齐摆放
```

---

## 二、新增文件（17 个）

### Agent 系统（14 个，`editor/plugins/AITool/cai_extensions/agent/`）

| 文件 | 职责 |
|------|------|
| `__init__.py` | 场景组装 LangGraph workflow 注册（`/sc_agent`） |
| `agent_adapter.py` | **MasterAgent** — 统一入口，接管 LANChat 全部 AI 能力（聊天/场景编辑/讨论总结/风格巡检/场景组合）。路由分流：builtin / scene / compose / chat，包含 SSL 友好降级 + 布局上下文拼接 |
| `coordinator.py` | 编排引擎：intent → style → spatial → validate → execute。含 Self-Reflection、歧义候选选项、记忆增强（连续操作主动询问） |
| `intent_agent.py` | 意图理解（LLM + 关键词回退），解析 action/target/parameters |
| `spatial_agent.py` | 空间推理：Constraint Solver（复用 v2）+ CoT 5 步推理 + 碰撞检测偏移 |
| `style_agent.py` | 风格预检：关键词 + LLM 双重校验，含 4 套内置 Style Bible |
| `group_agent.py` | 群 Agent：讨论总结（共识计算 + Style Bible 生成）+ 风格巡检 |
| `memory.py` | L1/L2 记忆系统（SessionMemory + SceneMemory），进程级单例持久，支持 `find_similar_operations` 连续操作推断 |
| `event_bus.py` | 事件总线（asyncio.Queue），pub/sub/replay 模式 |
| `collaboration.py` | 多人协同管理：物体锁 + 意图预览 + 冲突检测 |
| `multi_step_planner.py` | 复杂任务分解（LLM + 规则回退），支持逐步执行 |
| `model_provider.py` | 3D 模型获取器：搜索本地库 → Hunyuan3D 生成 → 等待 mesh 下载，全程 verbose 日志 |
| `scene_composer.py` | **场景组合器**：清单提取 → 批量建模(复用 model_retrieval workflow) → 整体盒子生成 → 布局(复用 compose_scene) → 导入 → 物理沉降+钳制+整平 |
| `test_agent.py` | Agent 单元测试 |

### LANChat 扩展（3 个，`editor/plugins/LANChat/server/`）

| 文件 | 职责 |
|------|------|
| `scene_import_helper.py` | 3D 生成完成后自动导入引擎（检测混元模型目录 → 等 mesh 就绪 → import_model） |
| `intent_classifier.py` | 每条消息的意图判别器（规则优先 + LLM 兜底），判别 execute/summarize/none |
| `plan_session.py` | Plan 协商状态机：讨论 → Plan 协商 → 定稿。支持静默累积 + 适当时机输出 + 停顿检测 |

---

## 三、修改文件（7 个）

### `editor/plugins/AITool/cai_extensions/flows/scene_composition_workflow/compose_scene.py`
- **AABB 注入 LLM 布局**：`_build_layout_user_prompt` 新增 `asset_metadata` 参数，物体列表注入真实尺寸 + 放置类型
- `_match_meta_by_path` 辅助函数：用 local_path 文件名 stem 匹配 AABB 数据
- `compose_scene_node` 从 `intermediate.asset_metadata` 取出并传入布局

### `editor/plugins/AITool/cai_extensions/register.py`
- 注册 agent workflow（`.agent` 加入 `flow_modules`）

### `editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/constants.py`
- `GENERATION_MAX_WORKERS` 3→1（串行避免渲染线程死锁）

### `editor/plugins/AITool/cai_extensions/flows/model_retrieval_workflow/six_view_capture_tool.py`
- 六视图 → 四视图（删 `top`/`bottom`，保留 `front/back/left/right`）

### `editor/plugins/AITool/utils/ai_setting.py`
- Hunyuan3D API key 更换

### `editor/plugins/LANChat/main.py`
- `_make_agent_ai_chat` 重写：接入 MasterAgent + fallback_chat（含 JSON 流式解析 + SSL 网络重试 + 友好降级）
- `_make_summary_ai_chat` 重写：接入 SummaryAgent + JSON 解析
- `send_message` 房主路径增加 `_dispatch_mentions` 调用（修复房主发消息不触发 Agent）
- 场景最大物体数可配（`scene_max_items`，默认 8）

### `editor/plugins/LANChat/server/chat_server.py`
- `_dispatch_mentions` 增强：隐式指令检测（无 @ 也触发 agent）+ 场景组合/生成关键词
- `_classify_and_react`：每条消息主动判别是否需要执行/总结
- `_auto_import_models`：检测 agent 回复中的模型目录，等 mesh 就绪后自动导入引擎
- `_is_implicit_agent_command`：规则判别是否需要 agent 介入
- `_extract_model_dirs`：从回复中提取混元模型目录路径
- `_maybe_compress` 增强：无场景指令时广播摘要 + 摘要后询问是否执行
- 房间盒子检测 + 场景框架支持

---

## 四、核心能力矩阵

### 场景编辑
| 能力 | 触发 | 状态 |
|------|------|------|
| 单步添加/删除/移动/修改 | `@小黄 加个台灯` 或隐式触发 | ✅ |
| Multi-Step 复杂分解 | "把酒吧布置得更有氛围感" | ✅ |
| **场景组合** | "生成欧式卧室" / "按清单生成" | ✅ |
| CoT 空间推理 | 自动触发 | ✅ |
| Self-Reflection 质量检查 | 自动触发 | ✅ |
| 歧义候选选项 | 低置信度时 | ✅ |

### 3D 生成与组装
| 能力 | 说明 | 状态 |
|------|------|------|
| 文生图 → 图生3D | 复用 model_retrieval workflow | ✅ |
| 混元 Hunyuan3D | text_to_3d / image_to_3d | ✅ |
| 模型搜索复用 | 向量库检索已生成模型 | ✅ |
| **整体房间盒子** | 单个六面体 OBJ，撑不开 | ✅ |
| LLM 智能布局 + AABB | 真实尺寸 + 放置类型辅助 | ✅ |
| 受控物理沉降 | 关→回设原位→开 0.6s→关 | ✅ |
| 位置钳制 | X/Y/Z 越界强制拉回盒内 | ✅ |
| 地面整平 | AABB 高度 → 底部贴地 Y=0 | ✅ |
| 3D 生成完自动导入引擎 | 检测回复中的模型路径 → 导入 | ✅ |
| 物体数量上限 | 默认 8 个 | ✅ |

### 群协作
| 能力 | 触发 | 状态 |
|------|------|------|
| 讨论总结 + 共识计算 | `/总结` / LLM 判别 | ✅ |
| 风格巡检 | `/检查` | ✅ |
| Plan 协商状态机 | "执行" → plan v1 → 修订 → 定稿 | ✅ |
| 意图判别（每条消息） | 规则 + LLM 兜底 | ✅ |
| 自动摘要（定量兜底） | 40 条触发 | ✅ |

---

## 五、设计原则

1. **复用原 workflow，不重复造轮子**：模型检索用 `model_retrieval_workflow`，布局用 `compose_scene`，导入用 `import_to_engine`，物理沉降用 `_apply_physics_settlement`（v2）
2. **只改 SceneComposer，不动原 workflow**：所有组装定制逻辑集中在 `scene_composer.py`，原上下游 workflow 零改动
3. **友好降级**：LLM 失败 → 规则兜底；网络错误 → 重试 + 友好提示；工具不可用 → 回退单步执行

---

## 六、已知限制

1. **DMXAPI `model_dump` 错误**：LangChain/Pydantic 版本兼容问题，间歇性，走 CAIApp 内置 agent 时偶发。已在 `__call__` 和 `fallback_chat` 加了友好降级
2. **截图渲染死锁**：引擎 `save_screenshot_sync` 在快速连续调用时偶发卡死，已通过 `skip_six_view_capture=True` 跳过
3. **室外场景**：地形生成（`terrain_generation_workflow`）已有但未接入 SceneComposer，`_detect_scene_indoor` 已预留分叉
4. **视觉审核**：六/四视图截图已实现，但 `_VISUAL_REVIEW_DISABLED=True`（原 workflow 默认关闭），后续可开启做不通过打回重生成

---

## 七、提交建议

```bash
git add editor/plugins/AITool/utils/ai_setting.py
git commit -m "chore(agent): 更新 Hunyuan3D API key"
```

> 注意：`ai_setting.py` 包含 API 密钥，确认仓库权限后再推送。
