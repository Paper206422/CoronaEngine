"""CAI app_config provider 的宿主实现。

转发到 ``editor/config/app_config.get_app_config``。
"""

from __future__ import annotations

from typing import Any


def get_app_config_for_cai() -> Any:
    """供 CAI ``warmup`` 流程预热用。"""
    from config.app_config import get_app_config
    return get_app_config()
