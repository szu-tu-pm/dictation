from ctypes import c_void_p
from pathlib import Path

import numpy as np
import pytest

from dictation.config import AppConfig
from dictation.text import is_ghost, strip_fillers
from dictation.transcribe import WhisperEngine, _as_addr, _path_for_fopen, _write_wav, load_wav_mono
from dictation.vocabulary import Replacement, Vocabulary, save_vocabulary


def test_as_addr_int() -> None:
    assert _as_addr(123) == 123


def test_as_addr_c_void_p() -> None:
    assert _as_addr(c_void_p(456)) == 456


def test_as_addr_null() -> None:
    with pytest.raises(RuntimeError, match="null"):
        _as_addr(None)
    with pytest.raises(RuntimeError, match="null"):
        _as_addr(c_void_p())


def test_path_for_fopen_utf8(tmp_path: Path) -> None:
    p = tmp_path / "model.bin"
    assert _path_for_fopen(p) == str(p).encode("utf-8")


def test_engine_skips_quiet_without_loading() -> None:
    cfg = AppConfig()
    engine = WhisperEngine(Path("."), Path("missing.bin"), cfg)
    samples = np.zeros(100, dtype=np.float32)
    assert engine.transcribe(samples) is None


def test_engine_skips_empty_even_with_skip_gate() -> None:
    engine = WhisperEngine(Path("."), Path("missing.bin"), AppConfig())

    class _Fake:
        def transcribe(self, samples: np.ndarray, prompt: str = "") -> str:
            raise AssertionError("must not call impl on empty audio")

    engine._impl = _Fake()  # type: ignore[assignment]
    assert engine.transcribe(np.zeros(0, dtype=np.float32), skip_gate=True) is None


def test_warmup_noop_without_impl() -> None:
    engine = WhisperEngine(Path("."), Path("missing.bin"), AppConfig())
    engine.warmup()


def test_warmup_calls_impl_transcribe() -> None:
    engine = WhisperEngine(Path("."), Path("missing.bin"), AppConfig())
    class _Fake:
        def transcribe(self, samples: np.ndarray) -> str:
            assert samples.size > 0
            return "ok"

    engine._impl = _Fake()  # type: ignore[assignment]
    engine.warmup()


def test_engine_applies_replacements_and_prompt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    save_vocabulary(
        Vocabulary(
            words=["Whisper"],
            replacements=[Replacement(heard="wisper", meant="Whisper")],
        )
    )
    engine = WhisperEngine(Path("."), Path("missing.bin"), AppConfig())
    seen: dict[str, str] = {}

    class _Fake:
        def transcribe(self, samples: np.ndarray, prompt: str = "") -> str:
            seen["prompt"] = prompt
            return "um wisper flow"

    engine._impl = _Fake()  # type: ignore[assignment]
    rng = np.random.default_rng(0)
    samples = rng.normal(0, 0.1, 4000).astype(np.float32)
    assert engine.transcribe(samples) == "Whisper flow"
    assert "Whisper" in seen["prompt"]


def test_skip_gate_transcribes_quiet(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    engine = WhisperEngine(Path("."), Path("missing.bin"), AppConfig())

    class _Fake:
        def transcribe(self, samples: np.ndarray, prompt: str = "") -> str:
            return "hello"

    engine._impl = _Fake()  # type: ignore[assignment]
    samples = np.zeros(4000, dtype=np.float32)
    assert engine.transcribe(samples) is None
    assert engine.transcribe(samples, skip_gate=True) == "hello"


def test_load_wav_mono_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    original = np.linspace(-0.5, 0.5, 1600, dtype=np.float32)
    _write_wav(path, original, 16000)
    loaded = load_wav_mono(path, 16000)
    assert loaded.size == original.size
    np.testing.assert_allclose(loaded, original, atol=2 / 32768)


def test_cleanup_pipeline_matches_engine() -> None:
    raw = "  um thanks for watching  "
    text = strip_fillers(raw)
    assert is_ghost(text)
