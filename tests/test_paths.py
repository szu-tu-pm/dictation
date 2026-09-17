from pathlib import Path

from dictation.paths import (
    appdata_dir,
    config_path,
    engine_dir,
    log_path,
    models_dir,
    tmp_dir,
)


def test_appdata_dir_from_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = appdata_dir()
    assert d == tmp_path / "Dictation"
    assert d.is_dir()


def test_paths_subdirectories(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    base = appdata_dir()
    assert engine_dir() == base / "engine"
    assert engine_dir().is_dir()
    assert models_dir() == base / "models"
    assert models_dir().is_dir()
    assert tmp_dir() == base / "tmp"
    assert tmp_dir().is_dir()
    assert config_path() == base / "config.json"
    assert log_path() == base / "dictation.log"


def test_appdata_dir_fallback_without_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    d = appdata_dir()
    assert d == tmp_path / "AppData" / "Roaming" / "Dictation"
    assert d.is_dir()