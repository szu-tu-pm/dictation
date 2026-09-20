from pathlib import Path
from unittest.mock import patch

import pytest

from dictation.config import AppConfig, load_config, save_config
from dictation.fileutil import atomic_write_text, quarantine_corrupt
from dictation.paths import appdata_dir, config_path


def test_load_save_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = AppConfig(language="en", preroll_ms=250)
    path = save_config(cfg)
    assert path == tmp_path / "Dictation" / "config.json"
    loaded = load_config()
    assert loaded.language == "en"
    assert loaded.preroll_ms == 250
    assert loaded.hotkey == "rctrl"
    assert loaded.engine_sha256
    assert loaded.model_sha256


def test_load_ignores_unknown_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    appdata_dir()
    config_path().write_text('{"language": "en", "not_a_field": 1}\n', encoding="utf-8")
    loaded = load_config()
    assert loaded.language == "en"
    assert loaded.sample_rate == 16000


def test_load_creates_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    loaded = load_config()
    assert loaded.model == "large-v3-turbo"
    assert loaded.max_record_seconds == 60.0
    assert loaded.continuous_max_seconds == 120.0
    assert loaded.hold_ms == 250
    assert loaded.double_tap_ms == 350
    assert loaded.preroll_ms == 350
    assert loaded.hud_enabled is True
    assert config_path().is_file()


def test_load_recovers_corrupt_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    appdata_dir()
    path = config_path()
    path.write_text("{not-json", encoding="utf-8")
    loaded = load_config()
    assert loaded.max_record_seconds == 60.0
    assert '"max_record_seconds"' in path.read_text(encoding="utf-8")
    bak = path.with_name(path.name + ".bak")
    assert bak.is_file()
    assert bak.read_text(encoding="utf-8") == "{not-json"


def test_load_recovers_non_dict(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    appdata_dir()
    path = config_path()
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    loaded = load_config()
    assert loaded.hotkey == "rctrl"
    assert path.with_name(path.name + ".bak").is_file()


def test_save_config_atomic(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = AppConfig(language="fr")
    with patch("dictation.config.atomic_write_text", wraps=atomic_write_text) as mock_atomic:
        save_config(cfg)
        assert mock_atomic.called
    assert load_config().language == "fr"


def test_quarantine_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("bad", encoding="utf-8")
    bak = quarantine_corrupt(path)
    assert not path.exists()
    assert bak.read_text(encoding="utf-8") == "bad"
