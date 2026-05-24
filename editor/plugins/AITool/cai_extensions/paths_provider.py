"""CAI 路径解析器的宿主实现。

转发到 ``editor/config/paths_config`` 中已有的实现，
不在此处重复编辑器/引擎逻辑。
"""

from __future__ import annotations

from pathlib import Path

from Quasar.ai_config.paths_config import PathsConfig


class CabbageEditorPathsResolver:
    """实现 CAI 的 ``PathsResolver`` 协议（duck typing）。"""

    def get_active_project_path(self) -> Path:
        from config.paths_config import _get_active_project_path
        return _get_active_project_path()

    def get_project_media_dir(self) -> Path:
        from config.paths_config import get_project_media_dir
        return get_project_media_dir()

    def get_project_models_dir(self) -> Path:
        from config.paths_config import get_project_models_dir
        return get_project_models_dir()

    def get_project_screenshots_dir(self) -> Path:
        from config.paths_config import get_project_screenshots_dir
        return get_project_screenshots_dir()

    def get_project_recognition_db(self) -> Path:
        from config.paths_config import get_project_recognition_db
        return get_project_recognition_db()

    def get_default_paths(self) -> PathsConfig:
        from config.paths_config import get_default_paths
        editor_paths = get_default_paths()
        # 编辑器侧的 PathsConfig 与 CAI 的同名 dataclass 字段一致，
        # 通过 dict 转换回 CAI 自己的类型，避免 isinstance 不匹配。
        return PathsConfig(
            repo_root=editor_paths.repo_root,
            backend_root=editor_paths.backend_root,
            frontend_dist=editor_paths.frontend_dist,
            script_dir=editor_paths.script_dir,
            autosave_dir=editor_paths.autosave_dir,
            config_dir=editor_paths.config_dir,
            assets_model_dir=editor_paths.assets_model_dir,
            object_recognition_db=editor_paths.object_recognition_db,
            screenshots_dir=getattr(editor_paths, "screenshots_dir", None),
            media_local_storage=getattr(editor_paths, "media_local_storage", None),
        )
