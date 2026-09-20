from __future__ import annotations

import io
import wave
from unittest.mock import MagicMock, patch

import pytest

from dictation.config import AppConfig
from dictation.sound import get_cue_wav, play_cue


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


def test_play_cue_disabled() -> None:
    with patch("dictation.sound.winsound") as mock_ws:
        assert play_cue("start", enabled=False) is False
        mock_ws.PlaySound.assert_not_called()


def test_play_cue_enabled() -> None:
    with patch("dictation.sound.winsound") as mock_ws:
        mock_ws.SND_MEMORY = 0x04
        mock_ws.SND_ASYNC = 0x01
        mock_ws.SND_NODEFAULT = 0x02
        assert play_cue("paste", enabled=True) is True
        mock_ws.PlaySound.assert_called_once()
        args, _ = mock_ws.PlaySound.call_args
        assert args[0].startswith(b"RIFF")
        assert args[1] == (mock_ws.SND_MEMORY | mock_ws.SND_ASYNC | mock_ws.SND_NODEFAULT)


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
