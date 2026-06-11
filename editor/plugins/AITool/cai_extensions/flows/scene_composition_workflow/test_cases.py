"""scene_composition 工作流测试入口。

使用方法:
    在 Agent 对话框直接输入：

        /scene_composition --test          (v1)
        /sc_v2 --test                     (v2)

    或在引擎 Python 控制台调用：

        from cai_extensions.flows.scene_composition_workflow.test_cases import run_test_v2, discover_models

        # 查看已有模型
        models = discover_models("E:/corona/document/test0528/models")

        # 直接跑 v2 组装 (跳过 3D 生成)
        run_test_v2(stream=True)                              # 用 DEFAULT_MODELS
        run_test_v2(models=models[:5], prompt="新中式客厅")   # 指定模型
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 默认测试模型（修改为你本地实际存在的路径） ──────────────────────────

# 新中式小客厅 (5件, 上次测试用)
TEST0528_MODELS_V1: List[Dict[str, str]] = [
    {"name": "胡桃木新中式圈椅沙发",   "path": "E:/corona/document/test0528/models/hunyuan_20260529_122533/base.glb"},
    {"name": "黑檀木新中式方形茶几",   "path": "E:/corona/document/test0528/models/hunyuan_20260529_122810/base.glb"},
    {"name": "实木格栅新中式电视柜",   "path": "E:/corona/document/test0528/models/hunyuan_20260529_122511/base.glb"},
    {"name": "宣纸竹编新中式落地灯",   "path": "E:/corona/document/test0528/models/hunyuan_20260529_122505/base.glb"},
    {"name": "水墨山水新中式装饰挂画", "path": "E:/corona/document/test0528/models/hunyuan_20260529_122717/base.glb"},
]

# 北欧极简客厅 (8件, 全落地物体, 无限挂墙问题)
TEST0528_MODELS: List[Dict[str, str]] = [
    {"name": "浅灰亚麻布艺紧凑L型沙发", "path": "E:/corona/document/test0528/models/浅灰亚麻布艺紧凑L型沙发/base.obj"},
    {"name": "浅橡木极简咖啡桌",         "path": "E:/corona/document/test0528/models/浅橡木极简咖啡桌/base.glb"},
    {"name": "悬空极简灰橡木电视柜",     "path": "E:/corona/document/test0528/models/悬空极简灰橡木电视柜/base.glb"},
    {"name": "极简黄铜落地灯",           "path": "E:/corona/document/test0528/models/极简黄铜落地灯/base.obj"},
    {"name": "哑光陶瓷球形台灯",         "path": "E:/corona/document/test0528/models/哑光陶瓷球形台灯/base.glb"},
    {"name": "黑色金属极简落地灯",       "path": "E:/corona/document/test0528/models/黑色金属极简落地灯/base.glb"},
    {"name": "浅橡木实木小圆几",         "path": "E:/corona/document/test0528/models/浅橡木实木小圆几/base.obj"},
    {"name": "灰白色手工羊毛区域地毯",   "path": "E:/corona/document/test0528/models/灰白色手工羊毛区域地毯/base.glb"},
]

DEFAULT_MODELS: List[Dict[str, str]] = TEST0528_MODELS

# 默认设计方案
DEFAULT_PROMPT = (
    "北欧极简客厅。房间尺寸为 5m（X）×3m（Z），天花板高度 3m。"
    "浅灰亚麻布艺紧凑L型沙发靠后墙放置，面向房间中心。"
    "浅橡木极简咖啡桌在沙发前方居中。"
    "悬空极简灰橡木电视柜靠后墙，与沙发相对。"
    "极简黄铜落地灯放在沙发一侧作为阅读照明。"
    "哑光陶瓷球形台灯放在咖啡桌或边桌上作为氛围照明。"
    "黑色金属极简落地灯放在电视柜旁或房间另一侧。"
    "浅橡木实木小圆几作为沙发旁的边桌。"
    "灰白色手工羊毛区域地毯铺在沙发和咖啡桌下方区域。"
)


def discover_models(models_dir: str) -> List[Dict[str, str]]:
    """扫描模型目录，返回 {name, path} 列表。

    每个子目录视为一个模型，取其中的 base.glb。
    目录名即为模型名。
    """
    root = Path(models_dir)
    if not root.is_dir():
        logger.warning("discover_models: 目录不存在: %s", models_dir)
        return []

    found = []
    for subdir in sorted(root.iterdir()):
        if not subdir.is_dir():
            continue
        glb = subdir / "base.glb"
        if glb.exists():
            found.append({"name": subdir.name, "path": str(glb)})
        else:
            # 查找目录下任意 .glb 文件
            glbs = list(subdir.glob("*.glb"))
            if glbs:
                found.append({"name": subdir.name, "path": str(glbs[0])})

    logger.info("discover_models: 在 %s 找到 %d 个模型", models_dir, len(found))
    return found


def build_test_state(
    models: Optional[List[Dict[str, str]]] = None,
    *,
    session_id: str = "test-scene-composition",
    scene_name: str = "test_scene",
    room_size: Optional[List[float]] = None,
    prompt: str = "",
    function_id: int = 21003,
) -> Dict[str, Any]:
    """构造可直接传入 scene_composition 工作流的初始 state。

    Args:
        models: 模型列表，每项需包含 ``name`` 和 ``path``。
        session_id: 会话 ID。
        scene_name: 输出场景名称。
        room_size: 房间尺寸 [X_length, Z_depth, Y_height]，默认 [10, 10, 3]。
        prompt: 设计方案描述。
        function_id: 工作流 ID (21003=v1, 21006=v2)。
    """
    items = models or DEFAULT_MODELS
    if not items:
        raise ValueError(
            "models 为空，请传入至少一个模型。示例:\n"
            '  run_test_v2(models=[{"name": "椅子", "path": "D:/path/to/椅子.glb"}])'
        )

    model_results = []
    for i, m in enumerate(items, 1):
        model_results.append({
            "item_name": m["name"],
            "object_id": m.get("object_id", m["name"]),
            "task_index": i,
            "source": "generation",
            "model_path": m["path"],
            "review_passed": True,
        })

    return {
        "session_id": session_id,
        "function_id": function_id,
        "prompt": prompt,
        "global_assets": {
            "model_retrieval": {
                "model_results": model_results,
            },
        },
        "intermediate": {},
        "metadata": {
            "scene_name": scene_name,
            "room_size": room_size or [10, 10, 3],
        },
    }


def run_test(
    models: Optional[List[Dict[str, str]]] = None,
    *,
    session_id: str = "test-scene-composition",
    scene_name: str = "test_scene",
    room_size: Optional[List[float]] = None,
    prompt: str = "",
    stream: bool = False,
) -> Any:
    """直接执行 scene_composition v1 工作流。"""
    state = build_test_state(
        models,
        session_id=session_id,
        scene_name=scene_name,
        room_size=room_size,
        prompt=prompt or DEFAULT_PROMPT,
        function_id=21003,
    )

    from . import build_scene_composition_workflow

    graph = build_scene_composition_workflow()

    if stream:
        logger.info("=== scene_composition v1 流式测试开始 ===")
        for chunk in graph.stream(state, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                error = node_update.get("error") if isinstance(node_update, dict) else None
                if error:
                    logger.error("[%s] 错误: %s", node_name, error)
                else:
                    logger.info("[%s] 完成", node_name)
        logger.info("=== scene_composition v1 流式测试结束 ===")
        return None

    logger.info("=== scene_composition v1 测试开始 ===")
    final_state = graph.invoke(state)
    error = final_state.get("error")
    if error:
        logger.error("工作流失败: %s", error)
    else:
        intermediate = final_state.get("intermediate", {})
        scene_path = intermediate.get("scene_json_path", "未知")
        imported = intermediate.get("imported_actors", [])
        failed = intermediate.get("failed_actors", [])
        logger.info(
            "工作流完成: scene_path=%s, 导入成功=%d, 导入失败=%d",
            scene_path, len(imported), len(failed),
        )
    logger.info("=== scene_composition v1 测试结束 ===")
    return final_state


def run_test_v2(
    models: Optional[List[Dict[str, str]]] = None,
    *,
    session_id: str = "test-sc-v2",
    scene_name: str = "test_scene_v2",
    room_size: Optional[List[float]] = None,
    prompt: str = "",
    stream: bool = True,
) -> Any:
    """直接执行 scene_composition v2 工作流 (跳过 3D 生成)。

    在引擎 Python 控制台调用:

        from cai_extensions.flows.scene_composition_workflow.test_cases import run_test_v2, discover_models

        # 用默认模型测试
        run_test_v2(stream=True)

        # 从模型目录挑选
        models = discover_models("E:/corona/document/test0528/models")
        run_test_v2(models=models[:5], prompt="新中式小客厅", stream=True)

    Args:
        models: 模型列表, 每项 {"name": "...", "path": "..."}。默认用 DEFAULT_MODELS。
        session_id: 会话 ID。
        scene_name: 输出场景名称。
        room_size: 房间尺寸 [X, Z, Y], 默认 [5, 3, 3]。
        prompt: 设计方案描述, 为空则用 DEFAULT_PROMPT。
        stream: 流式输出节点进度。
    """
    state = build_test_state(
        models,
        session_id=session_id,
        scene_name=scene_name,
        room_size=room_size or [5, 3, 3],
        prompt=prompt or DEFAULT_PROMPT,
        function_id=21006,
    )

    from ..scene_composition_workflow_v2 import build_scene_composition_v2_workflow

    graph = build_scene_composition_v2_workflow()

    if stream:
        logger.info("=== scene_composition v2 流式测试开始 ===")
        for chunk in graph.stream(state, stream_mode="updates"):
            for node_name, node_update in chunk.items():
                if not isinstance(node_update, dict):
                    continue
                error = node_update.get("error")
                if error:
                    logger.error("[%s] 错误: %s", node_name, error)
                else:
                    intermediate = node_update.get("intermediate", {})
                    decision = intermediate.get("tier1_review_decision") or intermediate.get("tier2_review_decision") or intermediate.get("tier3_review_decision")
                    tier_info = ""
                    for t in [1, 2, 3]:
                        items_key = f"tier{t}_items"
                        if items_key in intermediate:
                            tier_info += f" t{t}={len(intermediate[items_key])}件"
                    logger.info("[%s] 完成%s decision=%s", node_name, tier_info, decision or "N/A")
        logger.info("=== scene_composition v2 流式测试结束 ===")
        return None

    logger.info("=== scene_composition v2 测试开始 ===")
    final_state = graph.invoke(state)
    error = final_state.get("error")
    if error:
        logger.error("v2 工作流失败: %s", error)
    else:
        intermediate = final_state.get("intermediate", {})
        scene_path = intermediate.get("scene_json_path", "未知")
        logger.info("v2 工作流完成: scene_path=%s", scene_path)
    logger.info("=== scene_composition v2 测试结束 ===")
    return final_state
