from __future__ import annotations

import queue
import sys
import threading
from unittest.mock import MagicMock, patch

if sys.platform != "win32":
    sys.modules.setdefault("dictation.hotkey", MagicMock())
    sys.modules.setdefault("dictation.paste", MagicMock())

from dictation.app import DictationApp, State


def _ready_app() -> DictationApp:
    app = DictationApp()
    app.backend = "cpu"
    app.audio = MagicMock()
    app.engine = MagicMock()
    app.engine.ready = True
    app.hook = MagicMock()
    app.state = State.IDLE
    app.status = "Idle (cpu)"
    app._jobs = queue.Queue()
    return app


def _run_one_event(app: DictationApp, ev: str) -> None:
    """Feed one PTT event through the coordinator and then stop."""
    app._stop.clear()
    app._ptt.put(ev)
    done = threading.Event()
    real_get = app._ptt.get

    def get_wrapper(timeout=0.05):
        if done.is_set():
            app._stop.set()
            raise queue.Empty
        try:
            out = real_get(timeout=timeout)
        except Exception:
            app._stop.set()
            raise
        done.set()
        return out

    with patch.object(app._ptt, "get", side_effect=get_wrapper):
        app._coordinator()


def test_press_release_helpers() -> None:
    app = _ready_app()
    with app._lock:
        assert app._start_recording(continuous=False) is True
    assert app.state is State.RECORDING
    assert app.continuous is False
    assert app.status == "Recording"
    app.audio.mark_start.assert_called_with(max_seconds=app.cfg.max_record_seconds)
    app.hook.set_continuous.assert_called_with(False)
    with app._lock:
        assert app._stop_recording() is True
    assert app.state is State.TRANSCRIBING
    assert app.continuous is False


def test_double_tap_starts_continuous() -> None:
    app = _ready_app()
    _run_one_event(app, "double_tap")
    assert app.state is State.RECORDING
    assert app.continuous is True
    assert "continuous" in app.status
    app.audio.mark_start.assert_called_with(max_seconds=app.cfg.continuous_max_seconds)
    app.hook.set_continuous.assert_called_with(True)


def test_tap_stops_continuous() -> None:
    app = _ready_app()
    with app._lock:
        app._start_recording(continuous=True)
    _run_one_event(app, "tap")
    assert app.state is State.TRANSCRIBING
    assert app.continuous is False
    assert app._jobs.get_nowait() == "slice"
    app.hook.set_continuous.assert_called_with(False)


def test_tap_ignored_when_not_continuous() -> None:
    app = _ready_app()
    _run_one_event(app, "tap")
    assert app.state is State.IDLE
    assert app._jobs.empty()


def test_tray_toggle_starts_and_stops() -> None:
    app = _ready_app()
    _run_one_event(app, "continuous_toggle")
    assert app.continuous is True
    assert app.state is State.RECORDING
    _run_one_event(app, "continuous_toggle")
    assert app.continuous is False
    assert app.state is State.TRANSCRIBING
    assert app._jobs.get_nowait() == "slice"


def test_continuous_watchdog_emits_stop() -> None:
    app = _ready_app()
    app.cfg.continuous_max_seconds = 0.01
    with app._lock:
        app._start_recording(continuous=True)
    app._record_started = 0.0

    app._stop.clear()
    seen: list[str] = []
    real_put = app._ptt.put

    def put_wrapper(ev):
        seen.append(ev)
        real_put(ev)
        app._stop.set()

    with (
        patch.object(app._ptt, "put", side_effect=put_wrapper),
        patch.object(app._ptt, "get", side_effect=queue.Empty),
    ):
        app._coordinator()
    assert "stop" in seen


def test_stop_event_ends_continuous() -> None:
    app = _ready_app()
    with app._lock:
        app._start_recording(continuous=True)
    _run_one_event(app, "stop")
    assert app.state is State.TRANSCRIBING
    assert app.continuous is False
    assert app._jobs.get_nowait() == "slice"


def test_cancel_clears_continuous() -> None:
    app = _ready_app()
    with app._lock:
        app._start_recording(continuous=True)
    assert app.continuous is True

    with patch("dictation.app.play_cue") as mock_cue, patch.object(app, "_refresh_icon"):
        _run_one_event(app, "cancel")

    assert app.state is State.IDLE
    assert app.continuous is False
    app.audio.cancel.assert_called_once()
    app.hook.set_continuous.assert_called_with(False)
    mock_cue.assert_called_with("discard", enabled=True)


def test_menu_continuous_toggle_enqueues() -> None:
    app = DictationApp()
    app._menu()
    app._toggle_continuous()
    assert app._ptt.get_nowait() == "continuous_toggle"


def test_press_while_continuous_stops() -> None:
    app = _ready_app()
    with app._lock:
        app._start_recording(continuous=True)
    _run_one_event(app, "press")
    assert app.state is State.TRANSCRIBING
    assert app.continuous is False
    assert app._jobs.get_nowait() == "slice"
