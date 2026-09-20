from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure Windows-only / GUI deps are mocked on non-Windows platforms
if sys.platform != "win32":
    sys.modules.setdefault("pystray", MagicMock())
    sys.modules.setdefault("dictation.hotkey", MagicMock())
    sys.modules.setdefault("dictation.paste", MagicMock())

from dictation.app import DictationApp, State
from dictation.config import AppConfig


def test_tray_menu_structure() -> None:
    app = DictationApp()
    menu = app._menu()
    assert menu is not None
    # Verify submenu items exist
    dev_items = app._device_menu_items()
    assert len(dev_items) >= 1
    assert dev_items[0].text == "Default Microphone"

    hist_items = app._history_menu_items()
    assert len(hist_items) >= 1


def test_device_menu_selection(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = DictationApp()
    mock_audio = MagicMock()
    app.audio = mock_audio

    with patch("dictation.app.list_wasapi_inputs", return_value=[(1, "USB Mic"), (2, "Headset")]):
        items = app._device_menu_items()
        assert len(items) == 3
        assert items[0].text == "Default Microphone"
        assert items[1].text == "USB Mic"
        assert items[2].text == "Headset"

        # Click second device
        items[1]._action(None)
        assert app.cfg.device == 1
        mock_audio.switch_device.assert_called_with(1)

        # Click default mic
        items[0]._action(None)
        assert app.cfg.device is None
        mock_audio.switch_device.assert_called_with(None)


def test_history_menu_items_empty() -> None:
    app = DictationApp()
    with patch("dictation.app.load_history", return_value=[]):
        items = app._history_menu_items()
        assert len(items) == 1
        assert items[0].text == "(No recent transcripts)"
        assert not items[0].enabled


def test_history_menu_items_copy() -> None:
    app = DictationApp()
    mock_history = [
        {"date": "2026-09-20T10:00:00", "text": "Testing dictation tray copy"},
        {"date": "2026-09-20T10:01:00", "text": "Short"},
    ]
    with patch("dictation.app.load_history", return_value=mock_history), patch(
        "dictation.app.copy_to_clipboard"
    ) as mock_copy:
        items = app._history_menu_items()
        assert len(items) == 2
        assert items[0].text == "Testing dictation tray copy"
        # Trigger click
        items[0]._action(None)
        mock_copy.assert_called_once_with("Testing dictation tray copy")


def test_toggle_mute() -> None:
    app = DictationApp()
    app.hook = MagicMock()
    app.icon = MagicMock()
    assert app.muted is False

    # Mute
    app._toggle_mute()
    assert app.muted is True
    app.hook.set_enabled.assert_called_with(False)
    assert app.icon.title == "Dictation — Muted"

    # Unmute
    app._toggle_mute()
    assert app.muted is False
    app.hook.set_enabled.assert_called_with(True)


def test_quick_links(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = DictationApp()

    with patch("os.startfile", create=True) as mock_startfile:
        app._open_folder()
        assert mock_startfile.called

    with patch("os.startfile", create=True) as mock_startfile:
        app._open_vocabulary()
        assert mock_startfile.called

    with patch("os.startfile", create=True) as mock_startfile:
        app._open_log()
        assert mock_startfile.called
