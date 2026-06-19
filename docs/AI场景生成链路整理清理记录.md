# AI 场景生成链路整理清理记录

## 1. 本轮整理目标

本轮采用保守隐藏策略，不删除旧 workflow 模块，只收敛用户可触达入口，避免验收前引入大范围回归。

官方主链路固定为：

```text
LANChat / 单人聊天
-> Intent / Planning Gate
-> InteractionCoordinator
-> SeedPlan
-> SceneDesignContract
-> GenerationScheduler
-> SceneComposerJobRunner
-> SceneComposer
-> SceneElementClassifier
-> TerrainComponentResolver
-> model_retrieval_workflow
-> progressive import / placement check
-> optional VLM review
-> DisclosurePolicy / final report
```

## 2. 保留接口

继续保留并保护以下接口：

- `InteractionCoordinator`
- `SeedPlan`
- `SceneDesignContract`
- `GenerationScheduler`
- `SceneComposerJobRunner`
- `SceneComposer.compose`
- `SceneElementClassifier`
- `TerrainComponentResolver`
- `model_retrieval_workflow`
- `scene_composer_progressive`
- `DisclosurePolicy`
- `LanChatSceneRuntime`
- `agent_progress_context`
- `vlm_review_loop`

## 3. 隐藏或废弃旧入口

默认隐藏以下历史 slash workflow 命令：

```text
/scene_agent
/sc_agent
/scene_composition
/scene_composition_v2
/sc_v2
/full_pipeline
/pipeline
/full_pipeline_v2
/fp_v2
/multi_scene
/parallel_generate
/parallel_generate_v2
/pg_v2
```

直接输入上述命令时，RoleAgent 返回统一废弃提示，不再进入旧 compose 链路。

内部调试命令默认不暴露。需要调试时可显式设置：

```text
CORONA_ENABLE_INTERNAL_WORKFLOW_COMMANDS=1
```

如需临时恢复所有旧命令用于回放或排查，可显式设置：

```text
CORONA_ENABLE_LEGACY_WORKFLOW_COMMANDS=1
```

## 4. 意图理解收口

新增中心化 `IntentUnderstandingService`，作为语义分类外壳：

```text
Protocol Parser
-> LLM semantic classifier
-> Rule Guardrail
-> Router Decision
```

关键约束：

- 状态查询不能触发生成。
- 生成方案讨论不能直接触发生成。
- 只有明确“确认开始 / 直接生成 / 按方案生成”才进入生成启动。
- 生成中的新增、修改、删除进入 intervention，不由 RoleAgent 自行猜测。
- 规则层只做协议、权限、状态和安全 guardrail。

## 5. 模型与场景基底披露

方案确认阶段会向用户披露提炼结果：

- 具体物体进入“准备生成模型”。
- 草原、天空、森林、地形、地面、墙面等进入“环境/地形”，不作为普通模型生成。
- 入口、通道、主街、边界等进入“布局结构”。

该能力由 `SceneElementClassifier` 提供，LLM 分类失败时仍由规则 guardrail 兜底。

## 6. 禁删与保护项

本轮不改动：

- `editor/plugins/AITool/utils/ai_setting.py`
- C++ / CMake / Ninja / CEF 构建文件
- Quasar 底层公共接口
- LAN 同步底层协议

验证入口：

```powershell
python editor/plugins/AITool/services/verify_ultimate_plan.py
```

本记录对应的新增测试：

- `editor/plugins/AITool/services/test_intent_understanding.py`
- `editor/plugins/AITool/services/test_workflow_command_policy.py`
- `editor/plugins/AITool/services/test_lanchat_compose_trigger_classifier.py`
