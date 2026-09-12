from __future__ import annotations

import os
from pathlib import Path


def appdata_dir() -> Path:
    base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    path = base / "Dictation"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return appdata_dir() / "config.json"


def engine_dir() -> Path:
    path = appdata_dir() / "engine"
    path.mkdir(parents=True, exist_ok=True)
    return path


def models_dir() -> Path:
    path = appdata_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tmp_dir() -> Path:
    path = appdata_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return appdata_dir() / "dictation.log"
