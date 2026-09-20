from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
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


def test_history_menu_caps_at_five() -> None:
    app = DictationApp()
    mock_history = [{"date": f"d{i}", "text": f"t{i}"} for i in range(12)]
    with patch("dictation.app.load_history", return_value=mock_history), patch(
        "dictation.app.copy_to_clipboard"
    ):
        items = app._history_menu_items()
        assert len(items) == 5


def test_worker_records_history_before_paste_failure() -> None:
    """PR #9 clipboard safety net: persist history even when paste is blocked."""
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
        patch("dictation.app.play_cue"),
        patch.object(app, "_set_state", side_effect=_on_set_state) as mock_set,
        patch("dictation.app.threading.Timer") as mock_timer,
    ):
        app._worker()

    assert recorded == ["hello world"]
    statuses = [c.args[1] for c in mock_set.call_args_list if len(c.args) >= 2]
    assert any("Recent Transcripts" in s for s in statuses)
    assert mock_timer.called


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


def test_device_switch_failure_does_not_save_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = DictationApp()
    app.cfg.device = None
    mock_audio = MagicMock()
    mock_audio.switch_device.side_effect = RuntimeError("Device unavailable")
    app.audio = mock_audio

    with patch("dictation.app.save_config") as mock_save:
        with pytest.raises(RuntimeError, match="Device unavailable"):
            app._set_device(99)
        assert not mock_save.called
    assert app.cfg.device is None


def test_device_menu_escapes_ampersand() -> None:
    app = DictationApp()
    with patch("dictation.app.list_wasapi_inputs", return_value=[(1, "Microphone (Realtek & USB)")]):
        items = app._device_menu_items()
        assert items[1].text == "Microphone (Realtek && USB)"


def test_toggle_sound(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    app = DictationApp()
    app.cfg.sound_effects = True
    with patch("dictation.app.save_config") as mock_save:
        app._toggle_sound()
        assert app.cfg.sound_effects is False
        assert mock_save.called

        mock_save.reset_mock()
        app._toggle_sound()
        assert app.cfg.sound_effects is True
        assert mock_save.called


def test_audio_capture_switch_device_clears_ring_and_cancels(monkeypatch) -> None:
    import numpy as np
    from dictation.audio import AudioCapture
    from dictation.config import AppConfig

    monkeypatch.setattr(
        "dictation.audio.sd.query_devices",
        lambda *_a, **_k: {"name": "mic", "hostapi": 0},
    )
    monkeypatch.setattr(
        "dictation.audio.sd.query_hostapis",
        lambda: [{"name": "WASAPI", "default_input_device": 0}],
    )
    cfg = AppConfig()
    audio = AudioCapture(cfg)
    audio.ring.write(np.ones(1000, dtype=np.float32))
    audio.mark_start()
    assert audio.ring.write_total == 1000
    assert audio._mark is not None

    with (
        patch("dictation.audio.find_wasapi_input", return_value=1),
        patch("dictation.audio.sd.query_devices", return_value={"name": "New Mic"}),
        patch.object(audio, "start"),
        patch.object(audio, "stop"),
    ):
        audio.switch_device(1)
        assert audio.ring.write_total == 0
        assert audio._mark is None
        assert audio.device == 1


def test_device_switch_while_recording_cancels_take() -> None:
    app = DictationApp()
    app.state = State.RECORDING
    mock_audio = MagicMock()
    app.audio = mock_audio

    with patch("dictation.app.play_cue") as mock_cue, patch("dictation.app.save_config"):
        app._set_device(2)
        mock_audio.cancel.assert_called_once()
        assert app.state == State.IDLE
        mock_cue.assert_called_with("discard", enabled=app.cfg.sound_effects)
        mock_audio.switch_device.assert_called_with(2)


def test_toggle_mute_while_recording_cancels_take() -> None:
    app = DictationApp()
    app.state = State.RECORDING
    mock_audio = MagicMock()
    app.audio = mock_audio
    app.icon = MagicMock()

    with patch("dictation.app.play_cue") as mock_cue:
        app._toggle_mute()
        assert app.muted is True
        mock_audio.cancel.assert_called_once()
        assert app.state == State.IDLE
        mock_cue.assert_called_with("discard", enabled=app.cfg.sound_effects)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only (hotkey mocked on Linux)")
def test_hook_set_enabled_false_while_down_does_not_release() -> None:
    from dictation.hotkey import RightCtrlHook
    on_press = MagicMock()
    on_release = MagicMock()
    on_cancel = MagicMock()
    hook = RightCtrlHook(on_press, on_release, on_cancel)

    with hook._down_lock:
        hook._down = True

    hook.set_enabled(False)
    assert hook.down is False
    assert not on_release.called
