# 场景组装 v3 实施计划：GPT-5.5 视觉合并审查+修正

> 2026-05-30 | 基于 15+ 次测试运行的数据诊断

---

## 一、问题诊断

### 当前致命断点

```
VLM (GPT-5.5) 看 8 张截图
  → 判断: 茶几距离沙发 1.5m, 应该 0.7m
  → 输出: {"issue": "too_far"}  ← 空间信息丢失 90%

LLM (o3-mini) 收到文本
  → 输入: "茶几 too_far"
  → 只能: 再猜一次坐标 (盲猜)
```

**根本原因**: VLM 有完整空间信息但只输出文本标签, LLM 需要空间信息但只收到文本标签。

### 数据支撑 (15+ 轮 VLM 问题统计)

| 问题类型 | 占比 | 说明 |
|---------|------|------|
| 位置/距离 | 51% | LLM 布局不准确 |
| 尺度/比例 | 14% | 默认 Scale 已大幅改善 |
| 悬空/漂浮 | 7% | 物理沉降+挂墙修正已生效 (从29%降至7%) |
| 朝向/方向 | 3% | 基本不是问题 |
| 其他 | 25% | 环境缺失等 |

**51% 的位置问题可以通过 GPT-5.5 直接看图修正。**

---

## 二、解决方案

### 核心改变

```
现在:  VLM 看截图 → "too_far" → 文本转给 o3-mini → o3-mini 盲猜坐标
改为:  GPT-5.5 看截图 → 直接输出修正坐标 → 代码执行
```

### 架构不变的部分

- Tier1 初始布局: o3-mini (空地没东西可看)
- Tier2/Tier3 初始布局: 保持 gpt-5.5 锚点/绝对坐标
- 物理沉降 / 挂墙修正 / 默认 Scale: 全部保留
- DAG 结构: 三层条件路由不变

### 架构改变的部分

```
TierX Review 节点:
  旧: VLM 审查 → 输出 problem_actors → LLM retry 猜坐标
  新: GPT-5.5 审查+修正 → 输出 corrections (直接坐标) → 代码执行
```

---

## 三、实施步骤

### Step 1: 改 VLM Prompt (scene_review_tools.py)

在现有 prompt 的 JSON 格式中加 `corrections` 字段:

```json
{
  "overall": "PASS" | "NEEDS_IMPROVEMENT",
  "score": 82,
  "problem_actors": [...],
  "corrections": [
    {
      "object_id": "茶几",
      "position": [-0.9, 0, 0.35],
      "rotation": [0, 0, 0],
      "reason": "调整到沙发前方 0.7m"
    }
  ],
  "issues": [...],
  "suggestions": [...]
}
```

### Step 2: 改 _tier_review 节点 (nodes_tier_review.py)

在现有 `_apply_diff_correction` 之前加 `_apply_corrections`:

```
VLM 输出 → 解析 corrections
  → 校验坐标 (边界/clamp)
  → set_actor_transform 执行
  → 修正成功 → 直接 PASS (不再走 diff + retry)
  → 修正失败 → fallback 到现有 diff correction
```

### Step 3: 加保护

- 坐标边界校验: X/Z 必须在房间范围内
- corrections 为空时: 回退现有逻辑
- 最多 2 轮审查 (和现在一致)
- GPT-5.5 不输出 corrections 时: 降级为当前 diff correction

### Step 4: 验证

F5 → `/sc_v2 --test` → 对比评分变化

---

## 四、涉及文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `scene_review_tools.py` | prompt 加 corrections 格式 | ~20 |
| `nodes_tier_review.py` | 新增 `_apply_corrections`, 集成到 `_tier_review` | ~50 |
| `ai_setting.py` | 不变 (VLM 已是 gpt-5.5) | 0 |
| `nodes_tier_place.py` | 不变 | 0 |
| `__init__.py` | 不变 | 0 |

---

## 五、时间线

| 时间 | 步骤 |
|------|------|
| 2026-05-30 现在 | Step 1-3 实施 |
| 2026-05-30 | Step 4 验证 |
