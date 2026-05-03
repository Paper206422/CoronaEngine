# CoronaEngine

CoronaEngine 是一个模块化、多线程、数据驱动的 C++ 游戏引擎，构建在 CoronaFramework 的 `KernelContext` 之上，采用系统化架构组织渲染、几何、运动学、力学、声学、脚本和 UI 等能力。

## 文档入口

- 一页式总览：`docs/ONE_PAGE_OVERVIEW_cn.md`
- 5 分钟上手：`docs/QUICK_START_cn.md`
- 架构图速览：`docs/ARCHITECTURE_MAP_cn.md`
- 项目总览：`docs/PROJECT_SUMMARY_cn.md`
- 系统职责总览：`docs/SYSTEMS_OVERVIEW_cn.md`
- 数据流总览：`docs/DATA_FLOW_OVERVIEW_cn.md`
- 源码阅读索引：`docs/SOURCE_INDEX_cn.md`
- Python API 存储映射：`docs/PYTHON_API_STORAGE_MAPPING_cn.md`
- 能力状态清单：`docs/CAPABILITY_STATUS_cn.md`
- 现状问题与改进建议：`docs/ISSUES_AND_RECOMMENDATIONS_cn.md`
- 开发者指南：`docs/DEVELOPER_GUIDE_cn.md`
- 架构指南：`docs/ARCHITECTURE_cn.md`
- CMake 构建指南：`docs/CMAKE_GUIDE_cn.md`
- 代码风格指南：`docs/CODE_STYLE_cn.md`
- Python API 示例：`docs/PYTHON_API_EXAMPLES.md`

## 当前状态

- 核心入口位于 `src/engine.cpp` 和 `include/corona/engine.h`
- 当前已注册系统包括 `display`、`optics`、`geometry`、`kinematics`、`mechanics`、`acoustics`、`script`、`ui`
- 项目使用 `CMakePresets.json` 管理跨平台构建配置

## 快速构建

Windows + MSVC + Ninja：

```powershell
cmake --preset ninja-msvc
cmake --build --preset msvc-debug
```

第一次进入仓库，建议先看 `docs/ONE_PAGE_OVERVIEW_cn.md` 和 `docs/QUICK_START_cn.md`。