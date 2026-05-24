# CabbageEditor 合并到 CoronaEngine 修改清单

## 当前迁移状态

CabbageEditor 已经不再位于 `editor/CabbageEditor/`，而是整体平铺到 `editor/` 下。当前 `editor/` 已包含原 CabbageEditor 的顶层内容，例如 `Frontend/`、`CoronaCore/`、`CoronaPlugin/`、`plugins/`、`config/`、`Env/`、`requirements.txt`、`main.py` 和 `build.py`。

因此，源码仓库内的“编辑器源目录”应从：

```text
editor/CabbageEditor
```

调整为：

```text
editor
```

但运行时构建输出目录仍可以继续保持：

```text
<exe_dir>/CabbageEditor
```

这是 C++ 运行时当前查找 Python 入口和前端资源的约定。也就是说，本次合并建议先只改“源码路径”，不要同时改运行时目录名，避免扩大影响面。

## 必须修改

### 1. CMake 编辑器源目录

文件：`misc/cmake/corona_editor.cmake`

当前仍收集旧目录：

```cmake
set(_CORONA_EDITOR_DIR "${PROJECT_SOURCE_DIR}/editor/CabbageEditor")
```

应改为：

```cmake
set(_CORONA_EDITOR_DIR "${PROJECT_SOURCE_DIR}/editor")
```

否则 `BUILD_CORONA_EDITOR=ON` 时，CMake 会提示找不到 CabbageEditor 源目录，后续不会把编辑器资源复制到示例可执行文件目录。

### 2. CMake Node 工具链路径

文件：`misc/cmake/corona_editor.cmake`

当前仍指向旧目录下的内置 Node：

```cmake
set(_CORONA_NODE_DIR "${PROJECT_SOURCE_DIR}/editor/CabbageEditor/Env/node-v22.19.0-win-x64")
```

应改为：

```cmake
set(_CORONA_NODE_DIR "${PROJECT_SOURCE_DIR}/editor/Env/node-v22.19.0-win-x64")
```

否则 post-build 的 `npm install` / `npm run build` 会因为找不到 `npm.cmd` 而跳过或失败。

### 3. Python requirements 路径

文件：`misc/cmake/corona_python.cmake`

当前仍检查旧路径：

```cmake
set(CORONA_PY_REQUIREMENTS_FILE "${PROJECT_SOURCE_DIR}/editor/CabbageEditor/requirements.txt")
```

应改为：

```cmake
set(CORONA_PY_REQUIREMENTS_FILE "${PROJECT_SOURCE_DIR}/editor/requirements.txt")
```

否则 CMake 配置阶段的 Python 依赖检查会找不到 requirements 文件。

### 4. 脚本系统的源码 Backend 路径

文件：`src/systems/script/python/python_path_config.cpp`

当前源码侧 backend 路径是：

```cpp
static const std::string rel = "Editor/CabbageEditor/Backend";
```

从当前 `editor/` 结构看，仓库内并没有固定提交的 `Backend/` 顶层目录，历史代码中实际 Python 根已经是 `editor/` 本身，Blockly 相关代码会在运行时生成 `editor/Backend/` 下的脚本。因此这里应改成源码根：

```cpp
static const std::string rel = "editor";
```

`copyModifiedFiles(sourcePath, runtimePath, ...)` 会递归复制最近修改的 `.py` 文件。源码根使用 `editor` 才能覆盖 `CoronaCore/`、`CoronaPlugin/`、`plugins/` 和运行时生成的 `Backend/`；运行时目录仍由 `runtime_backend_abs()` 指向 `<cwd>/CabbageEditor`。

注意大小写：当前代码写的是 `Editor/...`，仓库目录是 `editor/...`。Windows 下通常不暴露问题，但跨平台会失败。

### 5. 顶层或 editor 的忽略规则

文件：`.gitignore` 与 `editor/.gitignore`

当前 `editor/.gitignore` 能覆盖 Python 缓存、`node_modules/`、`dist/`、`build/` 等常规产物。合并后建议再确认以下内容是否应由仓库管理：

```text
editor/Env/
editor/Frontend/package-lock.json
editor/Frontend/dist/
editor/Frontend/node_modules/
editor/autosave/
editor/media/
editor/models/
editor/screenshots/
```

建议策略：

- 如果 `Env/node-v22.19.0-win-x64` 是项目必需的离线 Node 工具链，保留跟踪或改为构建脚本自动下载，二选一。
- `Frontend/dist/` 如果由 CMake post-build 构建并复制，不建议提交。
- `package-lock.json` 如果团队需要可重复前端构建，建议取消忽略并提交；如果依赖漂移可接受，则继续忽略。
- `autosave/`、`media/`、`models/`、`screenshots/` 属于运行时或项目数据，建议忽略。

## 建议修改

### 1. 更新文档中的旧路径

以下文档此前出现过 `editor/CabbageEditor`，本轮已按源码新位置更新：

```text
docs/AI_FRONTEND_CHAIN_AND_CAI_GENERALIZATION_cn.md
.github/skills/input-pipeline-refactor/SKILL.md
.github/skills/input-pipeline-refactor/references/*.md
editor/plugins/AITool/cai_extensions/*.py 的 docstring
```

这类引用不会直接阻塞构建，但会误导后续开发。统一改为 `editor/`，例如：

```text
editor/plugins/AITool/CoronaArtificialIntelligence
editor/Frontend/src/utils/bridge.js
editor/plugins/
```

### 2. 更新 CabbageEditor 自身 README

文件：`editor/README.md`

当前 README 仍写着 Python 入口为 `Backend/main.py`，但实际当前入口是 `editor/main.py`，且 `Backend/` 更多像 Blockly 生成脚本运行包。

建议改成：

```text
Python 入口：editor/main.py
前端目录：editor/Frontend
插件目录：editor/plugins
Blockly 生成脚本目录：运行时/开发时的 Backend/script
```

### 3. 收敛命名：源码目录叫 editor，运行包叫 CabbageEditor

建议在文档和 CMake 注释里明确两个概念：

- 源码目录：`PROJECT_SOURCE_DIR/editor`
- 运行时目录：`$<TARGET_FILE_DIR>/CabbageEditor`

这样可以暂时兼容 C++ 运行时：

```cpp
sys.path.insert(0, os.path.join(os.getcwd(), 'CabbageEditor'))
```

如果后续想把运行时目录也改成 `editor`，需要同步改 C++、CMake、Python 配置和已有构建产物目录，影响面更大。

### 4. 保持 CAI submodule 路径一致

当前 `editor/.gitmodules` 中 submodule 路径为：

```text
plugins/AITool/CoronaArtificialIntelligence
```

这是相对于 `editor/` 的路径。如果顶层 CoronaEngine 负责管理 submodule，需要决定：

- 保留 `editor/.gitmodules`，把 `editor/` 视作带内部 submodule 的嵌入项目。
- 或迁移到顶层 `.gitmodules`，路径改为 `editor/plugins/AITool/CoronaArtificialIntelligence`。

本轮采用第二种，同时暂时保留 `editor/.gitmodules`，用于保留 editor 归档目录的独立上下文。这样可以从 CoronaEngine 根目录执行：

```powershell
git submodule update --init --recursive
```

### 5. 检查 CMake 复制脚本的忽略列表

文件：`misc/pytools/editor_copy_and_build.py`

当前复制脚本会忽略：

```text
requirements.txt
README.md
docs
tests
package-lock.json
```

如果运行时需要 `requirements.txt` 做诊断或需要附带某些文档/测试资源，应调整忽略列表。通常运行包不需要这些文件，可以保持现状。

## 暂不建议修改

### 1. 暂不修改运行时目录名 `CabbageEditor`

以下位置仍依赖运行时目录名：

```text
misc/cmake/corona_editor.cmake
src/systems/ui/cef/cef_query_bridge.cpp
src/systems/script/python/python_path_config.cpp
misc/pytools/editor_copy_and_build.py 注释和参数说明
```

只要 CMake 继续把 `editor/` 内容复制到 `<exe_dir>/CabbageEditor/`，这些运行时约定可以继续成立。改运行时目录名属于第二阶段迁移。

### 2. 暂不移动 `plugins/AITool/CoronaArtificialIntelligence`

已有 AI 通用化文档明确建议不要移动 CAI submodule。本轮只更新它的相对源码路径说明：从 `editor/CabbageEditor/plugins/...` 更新为 `editor/plugins/...`。

## 建议验证步骤

### 1. 搜索旧源码路径

```powershell
Get-ChildItem -Recurse -File |
	Where-Object { $_.FullName -notmatch '\\build\\|\\third_party\\' } |
	Select-String -Pattern 'editor/CabbageEditor','Editor/CabbageEditor'
```

预期：除历史说明或归档文档外，不应再有会参与构建/运行的旧路径。

### 2. 重新配置 CMake

```powershell
cmake --preset ninja-msvc
```

重点确认：

- 不再出现 `CabbageEditor directory not found: .../editor/CabbageEditor`。
- Python requirements 检查使用 `.../editor/requirements.txt`。

### 3. 构建示例目标

```powershell
cmake --build --preset msvc-debug
```

重点确认：

- post-build 会把 `editor/` 内容复制到 `build/.../<target>/CabbageEditor/`。
- `Frontend/dist/index.html` 被生成或已存在。
- 构建日志中 `npm.cmd` 路径来自 `editor/Env/node-v22.19.0-win-x64`。

### 4. 运行时 smoke test

从可执行文件目录启动示例，确认：

- C++ 能 import Python `main`。
- `CoronaEditor.open_browser()` 能找到 `CabbageEditor/Frontend/dist/index.html`。
- 插件加载器能扫描 `CabbageEditor/plugins/*/main.py`。
- AITool 能 import `CoronaArtificialIntelligence` 和 `cai_extensions`。

### 5. Python 侧最小导入检查

在 `editor/` 下执行：

```powershell
Set-Location editor
python -c "import main; from CoronaCore.core.corona_editor import CoronaEditor; from CoronaPlugin.utils.settings import core_path; print(core_path.repo_root); print(core_path.frontend_dist)"
```

预期 `core_path.repo_root` 指向 `.../CoronaEngine/editor`。

## 推荐落地顺序

1. [x] 先改 `misc/cmake/corona_editor.cmake` 和 `misc/cmake/corona_python.cmake`，恢复配置与构建。
2. [x] 再处理 `src/systems/script/python/python_path_config.cpp` 的源码路径大小写和旧目录。
3. [ ] 运行 CMake configure/build，确认编辑器能复制到运行时 `CabbageEditor/`。
4. [x] 根据构建产物情况调整 `.gitignore`。
5. [x] 最后批量更新文档与 `.github/skills` 中的旧路径。
