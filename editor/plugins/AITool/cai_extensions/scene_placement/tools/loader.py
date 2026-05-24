"""scene_placement 配置加载器（参考 three_d_generate 的 register_loader 风格）"""
from __future__ import annotations

from typing import Any, Mapping

from Quasar.ai_service.entrance import ai_entrance
from Quasar.ai_tools.helpers import _as_bool, _as_float  # type: ignore

from ..configs.dataclasses import ScenePlacementConfig



@ai_entrance.collector.register_loader("scene_placement")
def load_scene_placement_config(raw: Mapping[str, Any] | None) -> ScenePlacementConfig:
    if not isinstance(raw, Mapping):
        return ScenePlacementConfig()

    template = raw.get("template_scene_path")
    if not isinstance(template, str) or not template.strip():
        template = None

    return ScenePlacementConfig(
        asset_root=str(raw.get("asset_root") or "assets"),
        model_subdir=str(raw.get("model_subdir") or "model"),

        request_timeout=_as_float(raw.get("request_timeout"), 120.0),
        download_retries=int(raw.get("download_retries") or 2),
        download_resume=_as_bool(raw.get("download_resume"), True),
        download_unzip=_as_bool(raw.get("download_unzip"), True),

        layout_margin=_as_float(raw.get("layout_margin"), 0.5),
        layout_row_z=_as_float(raw.get("layout_row_z"), -1.0),

        template_scene_path=template,

        sun_direction_x=_as_float(raw.get("sun_direction_x"), -11.0),
        sun_direction_y=_as_float(raw.get("sun_direction_y"), 1.0),
        sun_direction_z=_as_float(raw.get("sun_direction_z"), 1.0),
    )
