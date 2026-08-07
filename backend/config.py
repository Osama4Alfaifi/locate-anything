"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

VALID_MODES = ("fast", "hybrid", "slow")


def _as_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    mock: bool
    model_path: str
    default_mode: str
    data_dir: str
    device: int
    max_clip_seconds: float
    max_upload_mb: float
    sample_fps: float
    max_search_frames: int


def _as_float(value: str | None, default: float) -> float:
    try:
        return float(value) if value else default
    except ValueError:
        return default


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


@lru_cache
def get_settings() -> Settings:
    mode = os.environ.get("LA_DEFAULT_MODE", "hybrid").strip().lower()
    if mode not in VALID_MODES:
        mode = "hybrid"
    try:
        device = int(os.environ.get("LA_DEVICE", "0"))
    except ValueError:
        device = 0
    return Settings(
        mock=_as_bool(os.environ.get("LA_MOCK")),
        model_path=os.environ.get("LA_MODEL_PATH", "nvidia/LocateAnything-3B"),
        default_mode=mode,
        data_dir=os.environ.get("LA_DATA_DIR", "./data"),
        device=device,
        max_clip_seconds=_as_float(os.environ.get("LA_MAX_CLIP_SECONDS"), 120.0),
        max_upload_mb=_as_float(os.environ.get("LA_MAX_UPLOAD_MB"), 200.0),
        sample_fps=_as_float(os.environ.get("LA_SAMPLE_FPS"), 2.0),
        max_search_frames=_as_int(os.environ.get("LA_MAX_SEARCH_FRAMES"), 150),
    )
