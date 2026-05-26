# Vision 渲染接入 CoronaEngine 最小改动收敛计划

## 1. 文档目标

本文档不再假设 Vision 接入尚未开始实现，而是用于回答两个更直接的问题：

1. 当前代码距离“最小可运行 Vision 渲染模式”还差什么。
2. 剩余工作应按什么顺序收敛，才能最小成本达成首版目标。

当前仓库内已经存在一版 Vision 接入实现，包括：

- OpticsSystem 中的 native / vision 后端切换骨架。
- Vision geometry / light / material adapter。
- Vision camera adapter 目标已确定，现阶段以主相机同步为收敛方向。
- Vision output bridge。
- Python 侧 `set_render_backend()` / `get_render_backend()` 接口。

因此，本文档的定位从“纯设计方案”调整为“差距清单 + 收敛方案”。

首版最终目标保持不变：

- 在不改动 DisplaySystem 协议的前提下，复用现有图像句柄与事件流。
- 支持 native 与 vision 两种渲染后端运行时切换。
- Vision 输出可以直接驱动现有显示链路。
- 首版范围限定为静态几何、环境光 / 太阳光、纯色材质、基础透视相机。
- 先完成可运行、可切换、可验证版本，再进行性能优化。

但需要明确：以上目标目前**尚未完全达成**，下文按“已完成 / 未完成 / 下一步”方式收敛。

---

## 2. 当前实现与目标的偏差

总体方案仍然采用“单点接入 + 适配层 + 输出桥接”，但当前实现与目标之间存在几处明确偏差。

### 2.1 已经基本具备的能力

- OpticsSystem 已具备后端切换状态与 Vision 分支入口。
- Vision 渲染结果已可通过 output bridge 写回现有 `HardwareImage`。
- geometry / light / material 三类适配器已经有独立实现。
- Python 已可从脚本侧触发后端切换。

这些能力说明工程并非从零开始，阶段 A 的一部分和阶段 C / D 的基础链路已经存在。

### 2.2 仍未达成的关键目标

1. 仍依赖外部 Vision 场景 JSON 路径
- 当前 Vision 初始化仍要求先设置 `vision_scene_path`，然后通过 `import_scene()` 创建 pipeline。
- 这与“从 Corona 场景数据直接适配到 Vision”不一致。
- 该项是当前首要阻塞项。

2. 相机尚未独立收敛为第四个适配器
- 当前相机同步逻辑仍内嵌在 `OpticsSystem` 中。
- 功能上已存在相机同步，但职责边界还未达到“四适配器”目标。

3. 几何适配未优先使用资源层 CPU mesh 数据
- 当前实现主要从 `MeshDevice` 的 vertex / index buffer 回读数据。
- 这与“优先使用 CPU mesh 数据，避免仅依赖 GPU buffer 句柄”的目标不一致。

4. viewport / resize / 多 camera 语义未完全闭环
- 当前 Vision 路径只处理首个 scene 和首个 camera。
- 输出分辨率是否严格跟随当前 viewport、resize 时是否完整重建，尚未形成明确闭环。

5. 错误处理策略未完整落地
- 当前已有初始化失败日志与留在 native 的处理。
- 但“单帧失败保留上一帧、连续失败阈值告警、不自动 fallback”的策略尚未完整实现。

### 2.3 需要立即统一的文档口径

当前仓库同时存在两种表述：

- 一种表述认为 Vision 首版尚未开始，仍在设计阶段。
- 另一种表述已经把当前 Vision 接入写成“现有适配代码说明”。

为避免后续实现跑偏，本文档以后者为现实基础，但以后续目标为验收标准，只记录“当前还差什么”。

---

## 3. 最终收敛后的目标边界

总体采用 单点接入 + 适配层 + 输出桥接 的方式：

- 单点接入：仅在 OpticsSystem 内实现后端选择与调度。
- 四适配器：
  - 几何适配器：Geometry 数据到 Vision Mesh 和 Instance。
  - 光源适配器：Environment 和 Sun 参数到 Vision Light。
  - 材质适配器：OpticsDevice 参数与材质颜色纹理到 Vision principled BSDF Material。
  - **相机适配器**：从 OpticsSystem 当前视角收集相机位置、朝向、FOV、近远裁面等参数，转换为 Vision Camera。
- 输出桥接层：将 Vision 渲染结果写入现有 ImageStorage 句柄，并继续发布 OpticsFrameReadyEvent。

该方案可以保持 DisplaySystem 无感知，无需修改显示系统架构。

实现边界保持如下：

- 尽量不修改 Vision 内部渲染逻辑。
- 所有 Corona 到 Vision 的适配逻辑统一放在 OpticsSystem 目录下。
- 若 Vision 现有公开接口不足，仅允许补最小公开接口，不修改 Vision 的核心渲染算法、材质实现、几何处理主流程与积分器逻辑。

首版切换语义最终确定为：

- 支持运行时切换。
- 切换采用“下一帧生效”的安全热切换策略。
- 切换时允许在 OpticsSystem 线程内执行一次 Vision 资源重建与状态清空。
- 不要求无重建零停顿切换。
- 首版以稳定性优先，不追求切换过程中的完全无缝连续累积。

这意味着首版实现目标不是“两个后端同时常驻、瞬时无损切换”，而是“运行中可切换，并在下一帧以安全方式切入目标后端”。

---

## 3.1 首版确定方案

本项目首版目标已经固定，不再保留开放项，具体如下：

1. 接入位置固定
- 所有 Vision 接入逻辑都收敛在 OpticsSystem 下。
- 不新增独立 VisionSystem。
- DisplaySystem 不做协议修改。

2. 数据范围固定
- 只支持静态几何。
- 只支持环境光与太阳光参数。
- 只支持纯色材质。
- 不支持纹理。
- **相机参数**：只支持一个主相机，从引擎当前主相机读取位置、朝向、FOV、近远裁面与输出尺寸，支持基础透视相机。

3. 材质模型固定
- Corona 材质统一映射到 Vision principled BSDF。
- 首版仅使用基础颜色与基础 BRDF 标量参数。
- 具体映射关系：`materialColor` → `baseColor`，`roughness` → `roughness`，`metallic` → `metallic`，其余参数使用 Vision 默认值。

4. 切换行为固定
- 支持运行时切换。
- 切换在下一帧生效。
- 切换时清空 Vision 累积与缓存状态。

5. 输出路径固定
- Vision 输出继续写入现有 ImageStorage。
- 继续发布现有 OpticsFrameReadyEvent。
- DisplaySystem 无感知后端差异。
- 输出分辨率跟随当前引擎主相机尺寸；若相机尺寸变化，Vision 输出随之重建。

6. Vision 修改策略固定
- 默认不改 Vision 内部逻辑。
- 如必须修改，仅允许补最小公开接口，以打通 scene / sensor / geometry / material / light / render 的主路径。
- 不允许将 Corona 适配逻辑写入 vision/ 目录。

7. 同步策略固定
- 首版允许全量重建 Vision 场景数据。
- 暂不做增量同步优化。

8. Vision 帧累积策略固定
- Vision 路径追踪采用逐帧增量累积模式，持续提升画质。
- 场景数据或相机发生变化时，清空已有累积帧，重新开始累积。
- 首版不设累积帧数上限，以稳定性为优先。

9. 坐标系适配固定
- 首版在适配器中统一处理 Corona 与 Vision 之间的坐标系转换（如存在差异）。
- 转换逻辑封装在各适配器内部，不散落到 OpticsSystem 主流程。

10. 错误处理策略固定
- Vision 单帧渲染失败时，输出上一帧结果（若有），并记录错误日志，**不自动 fallback 到 native**。
- 若连续失败超过阈值（首版建议 3 帧），触发告警日志，由用户主动切换回 native。

11. 切换请求传递机制固定
- 使用 `atomic` 标志位传递切换请求，OpticsSystem 在每帧渲染前检查并执行切换。
- 不使用消息队列，保持实现简单。

这就是首版的最终验收边界，后续实现以此为准。

### 3.2 已确认执行决策

以下事项已由当前任务直接确认，不再保留讨论空间：

1. 相机范围
- 首版只支持一个主相机。
- Vision 渲染始终跟随引擎当前主相机。

2. 输出尺寸语义
- Vision 输出尺寸跟随引擎主相机尺寸，而不是编辑器独立 viewport 语义。
- 主相机尺寸变化时，触发 Vision 输出重建与累积清空。

3. 调试接口策略
- `set_vision_scene_path()` 从首版正式路径中直接移除。
- 首版不保留“先导入外部 scene JSON 再补 Corona 数据”的主流程。

4. 几何数据策略
- 几何适配以 CPU mesh 为主路径。
- 若资源侧当前不存在 CPU mesh，则允许从 GPU buffer 下载并构造 CPU mesh，再进入几何适配器。
- 也就是说，进入 Vision 几何适配器前，统一收敛为 CPU mesh 形态。

5. Vision 接口补充策略
- 若 Vision 当前公开接口不足，允许按最小成本补充必要公开接口。
- 目标不是重构 Vision，而是让 Corona 侧可以纯代码构建并驱动 Vision 渲染主路径。

6. 主路径收敛策略
- 首版正式实现路径以“纯 Corona 数据驱动 Vision”优先。
- 不再把外部 scene import 作为首版主路径前提。

---

## 4. 当前代码与目标的差距清单

以下条目只保留仍需收敛的部分；已经落地的内容不再作为“待设计项”重复展开。

### 4.1 P0：必须先解决的阻塞项

1. 去除 `vision_scene_path` 外部场景依赖
- Vision 后端应从 Corona 当前场景数据直接构造可渲染场景，而不是依赖外部 JSON 文件。
- `set_vision_scene_path()` 应从首版主路径直接移除，不再作为调试入口或功能前置条件。

2. 明确 Vision scene / pipeline 的构建入口
- 需要确认是否可在不导入外部 scene JSON 的前提下创建空 scene、注册 geometry / material / light / sensor 并执行 render。
- 若 Vision 公开接口不足，应先补最小公开入口，再开始后续收敛。

3. 完整定义 Vision 相机适配边界
- 将当前 `OpticsSystem` 内的相机同步逻辑抽为独立 camera adapter，职责与 geometry / light / material 对齐。
- camera adapter 只面向引擎主相机工作。
- 相机或相机尺寸变化时负责通知 Vision 清空累积帧并重建必要输出资源。

### 4.2 P1：首版功能闭环项

4. 几何适配切回 CPU mesh 优先路径
- 优先从资源层 CPU mesh 数据构建 Vision Mesh。
- 若资源层暂时缺失 CPU mesh，则先从 GPU buffer 下载构造 CPU mesh，再进入 Vision 几何适配流程。

5. 完整补齐 viewport / resize / camera 语义
- Vision 输出尺寸必须明确跟随当前引擎主相机尺寸。
- 主相机尺寸变化时需要明确执行输出重建与累积清空。
- 首版只支持一个主相机，代码与文档都按此约束实现。

6. 错误处理状态机补齐
- 单帧失败时保留上一帧结果并记录错误。
- 连续失败超过阈值后记录告警日志。
- 不自动切回 native，由用户或脚本主动切换。

### 4.3 P2：文档与接口收口项

7. 收敛脚本接口口径
- 首版应保留 `set_render_backend()` 与 `get_render_backend()`。
- `set_vision_scene_path()` 从主文档、正式接口与首版实现路径中移除。

8. 收敛说明文档
- `docs/vision_integration.md` 目前偏向“现状说明”，需要在后续与本计划统一。
- 本文档作为“目标差距文档”，后续只维护剩余缺口与实施顺序。

---

## 5. 改动范围与文件清单

### 5.1 必改文件

1. src/systems/optics/optics_system.cpp
- 去除 `vision_scene_path` 作为首版主路径依赖。
- 保留后端分支调度，但缩减为“切换 / 调度 / 状态管理”职责。
- 将主相机适配、错误处理、相机尺寸变化重建逻辑收敛到稳定边界。
- 统一输出到现有 image_handle 和事件发布流程。

2. include/corona/systems/optics/optics_system.h
- 补充 Vision 失败计数、上一帧输出保留、viewport / resize 状态等字段。
- 增加 Vision camera adapter 与状态管理相关私有方法声明。

3. include/corona/systems/script/corona_engine_api.h
- 保留后端切换 API 声明。
- 移除 `set_vision_scene_path()` 声明。

4. src/systems/script/python/corona_engine_api.cpp
- 保留后端切换 API。
- 移除 `set_vision_scene_path()` 相关实现与说明。

### 5.2 建议新增文件

5. src/systems/optics/vision/vision_geometry_adapter.h
6. src/systems/optics/vision/vision_geometry_adapter.cpp

7. src/systems/optics/vision/vision_light_adapter.h
8. src/systems/optics/vision/vision_light_adapter.cpp

9. src/systems/optics/vision/vision_material_adapter.h
10. src/systems/optics/vision/vision_material_adapter.cpp

11. src/systems/optics/vision/vision_camera_adapter.h
12. src/systems/optics/vision/vision_camera_adapter.cpp

13. src/systems/optics/vision/vision_output_bridge.h
14. src/systems/optics/vision/vision_output_bridge.cpp

说明：geometry / light / material / output bridge 已存在独立文件，camera adapter 建议补成同级独立文件，不再继续把职责留在 `optics_system.cpp` 内。

目录约束：
- 优先将所有新增适配代码放在 src/systems/optics/vision/ 下。
- 不在 vision/ 目录下新增 Corona 专用适配实现。

### 5.3 可能需要轻量确认的构建文件

13. misc/cmake/corona_options.cmake
14. misc/cmake/corona_compile_config.cmake

仅确认 CORONA_BUILD_VISION 与 CORONA_ENABLE_VISION 宏链路是否按预期生效。

---

## 6. 分阶段收敛计划

### 首版范围锁定

为控制改动范围并优先打通最小闭环，首版实现边界明确如下：

- 只支持静态几何，不覆盖动画、蒙皮、运行时网格拓扑变化。
- 只支持环境光参数，不接入点光、聚光、面光等额外灯光类型。
- 材质只支持纯色参数，不接入纹理采样链路。
- 材质目标模型仍统一适配为 Vision principled BSDF，但首版仅使用其纯色相关基础参数。
- 后端切换采用下一帧生效策略，允许安全重建，不要求无缝无重建切换。

以下能力明确延后：

- 法线纹理、金属度纹理、粗糙度纹理、透明度纹理。
- 多灯混合与复杂灯光类型映射。
- 动态网格、骨骼动画、形变几何增量同步。

### 阶段 A：后端切换骨架与输出链路保持

目标：把当前已有框架收敛成稳定主路径，不破坏 native 现有行为。

步骤：
1. 保留现有后端枚举与切换状态，不重新设计该层结构。
2. 删除 `vision_scene_path` 作为首版必需依赖，改为从 Corona 运行时数据构建 Vision scene。
3. 保留原有 image_handle 写入和 OpticsFrameReadyEvent 发布逻辑，继续作为统一输出链路。
4. 将后端切换继续保持为“挂起状态”，在下一帧渲染开始前统一处理。
5. 处理切换时的 Vision 状态清空、安全重建与累积清空。

完成标准：
- 工程在 Vision 开关关闭和开启时均可编译。
- native 路径渲染行为不变。
- Vision 模式不再依赖外部 scene JSON 才能启动。
- 后端切换请求可在运行时提交，并在下一帧安全生效。

### 阶段 B：四适配器最小可用实现

目标：把现有适配器收敛到首版要求的输入边界。

步骤：
1. 几何适配器
- 输入：Scene Actor Profile Optics Geometry Transform。
- 几何数据源优先使用模型资源中的 CPU mesh 数据。
- 若 CPU mesh 缺失，则先从 GPU buffer 下载构造 CPU mesh，再进入适配逻辑。
- 若 CPU mesh 数据不可用，跳过该物体并记录警告日志，不中断渲染。
- 输出：Vision Mesh 与 ShapeInstance。
- 首版仅处理静态 mesh 与 transform，不处理动画和拓扑变化。
- 适配器内部统一处理坐标系转换（如 Corona 与 Vision 存在差异）。

2. 光源适配器
- 输入：Environment 的 sun_position、sun_color、sun_intensity、sky_intensity。
- 输出：Vision directional 或 environment light。
- 首版仅处理环境光与太阳光相关参数，不支持额外灯光类型。

3. 材质适配器
- 输入：OpticsDevice BRDF 参数、materialColor、纹理句柄信息。
- 输出：Vision principled BSDF Material。
- 映射规则：`materialColor` → `baseColor`，`roughness` → `roughness`，`metallic` → `metallic`，其余参数取 Vision 默认值。
- 首版不接入纹理，材质仅使用纯色与基础 BRDF 标量参数。

4. 相机适配器
- 输入：引擎主相机当前帧数据（位置、朝向、FOV、近远裁面、输出尺寸）。
- 输出：Vision Camera 对象。
- 坐标系转换封装在适配器内部。
- 相机参数每帧更新；主相机参数或相机尺寸变化时通知 Vision 清空累积帧并重建必要输出资源。

完成标准：
- 单场景下可生成不依赖外部 JSON 的 Vision 可渲染场景对象（含相机）。
- 参数变化能够正确反映到 Vision 对象（允许首版全量刷新）。

### 阶段 C：Vision 渲染输出桥接

目标：让 DisplaySystem 可以直接显示 Vision 输出，并明确 viewport 语义。

步骤：
1. 调用 Vision pipeline 执行渲染。
2. 将 Vision 帧缓冲结果拷贝或导入到 Horizon HardwareImage。
3. 写回 SharedDataHub image_storage 对应 image_handle。
4. 使用现有事件类型发布 OpticsFrameReadyEvent。
5. 确认 Vision 输出分辨率与当前引擎主相机尺寸一致；若不一致，执行尺寸对齐或重建。
6. 首版固定只处理一个主相机，并保证代码与文档一致。

首版实现决策：
- 优先采用稳定的结果拷贝或格式转换写回方案。
- 不将”零拷贝共享输出”作为首版前置要求。
- Vision 单帧失败时，输出上一帧结果并记录日志，不自动 fallback。

完成标准：
- 不改 DisplaySystem 的情况下，主窗口可显示 Vision 渲染结果。
- native 与 vision 切换后均能稳定显示。
- 主相机尺寸变化后不会长期输出错误尺寸图像。

### 阶段 D：脚本接口与运行时切换

目标：从脚本或编辑器触发后端切换，并收口调试接口。

步骤：
1. 新增 set_render_backend 接口。
2. 增加 get_render_backend 用于 UI 状态展示（可选但建议）。
3. 移除 `set_vision_scene_path`。
4. 切换时触发必要资源重置（例如清累计帧、重建或标记重建 Vision 场景）。

首版实现决策：
- 切换接口提交请求，不直接在外部线程即时改后端状态。
- 真正的后端切换与资源重建只在 OpticsSystem 更新线程内执行。

完成标准：
- 运行中可在 native 和 vision 间切换。
- 切换后首帧有效，无崩溃或黑屏长期停留。
- 主文档中的脚本接口与真实实现保持一致，且不再暴露 `set_vision_scene_path`。

### 阶段 E：增量优化（非首版阻塞）

目标：降低首版全量重建开销。

步骤：
1. 增加 mesh 和 material 缓存键（如 model_id、mesh_idx、material_hash）。
2. 对 transform、environment 参数采用增量更新。
3. 仅在资源变化时重建加速结构。

完成标准：
- 切换后首版功能不回退。
- 大场景帧时延和内存占用可控。

---

## 7. 关键技术约束与决策

1. DisplaySystem 不改协议
- 保持 image_handle 与 OpticsFrameReadyEvent 不变，降低联动风险。

2. 首版优先正确性
- 首版允许全量同步，先确保可渲染与可切换。

补充决策：
- 首版优先可验证与稳定，不优先最优性能。

3. 适配器输入统一
- 适配器不直接访问 UI 或脚本层，仅接收 Optics 收集好的帧数据。
- 相机适配器同样仅从 OpticsSystem 当前帧数据读取，不直接访问编辑器视口。

4. 宏开关策略
- Vision 相关编译代码必须受 CORONA_ENABLE_VISION 保护。

5. Vision 修改红线
- 不在 Vision 内部引入 Corona 数据结构。
- 不修改 Vision 的材质模型内部实现，Corona 侧统一适配到 Vision principled BSDF。
- 不修改 Vision 的积分器、核心渲染流程、几何求交主路径。
- 若确实缺少外部调用入口，仅允许增加最小公开接口，并保持 Vision 对 Corona 无反向依赖。
- **在开始阶段 A 前，需先对 Vision 现有公开接口进行一次盘点**，确认是否可以不依赖外部 scene JSON 直接创建并渲染场景；若不行，再按最小成本补足必要公开接口，避免阶段 B/C 返工。

6. 切换线程模型
- 外部系统只能发起切换请求，使用 `atomic` 标志位传递。
- OpticsSystem 在每帧渲染开始前统一检查并执行切换，是唯一允许实际提交后端切换和资源替换的线程。
- 不做跨线程即时抢占式切换。

7. 坐标系适配
- 如 Corona 与 Vision 存在坐标系差异（如 Y-up vs Z-up），统一在各适配器内部处理转换。
- 转换逻辑不散落在 OpticsSystem 主流程中。

8. Vision 帧累积
- Vision 路径追踪采用逐帧增量累积，持续提升画质。
- 场景数据或相机变化时清空累积帧。
- 首版不设帧数上限。

---

## 8. 风险清单与应对

1. 风险：相机参数缺失或无对应接口
- 应对：阶段 A 前盘点 Vision 相机接口，确认主相机的 position/direction/fov/near/far/size 设置入口；若缺失则补最小公开接口。

2. 风险：Vision 公开接口不完备（无法脱离 scene JSON 初始化）
- 应对：**阶段 A 开始前**完成接口盘点，优先确认 scene / sensor / render 主入口是否可纯代码构建。

3. 风险：几何 CPU 数据缺失或来源不一致
- 应对：通过 model_resource_handle 回查资源层 Scene 的 mesh 顶点索引；若资源侧没有 CPU mesh，则从 GPU buffer 下载并构造 CPU mesh；仍不可用时跳过该物体并记录警告，不中断渲染。

4. 风险：坐标系不一致导致画面错误
- 应对：阶段 B 初期先对比 Corona 与 Vision 坐标系约定，确认是否需要转换，统一封装在适配器内。

5. 风险：Vision 输出格式与 HardwareImage 不匹配
- 应对：增加统一格式转换和尺寸对齐逻辑，首版固定输出格式，viewport resize 时重建 Vision 输出。

6. 风险：切换时资源生命周期冲突
- 应对：切换动作串行化，在 OpticsSystem 线程内执行重建和替换；atomic 标志位保证线程安全。

7. 风险：首版性能波动较大
- 应对：先保证功能，再做缓存和增量策略。

8. 风险：Corona 材质参数与 Vision principled BSDF 语义不完全一致
- 应对：首版只做稳定的一对一主参数映射（materialColor→baseColor / roughness→roughness / metallic→metallic），明确不追求完全视觉一致；差异通过映射表和后续校准迭代处理。

9. 风险：Vision 路径追踪累积帧导致切换后画面短暂噪点
- 应对：切换时主动清空累积帧，告知用户 Vision 模式需若干帧收敛，属预期行为。

10. 风险：环境光首版范围过窄，用户预期包含其他灯光类型
- 应对：文档与实现都明确首版只支持环境光与太阳光，其他灯光延后到下一阶段。

---

## 9. 验收标准

### 功能验收
- native 后端正常渲染。
- vision 后端正常渲染，且不依赖外部 scene JSON 作为前置条件。
- 运行中可从 native 切换到 vision，再切回 native。
- DisplaySystem 无代码改动仍可显示两者输出。
- 静态几何场景可正确显示。
- 环境光参数变化可传递到 Vision。
- 纯色材质可正确映射到 Vision principled BSDF。
- 切换请求在下一帧生效，且切换后首帧输出有效。
- 主相机尺寸变化后输出尺寸能够同步更新。

### 稳定性验收
- 连续切换 50 次无崩溃。
- 场景加载后连续运行 10 分钟无显存泄漏趋势。
- 切换过程中允许发生一次安全重建，但不允许长期黑屏或卡死。

### 可维护性验收
- 适配器职责边界清晰。
- optics_system.cpp 不再包含硬编码 Vision 场景路径。

---

## 10. 推荐实施顺序（两周样例）

- 第 1 到 2 天：阶段 A 与 Vision 公开接口盘点
- 第 3 到 5 天：阶段 B
- 第 6 到 7 天：阶段 C
- 第 8 到 9 天：阶段 D
- 第 10 天：联调与回归
- 第 11 到 14 天：阶段 E 与文档补充

---

## 11. 回滚策略

若 Vision 分支出现问题：
- 通过后端开关强制回退 native。
- 保留所有 native 渲染路径与事件发布逻辑。
- Vision 代码受编译宏保护，可一键关闭构建。

---

## 12. 后续扩展建议

- 将适配器抽象为可插拔后端接口，为未来接入更多渲染器预留统一边界。
- 将输出桥接扩展为多输出通道，支持调试视图和离线导出。
- 在编辑器中加入后端切换与状态诊断面板。

---

## 13. 当前结论

当前结论不是“方案还未开始”，而是：

- Vision 接入已经有一版基础实现。
- 但首版目标尚未真正闭环。
- 当前最先要补的是主路径依赖、相机适配边界、CPU mesh 输入路径、viewport 语义和错误处理状态机。

后续不再保留以下开放讨论项：

- 是否支持动态几何：否。
- 是否支持多类灯光：否。
- 是否支持纹理：否。
- 是否采用无缝零重建热切换：否。
- 是否需要修改 DisplaySystem：否。
- 是否允许把适配逻辑写进 vision/：否。
- 是否自动 fallback 到 native：否，Vision 失败保留上一帧并记录日志。
- 相机是否单独适配：**是**，作为第四个适配器（vision_camera_adapter）。
- 坐标系转换由谁负责：各适配器内部封装，主流程不感知。
- 切换请求传递机制：atomic 标志位，OpticsSystem 每帧前检查执行。
- 帧累积策略：逐帧增量累积，场景或相机变化时清空，首版不设上限。
- 材质映射规则：materialColor→baseColor，roughness→roughness，metallic→metallic，其余取 Vision 默认值。

首版唯一目标是：

- 在尽量不修改 Vision 内部逻辑的前提下，
- 通过 OpticsSystem 下的四个适配器（几何、光源、材质、相机）与输出桥接，
- 让 CoronaEngine 能在运行时切换并以 Vision 渲染模式驱动画面输出，
- 且这条主路径不再依赖外部 scene JSON。