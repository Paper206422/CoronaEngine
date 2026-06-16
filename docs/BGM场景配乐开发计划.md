# 场景配乐（BGM）生成 — 开发计划

> 分支：`feature/scene-assembly-v2`
> 状态：**查验完成，待实施授权**（2026-06-15）
> 目标：场景生成管线接入音频/BGM 生成——不同场景主题 → 不同 BGM，并对齐人工介入节奏。

---

## 1. 锁定范围（已与用户对齐）

**"①+②A+②B(半隐)"** 三块，对齐聊天室人工介入节奏：

| 编号 | 名称 | 行为 |
|------|------|------|
| ① | **基础 BGM** | 聊天室内容确认后（decompose 结果落定），把场景主题喂音频模型 → 生成贴合主题的 base BGM |
| ②A | **显式介入** | 用户直接说"换 BGM / 来点空灵的 / 加鼓点" → 重新生成并替换 |
| ②B | **半隐式（半隐）** | 根据用户编辑行为（风格漂移类修改），系统**仅提示、不自动换**："场景风格变了，要不要更新 BGM"，决定权留给用户 |

**不做**：全自动按编辑实时换 BGM（隐式全自动）——留作后续。

---

## 2. 查验结论（逐环精确现状）

> 全部经 CodeGraph + Read 实证，附 `file:line`。结论：**代码侧接线几乎为零，缺口集中在配置层 + 少量编排代码**。

### 2.1 工具已就位 — ②A 代码缺口 ≈ 0 行

| 环节 | 事实 | 位置 |
|------|------|------|
| 注册 | `load_music_tools` 已作为 Quasar 内置 loader 注册（category=MEDIA） | [load_tools.py:174-187](../editor/plugins/AITool/Quasar/ai_tools/load_tools.py#L174) |
| 取出 | `load_tools()` 返回 `registry.list_tools()` —— 全量，无 category 过滤 | [load_tools.py:316](../editor/plugins/AITool/Quasar/ai_tools/load_tools.py#L316) |
| 绑定 | `_build_agent` 把全部工具（含 `generate_bgm_music`）绑给对话 LLM | [executor.py:103](../editor/plugins/AITool/Quasar/ai_agent/executor.py#L103) |
| 选择 | 工具按 **name** 选，不按 category | [model_provider.py:254](../editor/plugins/AITool/cai_extensions/agent/model_provider.py#L254) |

→ 对话 chat agent 已能发出 `generate_bgm_music` 调用，**无需补 loader**。

### 2.2 运行时前提（②A 真正的拦路点）= 配置，不是代码

- `generate_bgm_music` 加载时先查账号池：`get_pool(MediaCategory.MUSIC) is None → return []` → 工具不进 registry。 [music_tools.py:67](../editor/plugins/AITool/Quasar/ai_modules/music_generate/tools/music_tools.py#L67)
- 降级路径查 legacy client：`if not config.music.api_key: return None`。 [legacy_fallback.py:139](../editor/plugins/AITool/Quasar/ai_models/base_pool/legacy_fallback.py#L139)
- **当前部署的 music 默认 api_key = `"YOUR_API_KEY_HERE"`**（占位符）。 [settings.py:24](../editor/plugins/AITool/Quasar/ai_modules/music_generate/configs/settings.py#L24)
- 宿主 [ai_setting.py](../editor/plugins/AITool/utils/ai_setting.py) **未注册 `music`**（只有 chat/providers/image/omni/hunyuan3d 五项）。

> ⚠️ **关键陷阱**：占位符是非空字符串，过得了 `if not api_key` 守门 → 工具会注册、会绑定、LLM 能发调用，但真正打 Suno API 会因占位 key 失败。
> **结论：缺的不是代码，是配置层一个真实 Suno key（`https://www.sunoapi.org`）。**

### 2.3 播放底座齐全 — 缺口 ≈ 0

| 能力 | 状态 | 位置 |
|------|------|------|
| `play_audio(rid, loop)` | C++ pybind 完整，发 `PlayAudioEvent` 到 event_bus | [corona_engine_api.cpp:2015](../src/systems/script/python/corona_engine_api.cpp#L2015) |
| `import_media(path)` / `stop_audio(rid)` | 齐全 | corona_engine_api.cpp |
| 无引擎 fallback | `play_audio`/`stop_audio`/`import_media` 桩齐全，无声不报错 | [corona_engine_fallback.py:509](../editor/CoronaCore/utils/corona_engine_fallback.py#L509) |

> 唯一要新写的是**编排链**：`BGM 文件 → import_media(path) → rid → play_audio(rid, loop=True)`（几行）。播放原语本身不缺。

### 2.4 数据结构落点 — ① 持久化 + ②B 漂移检测

- `SceneMemory`（[memory.py:51](../editor/plugins/AITool/cai_extensions/agent/memory.py#L51)）有 `style_bible{theme,color_palette,materials,lighting,mood,avoid}` + `save/load`（JSON 序列化）。
- **但没有 `bgm` 字段** → ① 持久化 + ②B 漂移检测的落点。
- ⚠️ **compose 路径目前不填 style_bible**：`set_style_bible` 仅被 coordinator/test 调用（[grep 实证](../editor/plugins/AITool/cai_extensions/agent/)），compose 整场景生成路径未填。②B 依赖 style_bible，故需先在 compose 路径补填主题/氛围。

### 2.5 ① 触发点 — compose 收尾

- `compose()` 由 `_handle_scene_compose` 调用，返回 result dict。 [agent_adapter.py:880](../editor/plugins/AITool/cai_extensions/agent/agent_adapter.py#L880)
- `compose()` 内部收尾在 [scene_composer.py:1041](../editor/plugins/AITool/cai_extensions/agent/scene_composer.py#L1041) `return result`。
- 主题来源：`compose_text`（已有），或从 `decompose_zone_tree` 派生（更结构化）。

### 2.6 Provenance（无碰撞风险）

- BGM 代码：commit `605b9f83`，作者 Aq，2025-12-29 17:54，一次性建好。与任何同事在研工作无冲突。

---

## 3. 缺口清单（精确到落点）

| # | 缺口 | 类型 | 落点 | 量级 |
|---|------|------|------|------|
| G1 | music 真实 Suno api_key 未配 | **配置** | 宿主 [ai_setting.py](../editor/plugins/AITool/utils/ai_setting.py) 加 `register_setting("music")` | 1 项配置 |
| G2 | compose 收尾未生成 base BGM | 代码（①） | [scene_composer.py:1041](../editor/plugins/AITool/cai_extensions/agent/scene_composer.py#L1041) 前 / [agent_adapter.py:880](../editor/plugins/AITool/cai_extensions/agent/agent_adapter.py#L880) 后 | 中 |
| G3 | BGM→import→play 编排链未写 | 代码（①播放） | 新 helper（业务层调 import_media + play_audio） | 小 |
| G4 | SceneMemory 无 bgm 字段 | 代码（持久化） | [memory.py:51/81-94](../editor/plugins/AITool/cai_extensions/agent/memory.py#L51) 加 `bgm` + save/load 带上 | 小 |
| G5 | compose 路径不填 style_bible | 代码（②B 前置） | compose 收尾 set_style_bible(主题/氛围) | 小 |
| G6 | ②B 风格漂移检测 + 提示 | 代码（②B） | 编辑后比对新物体 vs style_bible，纯 Python，仅提示不自动换 | 中 |
| — | ②A 显式换 BGM | ✅ 已通 | 工具已绑定 chat agent，0 行 | 0 |
| — | 播放原语 | ✅ 已通 | C++ pybind + fallback 齐全 | 0 |

---

## 4. 实施步骤（建议分阶段）

### 阶段 0：打通 ②A（最小可用，先验证端到端）
1. **G1** 宿主 ai_setting.py 注册 music + 真实 Suno key（或走账号池）。
2. 启动验证：`generate_bgm_music` 进 registry（不被空池丢）。
3. F5 实测：聊天框说"生成一段空灵的背景音乐" → LLM 调工具 → 拿到音频 file_id。

> 阶段 0 完成即证明"②A 现在能用"从"代码成立"变成"实测成立"。

### 阶段 1：① 基础 BGM（compose 收尾自动生成 + 播放）
4. **G4** SceneMemory 加 `bgm` 字段（结构建议：`{file_id, prompt, theme, created_at, expire_at}`），save/load 带上。
5. **G3** 写播放编排 helper：`play_bgm(audio_path_or_id, loop=True)` → import_media → play_audio。
6. **G2** compose 收尾：从主题派生 prompt → 调 `_generate_bgm` → 写入 SceneMemory.bgm → 触发 play_bgm。
   - best-effort：BGM 失败仅 warning，绝不影响场景组合主链路返回。
7. **G5** 同处 set_style_bible（主题/氛围），为 ②B 铺垫。

### 阶段 2：②B 半隐式提示
8. **G6** 编辑行为后（走菜包通道，见 [edit-via-caibao-channel](../../../../Users/fzm/.claude/projects/e--corona-CoronaEngine/memory/edit-via-caibao-channel.md)）比对新增/改动物体语义 vs `style_bible.theme/mood`。
9. 漂移超阈值 → 向聊天室推一条提示："场景风格似乎从 X 偏向 Y，要不要更新 BGM？"——**不自动换**。
10. 用户确认 → 复用阶段 0 的 ②A 路径重新生成。

---

## 5. 风险

- **占位 key 假阳性**：占位符过守门但实际失败，错误信息易被误读为"工具没接好"。阶段 0 必须配真 key 并 F5 实测，不能只看 registry 是否有该工具。
- **BGM 生成耗时**：Suno 生成是异步任务（media_registry.submit），compose 收尾不应阻塞等音频——应 fire-and-forget + 回调写 SceneMemory + 播放。
- **录制安全**：demo 录制走已存盘的 `.scene` 静态文件，加 BGM 字段需保证旧 `.scene`（无 bgm）load 不崩（向后兼容默认空）。
- **②B 误报**：漂移阈值过敏 → 频繁打扰用户。阈值宜保守，宁可漏提示不可频繁打扰。
- **BGM 过期**：audio 15 天过期（media_registry）。SceneMemory.bgm 应存 expire_at，load 时过期则标记需重生成而非播放死链接。

---

## 6. 验证

- 阶段 0：F5，聊天框显式指令 → 听到 BGM（或拿到有效 file_id）。
- 阶段 1：F5，跑一个整场景生成（如蒙古包 / 教堂）→ 自动播放贴合主题的 BGM；不同主题听感不同。
- 阶段 1 兼容：load 一个旧 `.scene`（无 bgm 字段）→ 不崩、无 BGM。
- 阶段 2：编辑出明显风格漂移（如赛博场景里加古典家具）→ 收到提示、BGM **不**自动变；确认后才换。
- 单测：SceneMemory.bgm save/load 往返；旧数据无 bgm load 兼容。

---

## 附：本计划基于的查验调用链（防回溯重查）

CodeGraph 实证（绝对优先 CodeGraph，见 [prefer-codegraph](../../../../Users/fzm/.claude/projects/e--corona-CoronaEngine/memory/prefer-codegraph.md)）：
`codegraph_explore(load_music_tools / pool_registry / get_pool)` → `codegraph_node(music_tools.py)` → `codegraph_explore(legacy_fallback music client)` → `codegraph_search(play_audio)` → `codegraph_explore(SceneMemory compose)` + Read 确认 ai_setting.py / settings.py / agent_adapter.py。
