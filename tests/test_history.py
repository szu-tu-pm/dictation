from dictation.history import HISTORY_LIMIT, load_history, record_dictation
from dictation.paths import history_path


def test_record_dictation_prepends_and_caps(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    record_dictation("first")
    record_dictation("second")
    items = load_history()
    assert [i["text"] for i in items] == ["second", "first"]
    assert history_path().is_file()
    assert "date" in items[0]


def test_record_dictation_skips_blank(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    record_dictation("   ")
    assert load_history() == []


def test_record_dictation_limit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    for i in range(5):
        record_dictation(f"item {i}", limit=3)
    texts = [i["text"] for i in load_history()]
    assert texts == ["item 4", "item 3", "item 2"]
    assert HISTORY_LIMIT == 200


def test_record_dictation_swallows_oserror(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from pathlib import Path
    from unittest.mock import patch

    with patch.object(Path, "replace", side_effect=PermissionError("locked")):
        # Must not raise — paste already succeeded by the time history is written.
        record_dictation("hello")
    assert load_history() == []


def test_load_history_quarantines_corrupt_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json", encoding="utf-8")
    assert load_history() == []
    bak = path.with_name(path.name + ".bak")
    assert bak.is_file()
    assert bak.read_text(encoding="utf-8") == "{not-json"
    assert not path.exists()


def test_load_history_quarantines_non_list(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"text": "x"}\n', encoding="utf-8")
    assert load_history() == []
    assert path.with_name(path.name + ".bak").is_file()
