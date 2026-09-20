from dictation.config import AppConfig, load_config, save_config
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
    assert config_path().is_file()


def test_load_recovers_corrupt_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    appdata_dir()
    config_path().write_text("{not-json", encoding="utf-8")
    loaded = load_config()
    assert loaded.max_record_seconds == 60.0
    assert '"max_record_seconds"' in config_path().read_text(encoding="utf-8")


def test_load_recovers_non_dict(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    appdata_dir()
    config_path().write_text("[1, 2, 3]\n", encoding="utf-8")
    loaded = load_config()
    assert loaded.hotkey == "rctrl"
