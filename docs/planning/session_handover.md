---
name: session_handover_2026-05-12_v2
description: SSAT merge validation — updated findings, CUDA crash blocker, next steps
type: project
originSessionId: d3c61f93-5bc2-4daf-b2c5-f001e0648e5d
---
# SSAT Merge Validation — Session Handover v2 (2026-05-12)

## Goal
验证 SSAT denoiser 合并到 `change_horizon` 分支后行为未被修改。

Git 仓库：`D:\work\corona\Vision`，当前分支 `change_horizon`。

## 已完成验证

### 1. SSAT 模块加载 (RE-VERIFIED)
- `vision-denoiser-SSAT.dll` 存在于 `cmake-build-relwithdebinfo/bin/`
- 运行时加载成功：`vision-denoiser-ssat is take 4.05 ms`

### 2. Merge 变更审查 (VERIFIED)
Merge commit `9470be12c merge ssat` 的变更全部是 API 重命名：
- `Context` → `Toolkit` (类继承)
- `CommandList` → `CommandBatch` (类型重命名)
- `pipeline()->compute_surface_interaction()` → `pipeline()->geometry().compute_surface_interaction()`
- `float4` → `RadType4` (Vector<RadType, 4>，支持半精度)
- SVGF 变更：删除重复的 `set_enabled` 内联定义

受影响文件：`adaptive_sampler.h`, `sparse_gather.h`, `spatial_angular_filter.h`, `ssat.h`, `temporal_accumulator.h`, `svgf.h`
无算法逻辑修改。

### 3. SSAT 集成检查 (VERIFIED)
- PT integrator (`pt.cpp`) 正确处理 SSAT Phase 1/2/3 调度
- 支持 `SSAT_SKIP_PHASE2` / `SSAT_SKIP_PHASE3` 环境变量
- 所有 `compute_surface_interaction` 调用使用新 API：`pipeline()->geometry().compute_surface_interaction()`

## 阻塞问题

### CUDA build_accel 崩溃 (既存问题，非 SSAT 相关)
- **位置**: `src/base/mgr/geometry.cpp:67` — `rebuild_accel()` 中第一个 BLAS build
- **影响**: 所有渲染 (SVGF/SSAT, denoiser on/off) 均崩溃
- **已验证**:
  - `test-accel-update.exe` 成功构建 BLAS + TLAS → OptiX 本身工作正常
  - 相同崩溃发生在 `master` 和 `change_horizon` 分支
  - `--disable-denoiser` 无影响
- **环境**: RTX 3070 Ti, CUDA 13.1, OptiX 8.0, Driver 591.86
- **关键输出**: `vertex num is 72, triangle num is 36` → 然后 segfault
  - BLAS build 日志完全未出现 → 崩溃发生在第一个 BLAS 的 `optixAccelBuild` 或 `optixAccelComputeMemoryUsage`
  - 可能原因: 网格数据设置问题（bindless array buffer view 与直接创建 buffer 的差异）
  - `Geometry::upload()` 数据上传流与 `rebuild_accel()` BLAS 构建流之间的同步可能有问题
- **构建问题**: 从 bash 构建失败 (MSVC 环境问题)，无法重新编译调试

### 运行命令 (当 CUDA 问题修复后)
```bash
cd "D:/work/corona/CoronaTestScenes/test_vision/render_scene"
"D:/work/corona/Vision/cmake-build-relwithdebinfo/bin/vision-eval.exe" \
  -r "D:/work/corona/Vision/cmake-build-relwithdebinfo/bin" \
  -m cli \
  -s "D:/work/corona/CoronaTestScenes/test_vision/render_scene/cbox-lf/vision_scene_ssat.json" \
  --save-spp 1 --warmup-frames 4 --profile-frames 4 --stage-profile true \
  -o "D:/work/corona/Vision/eval-out/test_cbox_lf_ssat.png"
```

## 下一步
1. 解决 CUDA build_accel 崩溃（可能需要在 Visual Studio/CLion 中调试）
2. 运行单个场景 eval 验证 SSAT Phase 1/2/3 全部执行
3. 运行 ablation study 获取 RMSE 数据
4. 将 RMSE 与 `scene_targets.json` 中的 `rmse_target` 值对比

## 关键文件路径
- 测试场景（SSAT）：`D:\work\corona\CoronaTestScenes\test_vision\render_scene\cbox-lf\vision_scene_ssat.json`
- 场景目标配置：`D:\work\corona\Vision\tools\scene_targets.json`
- SSAT 源代码：`src/render_core/denoiser/SSAT/`
- 崩溃位置：`src/base/mgr/geometry.cpp:49-70` (rebuild_accel)
- Accel/OptiX：`src/Horizon/modules/ocarina/backends/cuda/optix_accel.cpp`
