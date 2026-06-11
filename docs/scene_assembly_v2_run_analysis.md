# 场景组装 v2 运行分析报告

> 2026-05-29 | 第 2 次完整运行 | o3-mini 布局 + Qwen3-VL 审查

---

## 一、本次运行流程

```
模型: o3-mini (布局/分类) + GPT-5.5 (从属/装饰) + Qwen3-VL (审查)

12:21:42  拆解 5 个设计元素 (新中式客厅)
12:23-28  3D 生成: 5 模型全部 DONE (~5min)
12:28:20  入库: 5 模型 (嵌入 401, 非阻塞)

12:29:50  tier1_place: 初始布局 3 大件 (沙发/茶几/电视柜)
12:30:09  tier1_review #1: Qwen3-VL → NEEDS_IMPROVEMENT (score=75)
          ↑ problem_actors=[] ← VLM 没输出结构化 actor 名

12:30:25  tier1_place retry #1: LLM 收到空的"需修正物体" → 输出相同坐标
12:30:48  tier1_review #2: NEEDS_IMPROVEMENT, problems=3
          apply_diff: removed 3/3 actors (ignored 0) ← tier 守卫生效
12:31:11  tier1_place retry #2: 差量修正
12:31:38  tier1_review #3: 已达上限, 强制通过

12:32:08  tier2_place: 1/1 锚点成功 (落地灯)
12:32:31  tier2_review #1: NEEDS_IMPROVEMENT, problems=2
          apply_diff: removed 1/2 (ignored 0) ← 守卫过滤正确

12:32:37  tier2_place retry #1: Pydantic validation error → 0/1 锚点失败
12:32:37  tier2_review: 无物品, 跳过 → tier2 丢失

12:33:07  tier3_place: 初始 1 装饰 (挂画)
12:33:28  tier3_review #1: NEEDS_IMPROVEMENT, removed 1/1 → retry
12:33:56  tier3_review #2: NEEDS_IMPROVEMENT, removed 1/1 → retry
12:34:27  tier3_review #3: 已达上限, 强制通过

12:34:27  output_result: 导入 5/5, 审查 NEEDS_IMPROVEMENT
```

---

## 二、布局坐标对比

| 物体 | 上次 GPT-5.5 | 本次 o3-mini |
|------|-------------|-------------|
| 沙发 | [0, 0, 0.9] | **[-1.2, 0, 1.1]** (靠左墙) |
| 茶几 | [0, 0, 0] | **[-0.6, 0, 0]** (偏左) |
| 电视柜 | — | **[-1.0, 0, -1.25]** (靠后墙) |
| 落地灯 | [1.0, 0, -1.0] | [1.0, 0, -1.0] |
| 挂画 | [0, 1.45, 1.25] | [-1.2, 1.5, 1.5] (沙发上方) |
| X=0 比例 | **4/5 (80%)** | **0/5 (0%)** |

---

## 三、VLM 审查详情

### tier1_review #1 (Qwen3-VL)
```json
{
  "overall": "NEEDS_IMPROVEMENT",
  "score": 75,
  "problem_actors": [],
  "issues": [
    "胡桃木新中式圈椅沙发在部分视角下与茶几距离过远，布局松散。",
    "实木格栅新中式电视柜在不同视角下位置不稳定，有时悬空或与茶几重叠。"
  ],
  "suggestions": [
    "调整沙发与茶几的相对位置",
    "固定电视柜的位置，确保其始终与地面接触"
  ],
  "details": {
    "layout": "物体布局存在不稳定现象...",
    "physics": "电视柜在部分视角下出现悬空...",
    "style": "材质和光照风格基本统一...",
    "aesthetics": "构图在部分视角下显得松散..."
  }
}
```

**问题**: VLM 用自然语言描述了问题，但没有填充 `problem_actors` 数组的 `actor` 字段。代码层模糊匹配找不到对应 actor，`problem_names` 为空 → LLM retry 输入为"需修正的物体: 无" → 输出相同坐标。

---

## 四、本轮修复汇总

### Hunyuan3D API 适配 (Quasar 子模块)
| 修改 | 旧 | 新 |
|------|----|----|
| Submit 路径 | `/v1/api/3d/submit` | `/v1/ai3d/submit` |
| Query 路径 | `/v1/api/3d/query` | `/v1/ai3d/query` |
| Model 名 | `hy-3d-3.0` | `3.0` |
| EnablePBR | `body["EnablePBR"] = True` | 注释掉 |
| Query body | `{"model":..., "id":...}` | `{"JobId": ...}` |
| 并发控制 | `Lock()` | `BoundedSemaphore(max_concurrent)` |

### 场景组装 v2 架构
| 文件 | 内容 |
|------|------|
| `flows/scene_composition_workflow_v2/__init__.py` | 三层 DAG + 条件路由 (function_id=21006) |
| `nodes_tier_place.py` | 三层放置节点 + LLM 语义分类 + 差量重算 |
| `nodes_tier_review.py` | 三层独立 VLM 审查 + 差量修正 + 跨层守卫 |
| `mcp/tools/place_object_near.py` | 锚点放置工具 |
| `mcp/tools/scene_snapshot.py` | 场景快照工具 |
| `mcp/tools/set_actor_transform.py` | 绝对变换工具 |
| `register.py` / `engine_tools.py` | v2 工作流 + 新工具注册 |

### 模型矩阵
| 环节 | 模型 | Provider |
|------|------|----------|
| Tier1 布局 | `o3-mini` | DMXAPI |
| Classification | `o3-mini` | DMXAPI |
| Tier2/3 | `gpt-5.5` | DMXAPI |
| VLM 审查 | `qwen3-vl-235b-a22b-instruct` | DMXAPI |
| Agent/Dialogue | `gpt-5.5` | DMXAPI |
| 3D 生成 | `3.0` | Hunyuan3D |
| 图像生成 | `gpt-image-2` | GRSAI |

### P0 Bug 修复
1. `_apply_diff_correction` 只删除当前 tier 的 actor (跨层自动忽略)
2. VLM prompt 加 focus/locked actors 隔离
3. tier2 回退不再错调 tier1_place_node
4. 分类 LLM 加 30s 超时保护
5. Prompt V3: 布局模板 + 自检清单 + 错开布局原则
6. Actor 名字精确+模糊双匹配
7. 重复导入跳过 (按 tier 累积 imported_names)

### Debug 数据
每次运行产出:
- `layout_debug_t{tier}_{phase}.json` — LLM 输出坐标
- `review_debug_t{tier}_r{retry}.json` — VLM 完整结构化反馈
- `llm_debug_t{tier}_r{retry}.json` — LLM retry 输入/输出

---

## 五、待解决问题

1. **VLM problem_actors 为空**: Qwen3-VL 给出 good textual feedback 但不填结构化 actor 名 → LLM retry 无效
2. **Tier2 retry 锚点失败**: Pydantic validation error on place_object_near call
3. **审查通过率 0%**: 需样本量 5-10 次运行判断是 VLM 阈值问题还是布局真有问题
4. **嵌入模型 401**: tongyi-embedding 缺 API key (非阻塞, 降级生成)
