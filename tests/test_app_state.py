import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure Windows-only / GUI deps are mocked before dictation.app import
sys.modules.setdefault("pystray", MagicMock())
if sys.platform != "win32":
    sys.modules.setdefault("dictation.hotkey", MagicMock())
    sys.modules.setdefault("dictation.paste", MagicMock())

from dictation.app import DictationApp, State, main, run_check, run_transcribe


def test_app_initial_state() -> None:
    app = DictationApp()
    assert app.state == State.STARTING
    assert "Starting" in app.status
    assert app.backend == "unknown"


def test_app_set_state_thread_safe() -> None:
    app = DictationApp()
    with patch.object(app, "_refresh_icon") as mock_icon:
        app._set_state(State.IDLE, "Idle (vulkan)", log=False)
        assert app.state == State.IDLE
        assert app.status == "Idle (vulkan)"
        assert mock_icon.called


def test_app_error_recovery_generation() -> None:
    app = DictationApp()
    app.backend = "vulkan"
    app._set_state(State.ERROR, "Error — see log", log=False)
    app._error_gen = 1

    # Matching generation and State.ERROR -> recovers to IDLE
    app._recover_from_error(gen=1)
    assert app.state == State.IDLE
    assert "Idle (vulkan)" in app.status

    # Stale generation -> no recovery
    app._set_state(State.ERROR, "Error — see log", log=False)
    app._error_gen = 2
    app._recover_from_error(gen=1)  # older gen
    assert app.state == State.ERROR

    # State changed to RECORDING before recovery fires -> do not clobber
    app._error_gen = 3
    app._set_state(State.RECORDING, "Recording", log=False)
    app._recover_from_error(gen=3)
    assert app.state == State.RECORDING


def test_on_progress_throttling() -> None:
    app = DictationApp()
    with patch.object(app, "_set_state") as mock_set:
        # First call: got=0 -> logs
        app._on_progress("model", got=0, total=100)
        assert mock_set.called

        mock_set.reset_mock()
        # Immediately call with got=0 again (0% diff, < 0.5s) -> skipped
        app._on_progress("model", got=0, total=100)
        assert not mock_set.called

        # Advance by 10% -> triggers
        app._on_progress("model", got=10, total=100)
        assert mock_set.called

        # Unknown Content-Length (total=0) throttle check
        mock_set.reset_mock()
        app._progress_last_ts = 0.0  # reset timestamp to allow first call
        app._on_progress("model", got=1000, total=0)
        assert mock_set.called

        mock_set.reset_mock()
        # Immediate subsequent call with total=0 (< 0.5s) -> skipped
        app._on_progress("model", got=2000, total=0)
        assert not mock_set.called


def test_startup_quit_race() -> None:
    app = DictationApp()
    app._stop.set()  # user requested quit during download
    with (
        patch("dictation.app.ensure_engine", return_value="engine_dir"),
        patch("dictation.app.ensure_model", return_value="model_path"),
        patch("dictation.app.WhisperEngine") as mock_engine_cls,
        patch("dictation.app.RightCtrlHook") as mock_hook_cls,
    ):
        mock_engine = MagicMock()
        mock_engine.backend = "vulkan"
        mock_engine_cls.return_value = mock_engine
        mock_hook = MagicMock()
        mock_hook_cls.return_value = mock_hook

        app._startup()
        # When _stop is set, hook must NOT start and state must NOT transition to IDLE
        assert not mock_hook.start.called
        assert app.state != State.IDLE


def test_run_check_flag() -> None:
    with (
        patch("dictation.app.find_wasapi_input", return_value=0),
        patch("dictation.app.RightCtrlHook") as mock_hook_cls,
    ):
        mock_hook = MagicMock()
        mock_hook_cls.return_value = mock_hook
        res = run_check()
        assert res == 0
        assert mock_hook.start.called
        assert mock_hook.stop.called


def test_cli_main_check() -> None:
    with (
        patch("dictation.app.run_check", return_value=0) as mock_check,
        pytest.raises(SystemExit) as exc_info,
    ):
        main(["--check"])
    assert exc_info.value.code == 0
    assert mock_check.called


def test_cli_main_transcribe_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with pytest.raises(SystemExit) as exc_info:
        main(["--transcribe", str(tmp_path / "missing.wav")])
    assert exc_info.value.code == 2


def test_run_transcribe_uses_engine(tmp_path, monkeypatch) -> None:
    import numpy as np

    from dictation.transcribe import _write_wav

    monkeypatch.setenv("APPDATA", str(tmp_path))
    wav = tmp_path / "utt.wav"
    _write_wav(wav, np.zeros(16000, dtype=np.float32), 16000)
    fake_engine = MagicMock()
    fake_engine.backend = "vulkan"
    fake_engine.transcribe.return_value = "hello"
    with (
        patch("dictation.app.ensure_engine", return_value=tmp_path),
        patch("dictation.app.ensure_model", return_value=tmp_path / "m.bin"),
        patch("dictation.app.WhisperEngine", return_value=fake_engine),
    ):
        assert run_transcribe(str(wav)) == 0
    fake_engine.load.assert_called_once_with(warmup=False)
    fake_engine.transcribe.assert_called_once()
    fake_engine.close.assert_called_once()

def test_run_transcribe_empty_wav(tmp_path, monkeypatch) -> None:
    import numpy as np

    from dictation.transcribe import _write_wav

    monkeypatch.setenv("APPDATA", str(tmp_path))
    wav = tmp_path / "empty.wav"
    _write_wav(wav, np.zeros(0, dtype=np.float32), 16000)
    with patch("dictation.app.WhisperEngine") as mock_engine_cls:
        assert run_transcribe(str(wav)) == 1
        assert not mock_engine_cls.called


def test_refresh_icon_skips_menu_on_level_tick() -> None:
    app = DictationApp()
    icon = MagicMock()
    app.icon = icon
    app.state = State.RECORDING
    app.audio = MagicMock(level=0.4)
    app._refresh_icon(update_menu=False)
    assert icon.icon is not None
    assert "Recording 40%" in icon.title
    assert not icon.update_menu.called
    app._refresh_icon(update_menu=True)
    assert icon.update_menu.called
