"""scene_placement 默认配置（参考 three_d_generate 的 register_setting 风格）"""
from __future__ import annotations

from typing import Any, Dict

from Quasar.ai_service.entrance import ai_entrance


@ai_entrance.collector.register_setting("scene_placement")
def SCENE_PLACEMENT_SETTINGS() -> Dict[str, Any]:
    return {
        "asset_root": "assets",
        "model_subdir": "model",

        "request_timeout": 120.0,
        "download_retries": 2,
        "download_resume": True,
        "download_unzip": True,

        # deterministic layout params
        "layout_margin": 0.5,
        "layout_row_z": -1.0,

        # 可选：指定模板 scene.json（建议放到你项目可访问的绝对路径/相对路径）
        # 例如: "F:/.../场景1.json"
        "template_scene_path": None,

        "sun_direction_x": -11.0,
        "sun_direction_y": 1.0,
        "sun_direction_z": 1.0,
    }
