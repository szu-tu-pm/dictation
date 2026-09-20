import numpy as np

from dictation.audio import AudioCapture, RingBuffer, peak_abs, rms
from dictation.config import AppConfig
from dictation.transcribe import too_quiet


def test_ring_copy_latest() -> None:
    ring = RingBuffer(1.0, 16000)
    ring.write(np.ones(20000, dtype=np.float32))
    chunk = ring.copy_abs(ring.write_total - 1000, ring.write_total)
    assert chunk.size == 1000
    assert float(chunk.mean()) == 1.0


def test_ring_wrap_preserves_sequence() -> None:
    ring = RingBuffer(seconds=0.01, samplerate=1000)  # 1000 samples min
    data = np.arange(1500, dtype=np.float32)
    ring.write(data)
    out = ring.copy_abs(ring.write_total - 500, ring.write_total)
    np.testing.assert_array_equal(out, data[-500:])


def test_ring_empty_range() -> None:
    ring = RingBuffer(1.0, 16000)
    assert ring.copy_abs(0, 0).size == 0


def test_grow_to_remaps_absolute_indices() -> None:
    ring = RingBuffer(seconds=0.01, samplerate=1000)  # n=1000
    data = np.arange(1500, dtype=np.float32)
    ring.write(data)
    old_total = ring.write_total
    ring.grow_to(2.0, 1000)  # n=2000
    assert ring.n == 2000
    assert ring.write_total == old_total
    out = ring.copy_abs(old_total - 500, old_total)
    np.testing.assert_array_equal(out, data[-500:])


def test_truncation_events_increment() -> None:
    ring = RingBuffer(seconds=0.01, samplerate=1000)  # n=1000
    # Write in chunks so total advances past n (a single oversized write is clipped)
    ring.write(np.arange(800, dtype=np.float32))
    ring.write(np.arange(800, 1600, dtype=np.float32))
    assert ring.write_total == 1600
    assert ring.truncation_events == 0
    out = ring.copy_abs(0, ring.write_total)
    assert out.size == 1000
    assert ring.truncation_events == 1


def test_rms_zero_and_ones() -> None:
    assert rms(np.zeros(0, dtype=np.float32)) == 0.0
    assert rms(np.ones(16, dtype=np.float32)) == 1.0
    assert peak_abs(np.zeros(0, dtype=np.float32)) == 0.0
    assert peak_abs(np.array([-0.5, 0.25], dtype=np.float32)) == 0.5


def test_too_quiet_short_clip() -> None:
    samples = np.zeros(100, dtype=np.float32)
    assert too_quiet(samples, threshold=0.008, min_samples=3200)


def test_too_quiet_silence() -> None:
    samples = np.zeros(4000, dtype=np.float32)
    assert too_quiet(samples, threshold=0.008, min_samples=3200)


def test_capture_level_rises(monkeypatch) -> None:
    from dictation.audio import AudioCapture
    from dictation.config import AppConfig

    monkeypatch.setattr("dictation.audio.find_wasapi_input", lambda preferred: 0)
    monkeypatch.setattr(
        "dictation.audio.sd.query_devices",
        lambda *_a, **_k: {"name": "mic", "hostapi": 0},
    )
    monkeypatch.setattr(
        "dictation.audio.sd.query_hostapis",
        lambda: [{"name": "WASAPI"}],
    )
    cap = AudioCapture(AppConfig())
    assert cap.level == 0.0
    cap._callback(np.ones((256, 1), dtype=np.float32) * 0.2, 256, None, 0)
    assert cap.level > 0.0


def test_too_quiet_speech_like() -> None:
    rng = np.random.default_rng(0)
    samples = rng.normal(0, 0.1, 4000).astype(np.float32)
    assert not too_quiet(samples, threshold=0.008, min_samples=3200)


def test_audio_capture_cancel(monkeypatch) -> None:
    monkeypatch.setattr(
        "dictation.audio.sd.query_devices",
        lambda *_a, **_k: {"name": "mic", "hostapi": 0},
    )
    monkeypatch.setattr(
        "dictation.audio.sd.query_hostapis",
        lambda: [{"name": "WASAPI", "default_input_device": 0}],
    )
    cap = AudioCapture(AppConfig())
    cap.mark_start()
    assert cap._mark is not None
    cap.cancel()
    assert cap._mark is None
