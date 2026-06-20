from __future__ import annotations

import os

from scene_composer import SceneComposer


def test_scene_composer_discloses_model_and_substrate_summary() -> None:
    old = os.environ.get("CORONA_DISABLE_INVENTORY_EXPANSION")
    os.environ["CORONA_DISABLE_INVENTORY_EXPANSION"] = "1"
    try:
        composer = SceneComposer(scene_name="routing_test", max_items=8)
        composer._llm_extract = lambda _text: [  # type: ignore[method-assign]
            {"name": "床", "keywords": "cute bed"},
            {"name": "木地板", "keywords": "wood floor"},
            {"name": "天空", "keywords": "sky"},
            {"name": "入口", "keywords": "entrance"},
            {"name": "小夜灯", "keywords": "night lamp"},
        ]
        composer.decompose_zone_tree = lambda _text: None  # type: ignore[method-assign]
        composer._run_model_retrieval = lambda _items: []  # type: ignore[method-assign]
        progress: list[str] = []
        result = composer.compose("做一个可爱卧室，有木地板、天空背景、入口、床和小夜灯", progress_sink=progress.append)
    finally:
        if old is None:
            os.environ.pop("CORONA_DISABLE_INVENTORY_EXPANSION", None)
        else:
            os.environ["CORONA_DISABLE_INVENTORY_EXPANSION"] = old

    assert result.get("error")
    summary = "\n".join(progress)
    assert "准备生成模型：床、小夜灯" in summary
    assert "环境/地形：木地板、天空" in summary
    assert "布局结构：入口" in summary
    assert "木地板" not in [item["name"] for item in result["items"]]
    assert "天空" not in [item["name"] for item in result["items"]]


if __name__ == "__main__":
    test_scene_composer_discloses_model_and_substrate_summary()
    print("[OK] SceneComposer discloses model/substrate/layout summary")
    print("\n=== SceneComposer element routing ALL PASS ===")
