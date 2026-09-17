from unittest.mock import MagicMock, patch

import pytest

from dictation.app import DictationApp, State, main, run_check


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
