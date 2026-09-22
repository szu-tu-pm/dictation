from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from dictation.fileutil import atomic_write_text, try_quarantine
from dictation.logutil import LOG
from dictation.paths import config_path


ENGINE_ZIP_URL = (
    "https://github.com/eviscerations/whisper-windows-mcp/releases/"
    "download/v1.4.0/whisper-vulkan-win-x64.zip"
)
# GitHub release asset digest for v1.4.0 whisper-vulkan-win-x64.zip
ENGINE_ZIP_SHA256 = "8913366b0d97764767bacaf73b23e433563ab97dee6ce9550460a54215669ddb"
MODEL_FILENAME = "ggml-large-v3-turbo.bin"
MODEL_URL = (
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
    + MODEL_FILENAME
)
# Hugging Face LFS oid for ggml-large-v3-turbo.bin
MODEL_SHA256 = "1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"


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
    energy_threshold: float = 0.002
    ring_seconds: float = 30.0
    max_record_seconds: float = 60.0
    continuous_max_seconds: float = 120.0
    hold_ms: int = 250
    double_tap_ms: int = 350
    hud_enabled: bool = True
    engine_url: str = ENGINE_ZIP_URL
    engine_sha256: str = ENGINE_ZIP_SHA256
    model_url: str = MODEL_URL
    model_filename: str = MODEL_FILENAME
    model_sha256: str = MODEL_SHA256
    sound_effects: bool = True


def _recover_defaults(path: Path, reason: str) -> AppConfig:
    LOG.warning("config %s (%s); using defaults", path, reason)
    try_quarantine(path, "config")
    cfg = AppConfig()
    save_config(cfg)
    return cfg


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        cfg = AppConfig()
        save_config(cfg)
        return cfg
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _recover_defaults(path, f"invalid JSON: {exc}")
    except OSError as exc:
        return _recover_defaults(path, f"read error: {exc}")
    if not isinstance(raw, dict):
        return _recover_defaults(path, "JSON root is not an object")
    allowed = {f.name for f in fields(AppConfig)}
    filtered = {k: v for k, v in raw.items() if k in allowed}
    return AppConfig(**filtered)


def save_config(cfg: AppConfig) -> Path:
    path = config_path()
    atomic_write_text(path, json.dumps(asdict(cfg), indent=2) + "\n")
    return path
