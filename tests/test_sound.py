from __future__ import annotations

import io
from pathlib import Path
import sys
import wave
from unittest.mock import MagicMock, patch

import pytest

from dictation.config import AppConfig
from dictation.sound import _get_cue_path, get_cue_wav, init_cues, play_cue


def test_init_cues() -> None:
    with patch("dictation.sound._get_cue_path") as mock_get_path:
        init_cues()
        assert mock_get_path.call_count == 4
        cues_called = [call.args[0] for call in mock_get_path.call_args_list]
        assert set(cues_called) == {"start", "stop", "paste", "discard"}


def test_cue_wav_generation() -> None:
    cues = ["start", "stop", "paste", "discard"]
    for name in cues:
        wav_bytes = get_cue_wav(name)  # type: ignore[arg-type]
        assert wav_bytes is not None
        assert wav_bytes.startswith(b"RIFF")
        assert b"WAVE" in wav_bytes
        # Read back with wave module to ensure validity
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 22050
            assert wf.getnframes() > 0


def test_cue_path_caching(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    import dictation.sound as sound_mod

    # Reset cache to test generation
    sound_mod._CUE_PATHS = None
    path = sound_mod._get_cue_path("start")
    assert path is not None
    assert path.exists()
    assert path.name == "start.wav"
    assert path.stat().st_size > 0


def test_play_cue_disabled() -> None:
    with patch("dictation.sound.winsound") as mock_ws:
        assert play_cue("start", enabled=False) is False
        mock_ws.PlaySound.assert_not_called()


def test_play_cue_file_async() -> None:
    with patch("dictation.sound.winsound") as mock_ws:
        mock_ws.SND_FILENAME = 0x20000
        mock_ws.SND_ASYNC = 0x01
        mock_ws.SND_NODEFAULT = 0x02
        assert play_cue("paste", enabled=True) is True
        mock_ws.PlaySound.assert_called_once()
        args, _ = mock_ws.PlaySound.call_args
        assert isinstance(args[0], str)
        assert args[0].endswith("paste.wav")
        assert args[1] == (mock_ws.SND_FILENAME | mock_ws.SND_ASYNC | mock_ws.SND_NODEFAULT)


def test_play_cue_fallback_thread() -> None:
    with patch("dictation.sound.winsound") as mock_ws, patch(
        "dictation.sound._get_cue_path", return_value=None
    ):
        mock_ws.SND_MEMORY = 0x04
        mock_ws.SND_NODEFAULT = 0x02
        assert play_cue("start", enabled=True) is True


def test_play_cue_no_winsound() -> None:
    with patch("dictation.sound.winsound", None):
        assert play_cue("start", enabled=True) is False


def test_play_cue_unknown_name() -> None:
    with patch("dictation.sound.winsound") as mock_ws:
        assert play_cue("invalid_cue", enabled=True) is False  # type: ignore[arg-type]
        mock_ws.PlaySound.assert_not_called()


def test_config_sound_effects_default() -> None:
    cfg = AppConfig()
    assert cfg.sound_effects is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_play_cue_real_windows_does_not_raise() -> None:
    # Verifies CPython doesn't raise RuntimeError: Cannot play asynchronously from memory
    assert play_cue("start", enabled=True) is True
