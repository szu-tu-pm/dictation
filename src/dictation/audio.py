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
            start_abs = max(start_abs, max(0, self.total - self.n))
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

    @property
    def write_total(self) -> int:
        with self._lock:
            return self.total


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


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


class AudioCapture:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.ring = RingBuffer(cfg.ring_seconds, cfg.sample_rate)
        self._stream: sd.InputStream | None = None
        self._mark: int | None = None
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
            LOG.warning("PortAudio status: %s", status)
        self.ring.write(indata[:, 0])

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
        preroll = int(self.cfg.sample_rate * self.cfg.preroll_ms / 1000)
        self._mark = max(0, self.ring.write_total - preroll)

    def take_slice(self) -> np.ndarray:
        suffix = int(self.cfg.sample_rate * self.cfg.suffix_ms / 1000)
        if suffix > 0:
            time.sleep(self.cfg.suffix_ms / 1000)
        start = 0 if self._mark is None else self._mark
        self._mark = None
        return self.ring.copy_abs(start, self.ring.write_total)
