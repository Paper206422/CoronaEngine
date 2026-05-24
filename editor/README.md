# Corona Engine Editor
- 此仓库为 Corona Engine 的编辑器
- 前端 Web：
	- 基于 Node.js（Vue + Tailwind）
	- 实现基于积木可视化编程（类似 Scratch），积木运行时转为 Python
- 后端/脚本层 Python：
	- 基于 MCP 接入大模型
	- 使用 PySide6 的 QWebEngineView 及 QDockWidget 搭建前端界面布局
- 底层 C++：
	- 支持 Python 层的热重载，保存文件自动更新 Python 代码逻辑
  
### 环境配置
- Editor 作为 CoronaEngine 的内置模块构建，不再维护独立的一键构建入口。
- Python 依赖由顶层 CMake 检查 `editor/requirements.txt`。
- 前端构建由顶层 CMake post-build 步骤触发，使用 `third_party/node-v22.19.0-win-x64` 中的 Node/npm。
- 程序入口为 `main.py`，运行时由引擎从 `CabbageEditor/` 目录加载。
- Blockly 生成脚本位于运行时的 `Backend/script/`。

