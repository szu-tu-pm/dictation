from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

if sys.platform != "win32":
    sys.modules.setdefault("dictation.hotkey", MagicMock())
    sys.modules.setdefault("dictation.paste", MagicMock())

from dictation.app import DictationApp, State


def test_tray_menu_has_recent_transcripts() -> None:
    app = DictationApp()
    menu = app._menu()
    assert menu is not None
    with patch("dictation.app.load_history", return_value=[]):
        items = app._history_menu_items()
        assert len(items) == 1
        assert items[0].text == "(No recent transcripts)"
        assert not items[0].enabled


def test_history_menu_items_copy() -> None:
    app = DictationApp()
    long = "A" * 50
    mock_history = [
        {"date": "2026-09-20T10:00:00", "text": long},
        {"date": "2026-09-20T10:01:00", "text": "Short"},
    ]
    with patch("dictation.app.load_history", return_value=mock_history), patch(
        "dictation.app.copy_to_clipboard"
    ) as mock_copy:
        items = app._history_menu_items()
        assert len(items) == 2
        assert items[0].text == ("A" * 45) + "…"
        assert items[1].text == "Short"
        items[0]._action(None)
        mock_copy.assert_called_once_with(long)


def test_history_menu_caps_at_eight() -> None:
    app = DictationApp()
    mock_history = [{"date": f"d{i}", "text": f"t{i}"} for i in range(12)]
    with patch("dictation.app.load_history", return_value=mock_history), patch(
        "dictation.app.copy_to_clipboard"
    ):
        items = app._history_menu_items()
        assert len(items) == 8


def test_worker_records_history_before_paste_failure() -> None:
    app = DictationApp()
    app.backend = "cpu"
    app._stop.clear()
    samples = np.zeros(1600, dtype=np.float32)
    app.audio = MagicMock()
    app.audio.take_slice.return_value = samples
    app.engine = MagicMock()
    app.engine.ready = True
    app.engine.transcribe.return_value = "hello world"
    app._jobs.put("slice")

    recorded: list[str] = []

    def _on_set_state(state, status, **_kwargs):
        if state is State.ERROR:
            app._stop.set()

    with (
        patch("dictation.app.record_dictation", side_effect=lambda t: recorded.append(t)),
        patch("dictation.app.paste_text", side_effect=RuntimeError("UIPI blocked")),
        patch.object(app, "_set_state", side_effect=_on_set_state) as mock_set,
        patch("dictation.app.threading.Timer") as mock_timer,
    ):
        app._worker()

    assert recorded == ["hello world"]
    statuses = [c.args[1] for c in mock_set.call_args_list if len(c.args) >= 2]
    assert any("Recent Transcripts" in s for s in statuses)
    assert mock_timer.called
