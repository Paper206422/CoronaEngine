# 单人 + 多 Agent F5 验收手册

## 目标

验证单人 + 多 Role Agent 主线能作为论文/demo 主线：

- 生成前可确认方案。
- 生成中按 micro-batch 分批出现。
- 用户和其他 Agent 能在生成中介入。
- 后续 batch 能吸收 pending layout / generation notes。
- AABB 负责几何可靠性。
- VLM 只做最后 advisory 审查，不拖垮主链路。

## 推荐环境

第一轮主链路验收关闭 VLM：

```powershell
$env:CORONA_RESOURCESEARCH_DISABLE_AUTO_REBUILD="1"
$env:CORONA_F5_DEMO_MODE="1"
$env:PROGRESSIVE_VLM_MAX_TARGETS="0"
$env:CORONA_IMAGE_RETRY_MAX_WORKERS="3"
$env:CORONA_HUNYUAN_MAX_CONCURRENCY="3"
$env:LANCHAT_AGENT_ASYNC="1"
$env:CORONA_PROGRESSIVE_BATCH_SIZE="3"
$env:CORONA_MIN_SCENE_ITEMS="6"
```

第二轮只验 VLM 论文点：

```powershell
$env:PROGRESSIVE_VLM_MAX_TARGETS="1"
```

如果未显式设置 `PROGRESSIVE_VLM_MAX_TARGETS`，`CORONA_F5_DEMO_MODE=1` 下默认不跑 VLM。

## 场景 A：森林奇幻集市

输入：

```text
@长者 我有一个计划，建立一个森林奇幻集市
```

预期：

- 不直接生成。
- 返回确认方案。
- 方案含 6-10 个物体或类别。

继续：

```text
@长者 补充：要有发光蘑菇、灯串和精灵木牌
@长者 确认开始，先生成前三个
```

生成中介入：

```text
@小女孩 后面再加两个摊位和一块中央活动区
@小女孩 不要太空，灯串多一点
@长者 后续不要挡住中间活动区
```

通过标准：

- 至少 6 个物体进入计划。
- 至少 3 个 micro-batch。
- 小女孩能快速轻回复，不启动第二个 compose。
- 中央活动区约束影响后续 batch 或进入最终报告。
- 最终不是只有树木 + 摊位。

## 场景 B：儿童卧室

输入：

```text
@小D 生成一个儿童卧室，有儿童床、书桌、椅子、衣柜、书架、地毯、台灯、玩具柜。
```

生成中介入：

```text
@小D 放大儿童床
@学者 后面再加一个小台灯
@小D 后续家具都靠墙，不要挤在中间
```

通过标准：

- 8 个物体分批出现。
- 儿童床快速放大并贴地。
- 小台灯若未预生成，最终报告标为待补生成。
- 家具不明显堆叠。
- 地毯作为 surface，不把家具挤开。
- 学者轻回复，不抢生成。

## 场景 C：欧式教堂广场

输入：

```text
@学者 在大理石广场上设计一个欧式教堂，要有喷泉、天使雕像、石质铺装和开阔前场。
```

生成中介入：

```text
@小D 喷泉必须在教堂外广场轴线上
@小D 放大天使雕像
@小D 喷泉底座穿模了
@小D 把雕像旋转90度
```

通过标准：

- 喷泉在教堂外广场，不进入教堂内部。
- 雕像比例合理，不明显穿模。
- 旋转 90 度后返回/日志中的 yaw 约为 `1.5708` 弧度。
- 不重复生成第二个教堂。
- 无草原花草簇。
- VLM 关闭时主链路稳定；开启 1 target 时输出审查或 skipped/warn。

## 每轮记录

请记录以下结果，便于快速归因：

```text
是否出现确认方案:
是否真的分批:
每批大约耗时:
输入框是否可继续输入:
其他 Agent 是否 quick ack:
快车道编辑是否进入 integrated stream:
pending 是否出现在最终报告:
AABB 是否有 needs_confirm:
VLM 是否 skipped/warn:
是否出现 ResourceSearch rebuild:
是否出现画面黑屏或长时间卡顿:
```

## 失败归因

- 输入框本身卡死：C++/CEF/UI 主线程或渲染线程问题。
- 能输入但 Agent 晚回复：Python agent lock、integrated stream 或快车道覆盖不足。
- 生成中新增全新物体没有立即出现：当前设计边界，进入待补生成。
- VLM 开启后黑屏/卡顿：截图管线占用主相机或主 render target。
- AABB unresolved：进入 `needs_confirm`，不算自动修复成功。
