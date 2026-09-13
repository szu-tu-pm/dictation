import numpy as np

from dictation.audio import RingBuffer, rms
from dictation.transcribe import too_quiet


def test_ring_copy_latest() -> None:
    ring = RingBuffer(1.0, 16000)
    ring.write(np.ones(20000, dtype=np.float32))
    chunk = ring.copy_abs(ring.write_total - 1000, ring.write_total)
    assert chunk.size == 1000
    assert float(chunk.mean()) == 1.0


def test_ring_wrap_preserves_sequence() -> None:
    ring = RingBuffer(seconds=0.01, samplerate=1000)  # 1000 samples min
    # n = max(10, 1000) = 1000
    data = np.arange(1500, dtype=np.float32)
    ring.write(data)
    out = ring.copy_abs(ring.write_total - 500, ring.write_total)
    np.testing.assert_array_equal(out, data[-500:])


def test_ring_empty_range() -> None:
    ring = RingBuffer(1.0, 16000)
    assert ring.copy_abs(0, 0).size == 0


def test_rms_zero_and_ones() -> None:
    assert rms(np.zeros(0, dtype=np.float32)) == 0.0
    assert rms(np.ones(16, dtype=np.float32)) == 1.0


def test_too_quiet_short_clip() -> None:
    samples = np.zeros(100, dtype=np.float32)
    assert too_quiet(samples, threshold=0.008, min_samples=3200)


def test_too_quiet_silence() -> None:
    samples = np.zeros(4000, dtype=np.float32)
    assert too_quiet(samples, threshold=0.008, min_samples=3200)


def test_too_quiet_speech_like() -> None:
    rng = np.random.default_rng(0)
    samples = rng.normal(0, 0.1, 4000).astype(np.float32)
    assert not too_quiet(samples, threshold=0.008, min_samples=3200)
