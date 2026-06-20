"""Compatibility wrapper for shared asset metadata helpers."""

from ..shared.asset_metadata import (
    build_asset_metadata,
    build_asset_metadata_batch,
    load_asset_metadata_cache,
)

__all__ = [
    "build_asset_metadata",
    "build_asset_metadata_batch",
    "load_asset_metadata_cache",
]
