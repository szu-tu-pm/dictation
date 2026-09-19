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
