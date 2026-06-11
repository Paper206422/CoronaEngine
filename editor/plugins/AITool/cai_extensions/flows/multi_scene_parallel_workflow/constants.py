"""
Multi-Scene Parallel Generation — 常量与工具函数
"""
from __future__ import annotations

import hashlib
import re

# 多场景并行工作流 function_id
PARALLEL_GENERATE_FUNCTION_ID = 21004
PARALLEL_GENERATE_V2_FUNCTION_ID = 21008  # 使用 scene_composition_v2

# 单次请求最多并发的子场景数
# 限制为 2：Vulkan 引擎长时间运行 (>15min) 会出现 timeline semaphore 溢出崩溃
MAX_PARALLEL_SCENES = 2

# 分层超时（秒）
TIMEOUTS = {
    "llm_call": 30,
    "image_gen": 120,
    "model_gen_per_item": 300,
    "scene_import": 60,
    "single_scene_total": 1800,
    "parallel_overall": 3600,
}

# Checkpoint 保存字段 — 恢复 Phase 2 的最小集合（排除 bytes、C++ 对象、messages）
CHECKPOINT_SCHEMA = {
    "child_session", "scene_name", "output_dir",
    "local_mesh_paths", "scene_center", "camera_distance",
}

CHECKPOINT_VERSION = "1.0"


def make_child_session_id(parent: str, scene_name: str, index: int) -> str:
    """
    生成子场景 session_id。

    格式: {parent}___{index:02d}___{safe_name}___{hash[:6]}
    - index: 保证确定性唯一（即使两个场景 scene_name 完全相同）
    - safe_name: 清洗后的 ASCII 片段（可读性）
    - hash: 原始 scene_name 的 md5 前 6 位（防止清洗后重名）
    """
    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', scene_name)[:16]
    name_hash = hashlib.md5(scene_name.encode('utf-8')).hexdigest()[:6]
    return f"{parent}___{index:02d}___{safe_name}___{name_hash}"
