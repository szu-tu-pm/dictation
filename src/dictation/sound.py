from __future__ import annotations

import io
import math
import struct
import wave
from typing import Literal

try:
    import winsound
except ImportError:
    winsound = None  # type: ignore[assignment]

CueName = Literal["start", "stop", "paste", "discard"]

SAMPLE_RATE = 22050


def _generate_wav(samples: list[float], sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        # Convert [-1.0, 1.0] float samples to 16-bit signed PCM
        raw = bytearray()
        for s in samples:
            clamped = max(-1.0, min(1.0, s))
            val = int(clamped * 32767.0)
            raw.extend(struct.pack("<h", val))
        wf.writeframes(raw)
    return buf.getvalue()


def _synthesize_tone(freq: float, duration_s: float, volume: float = 0.25) -> list[float]:
    num_samples = int(SAMPLE_RATE * duration_s)
    samples: list[float] = []
    # 5ms fade in / out to avoid clicking
    fade_len = min(int(SAMPLE_RATE * 0.005), num_samples // 2)
    for i in range(num_samples):
        t = i / SAMPLE_RATE
        val = math.sin(2.0 * math.pi * freq * t) * volume
        if i < fade_len:
            val *= i / fade_len
        elif i >= num_samples - fade_len:
            val *= (num_samples - 1 - i) / fade_len
        samples.append(val)
    return samples


def _synthesize_sweep(
    freq_start: float, freq_end: float, duration_s: float, volume: float = 0.25
) -> list[float]:
    num_samples = int(SAMPLE_RATE * duration_s)
    samples: list[float] = []
    fade_len = min(int(SAMPLE_RATE * 0.005), num_samples // 2)
    phase = 0.0
    for i in range(num_samples):
        progress = i / max(1, num_samples - 1)
        freq = freq_start + (freq_end - freq_start) * progress
        phase += 2.0 * math.pi * freq / SAMPLE_RATE
        val = math.sin(phase) * volume
        if i < fade_len:
            val *= i / fade_len
        elif i >= num_samples - fade_len:
            val *= (num_samples - 1 - i) / fade_len
        samples.append(val)
    return samples


def _build_cues() -> dict[str, bytes]:
    # Start: soft high blip (650 Hz, 40ms)
    start_samples = _synthesize_tone(650.0, 0.040, volume=0.20)
    # Stop: crisp acknowledgement tone (880 Hz, 45ms)
    stop_samples = _synthesize_tone(880.0, 0.045, volume=0.22)
    # Paste: cheerful ascending two-tone chime (750 Hz 40ms + 1050 Hz 55ms)
    paste_samples = _synthesize_tone(750.0, 0.035, volume=0.20) + _synthesize_tone(
        1050.0, 0.055, volume=0.25
    )
    # Discard: subtle descending sweep (440 Hz -> 260 Hz, 80ms)
    discard_samples = _synthesize_sweep(440.0, 260.0, 0.080, volume=0.20)

    return {
        "start": _generate_wav(start_samples),
        "stop": _generate_wav(stop_samples),
        "paste": _generate_wav(paste_samples),
        "discard": _generate_wav(discard_samples),
    }


_CUES: dict[str, bytes] | None = None


def get_cue_wav(name: CueName) -> bytes | None:
    global _CUES
    if _CUES is None:
        _CUES = _build_cues()
    return _CUES.get(name)


def play_cue(name: CueName, *, enabled: bool = True) -> bool:
    """Play an in-memory earcon asynchronously. Returns True if played."""
    if not enabled or winsound is None:
        return False
    data = get_cue_wav(name)
    if data is None:
        return False
    try:
        flags = winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        winsound.PlaySound(data, flags)
        return True
    except Exception:
        return False
