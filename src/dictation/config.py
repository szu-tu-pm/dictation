from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from dictation.paths import config_path


ENGINE_ZIP_URL = (
    "https://github.com/eviscerations/whisper-windows-mcp/releases/"
    "download/v1.4.0/whisper-vulkan-win-x64.zip"
)
MODEL_FILENAME = "ggml-large-v3-turbo.bin"
MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    + MODEL_FILENAME
)


@dataclass
class AppConfig:
    hotkey: str = "rctrl"
    model: str = "large-v3-turbo"
    language: str = "en"
    device: int | None = None
    sample_rate: int = 16000
    # Must cover hold_ms classification delay so the first syllable is kept.
    preroll_ms: int = 350
    suffix_ms: int = 80
    min_hold_ms: int = 200
    energy_threshold: float = 0.008
    ring_seconds: float = 30.0
    max_record_seconds: float = 60.0
    continuous_max_seconds: float = 120.0
    hold_ms: int = 250
    double_tap_ms: int = 350
    engine_url: str = ENGINE_ZIP_URL
    model_url: str = MODEL_URL
    model_filename: str = MODEL_FILENAME
    sound_effects: bool = True


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    if not isinstance(raw, dict):
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    allowed = {f.name for f in fields(AppConfig)}
    filtered = {k: v for k, v in raw.items() if k in allowed}
    return AppConfig(**filtered)


def save_config(cfg: AppConfig) -> Path:
    path = config_path()
    path.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")
    return path
