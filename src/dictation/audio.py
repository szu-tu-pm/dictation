from __future__ import annotations

import threading
import time

import numpy as np
import sounddevice as sd

from dictation.config import AppConfig
from dictation.logutil import LOG


class RingBuffer:
    def __init__(self, seconds: float, samplerate: int) -> None:
        self.n = max(int(seconds * samplerate), samplerate)
        self.buf = np.zeros(self.n, dtype=np.float32)
        self._lock = threading.Lock()
        self.total = 0
        self.truncation_events = 0

    def write(self, samples: np.ndarray) -> None:
        x = np.ascontiguousarray(samples, dtype=np.float32).reshape(-1)
        if x.size == 0:
            return
        if x.size >= self.n:
            x = x[-self.n :]
        n = int(x.size)
        with self._lock:
            start = self.total % self.n
            first = min(n, self.n - start)
            self.buf[start : start + first] = x[:first]
            if first < n:
                self.buf[: n - first] = x[first:]
            self.total += n

    def copy_abs(self, start_abs: int, end_abs: int) -> np.ndarray:
        with self._lock:
            end_abs = min(end_abs, self.total)
            earliest = max(0, self.total - self.n)
            if start_abs < earliest:
                self.truncation_events += 1
                start_abs = earliest
            else:
                start_abs = max(start_abs, earliest)
            n = end_abs - start_abs
            if n <= 0:
                return np.zeros(0, dtype=np.float32)
            start = start_abs % self.n
            out = np.empty(n, dtype=np.float32)
            first = min(n, self.n - start)
            out[:first] = self.buf[start : start + first]
            if first < n:
                out[first:] = self.buf[: n - first]
            return out

    def grow_to(self, seconds: float, samplerate: int) -> None:
        new_n = max(int(seconds * samplerate), samplerate)
        with self._lock:
            if new_n <= self.n:
                return
            available = min(self.total, self.n)
            new_buf = np.zeros(new_n, dtype=np.float32)
            if available > 0:
                start_abs = self.total - available
                src = start_abs % self.n
                ordered = np.empty(available, dtype=np.float32)
                first = min(available, self.n - src)
                ordered[:first] = self.buf[src : src + first]
                if first < available:
                    ordered[first:] = self.buf[: available - first]
                dest = start_abs % new_n
                first_d = min(available, new_n - dest)
                new_buf[dest : dest + first_d] = ordered[:first_d]
                if first_d < available:
                    new_buf[: available - first_d] = ordered[first_d:]
            self.buf = new_buf
            self.n = new_n

    def clear(self) -> None:
        """Reset the buffer contents, write counter, and truncation events."""
        with self._lock:
            self.buf.fill(0)
            self.total = 0
            self.truncation_events = 0

    @property
    def write_total(self) -> int:
        with self._lock:
            return self.total


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def peak_abs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.max(np.abs(samples)))


def find_wasapi_input(preferred: int | None) -> int:
    hostapis = sd.query_hostapis()
    wasapi_index = next(
        (i for i, api in enumerate(hostapis) if "WASAPI" in str(api.get("name", ""))),
        None,
    )
    if wasapi_index is None:
        raise RuntimeError("WASAPI host API not found in PortAudio")
    default_in = int(hostapis[wasapi_index]["default_input_device"])
    if preferred is None:
        return default_in
    info = sd.query_devices(preferred)
    if int(info["hostapi"]) != wasapi_index:
        LOG.warning("configured device %s is not WASAPI; using default %s", preferred, default_in)
        return default_in
    return int(preferred)


def list_wasapi_inputs() -> list[tuple[int, str]]:
    """List available WASAPI input devices as (device_index, name)."""
    try:
        hostapis = sd.query_hostapis()
        wasapi_index = next(
            (i for i, api in enumerate(hostapis) if "WASAPI" in str(api.get("name", ""))),
            None,
        )
        if wasapi_index is None:
            return []
        devices = sd.query_devices()
        results: list[tuple[int, str]] = []
        for idx, dev in enumerate(devices):
            if int(dev.get("hostapi", -1)) == wasapi_index and int(dev.get("max_input_channels", 0)) > 0:
                name = str(dev.get("name", f"Device {idx}"))
                results.append((idx, name))
        return results
    except Exception:
        LOG.exception("failed to query WASAPI devices")
        return []


class AudioCapture:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.ring = RingBuffer(cfg.ring_seconds, cfg.sample_rate)
        self._stream: sd.InputStream | None = None
        self._mark: int | None = None
        self._pa_status = 0
        self._pa_status_count = 0
        self._level = 0.0
        self._level_lock = threading.Lock()
        self.device = find_wasapi_input(cfg.device)
        info = sd.query_devices(self.device)
        LOG.info(
            "WASAPI input device %s (%s) hostapi=%s",
            self.device,
            info["name"],
            sd.query_hostapis()[int(info["hostapi"])]["name"],
        )

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            self._pa_status = int(status)
            self._pa_status_count += 1
        chunk = indata[:, 0]
        self.ring.write(chunk)
        energy = rms(chunk)
        with self._level_lock:
            self._level = self._level * 0.6 + min(1.0, energy * 10.0) * 0.4

    @property
    def level(self) -> float:
        with self._level_lock:
            return self._level

    def drain_portaudio_status(self) -> int | None:
        if self._pa_status_count == 0:
            return None
        status = self._pa_status
        self._pa_status_count = 0
        return status

    def start(self) -> None:
        extra: sd.WasapiSettings
        try:
            extra = sd.WasapiSettings(exclusive=False, auto_convert=True)
        except TypeError:
            extra = sd.WasapiSettings(exclusive=False)
        self._stream = sd.InputStream(
            samplerate=self.cfg.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device,
            extra_settings=extra,
            callback=self._callback,
            blocksize=0,
        )
        self._stream.start()
        LOG.info("WASAPI shared capture started at %s Hz", self.cfg.sample_rate)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                LOG.exception("error stopping audio stream")
            self._stream = None

    def mark_start(self) -> None:
        self.ring.grow_to(
            max(self.cfg.ring_seconds, self.cfg.max_record_seconds + 2),
            self.cfg.sample_rate,
        )
        preroll = int(self.cfg.sample_rate * self.cfg.preroll_ms / 1000)
        self._mark = max(0, self.ring.write_total - preroll)

    def take_slice(self) -> np.ndarray:
        suffix = int(self.cfg.sample_rate * self.cfg.suffix_ms / 1000)
        if suffix > 0:
            time.sleep(self.cfg.suffix_ms / 1000)
        start = 0 if self._mark is None else self._mark
        self._mark = None
        before = self.ring.truncation_events
        samples = self.ring.copy_abs(start, self.ring.write_total)
        if self.ring.truncation_events > before:
            LOG.warning(
                "audio slice truncated (mark fell outside ring; lost %s event(s))",
                self.ring.truncation_events - before,
            )
        return samples

    def cancel(self) -> None:
        """Discard the active mark without taking a slice."""
        self._mark = None

    def switch_device(self, preferred: int | None) -> None:
        """Switch input device and restart stream."""
        new_device = find_wasapi_input(preferred)
        if new_device == self.device and self._stream is not None:
            return
        self.stop()
        self.cancel()
        self.ring.clear()
        self.device = new_device
        info = sd.query_devices(self.device)
        LOG.info(
            "switched WASAPI input device to %s (%s)",
            self.device,
            info["name"],
        )
        self.start()
