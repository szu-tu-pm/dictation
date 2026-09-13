from ctypes import c_void_p
from pathlib import Path

import numpy as np
import pytest

from dictation.config import AppConfig
from dictation.text import is_ghost, strip_fillers
from dictation.transcribe import WhisperEngine, _as_addr


def test_as_addr_int() -> None:
    assert _as_addr(123) == 123


def test_as_addr_c_void_p() -> None:
    assert _as_addr(c_void_p(456)) == 456


def test_as_addr_null() -> None:
    with pytest.raises(RuntimeError, match="null"):
        _as_addr(None)
    with pytest.raises(RuntimeError, match="null"):
        _as_addr(c_void_p())


def test_engine_skips_quiet_without_loading() -> None:
    cfg = AppConfig()
    engine = WhisperEngine(Path("."), Path("missing.bin"), cfg)
    samples = np.zeros(100, dtype=np.float32)
    assert engine.transcribe(samples) is None


def test_cleanup_pipeline_matches_engine() -> None:
    raw = "  um thank you  "
    text = strip_fillers(raw)
    assert is_ghost(text)
