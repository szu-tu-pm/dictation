from __future__ import annotations

from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_bool,
    c_char_p,
    c_float,
    c_int,
    c_size_t,
    c_void_p,
    cast,
    create_string_buffer,
)
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave
from typing import TYPE_CHECKING, Any

import numpy as np

from dictation.config import AppConfig
from dictation.logutil import LOG
from dictation.paths import tmp_dir
from dictation.text import is_ghost, strip_fillers
from dictation.vocabulary import apply_replacements, load_vocabulary

if TYPE_CHECKING:
    from ctypes import WinDLL

WHISPER_SAMPLING_GREEDY = 0
CREATE_NO_WINDOW = 0x08000000

LogCallback = CFUNCTYPE(None, c_int, c_char_p, c_void_p)


def _as_addr(ptr: int | c_void_p | None) -> int:
    if ptr is None:
        raise RuntimeError("null pointer")
    if isinstance(ptr, int):
        return ptr
    value = getattr(ptr, "value", ptr)
    if not value:
        raise RuntimeError("null pointer")
    return int(value)


def _path_for_fopen(path: Path) -> bytes:
    """Bytes path suitable for C fopen / whisper_init_from_file (short path on Win32)."""
    s = str(path)
    if sys.platform == "win32":
        from ctypes import create_unicode_buffer, windll

        need = windll.kernel32.GetShortPathNameW(s, None, 0)
        if need:
            buf = create_unicode_buffer(need)
            if windll.kernel32.GetShortPathNameW(s, buf, need):
                return buf.value.encode("utf-8")
    return s.encode("utf-8")


class WhisperContextParams(Structure):
    _fields_ = [
        ("use_gpu", c_bool),
        ("flash_attn", c_bool),
        ("gpu_device", c_int),
        ("dtw_token_timestamps", c_bool),
        ("dtw_aheads_preset", c_int),
        ("dtw_n_top", c_int),
        ("dtw_aheads_n_heads", c_size_t),
        ("dtw_aheads_heads", c_void_p),
        ("dtw_mem_size", c_size_t),
    ]


class WhisperFullParamsPrefix(Structure):
    """Prefix of whisper_full_params; overlaid on a DLL-allocated blob."""

    _fields_ = [
        ("strategy", c_int),
        ("n_threads", c_int),
        ("n_max_text_ctx", c_int),
        ("offset_ms", c_int),
        ("duration_ms", c_int),
        ("translate", c_bool),
        ("no_context", c_bool),
        ("no_timestamps", c_bool),
        ("single_segment", c_bool),
        ("print_special", c_bool),
        ("print_progress", c_bool),
        ("print_realtime", c_bool),
        ("print_timestamps", c_bool),
        ("token_timestamps", c_bool),
        ("thold_pt", c_float),
        ("thold_ptsum", c_float),
        ("max_len", c_int),
        ("split_on_word", c_bool),
        ("max_tokens", c_int),
        ("debug_mode", c_bool),
        ("audio_ctx", c_int),
        ("tdrz_enable", c_bool),
        ("suppress_regex", c_char_p),
        ("initial_prompt", c_char_p),
        ("carry_initial_prompt", c_bool),
        ("prompt_tokens", c_void_p),
        ("prompt_n_tokens", c_int),
        ("language", c_char_p),
        ("detect_language", c_bool),
        ("suppress_blank", c_bool),
        ("suppress_nst", c_bool),
        ("temperature", c_float),
        ("max_initial_ts", c_float),
        ("length_penalty", c_float),
        ("temperature_inc", c_float),
        ("entropy_thold", c_float),
        ("logprob_thold", c_float),
        ("no_speech_thold", c_float),
    ]


def _write_wav(path: Path, samples: np.ndarray, samplerate: int) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(samplerate)
        wav.writeframes(pcm.tobytes())


def load_wav_mono(path: Path, sample_rate: int) -> np.ndarray:
    """Load a PCM WAV as 16 kHz-or-target-rate mono float32."""
    with wave.open(str(path), "rb") as wav:
        nch = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width == 2:
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        pcm = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        pcm = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise RuntimeError(f"unsupported WAV sample width {width}")
    if nch > 1:
        pcm = pcm.reshape(-1, nch).mean(axis=1)
    if rate != sample_rate and pcm.size:
        duration = pcm.size / float(rate)
        n_out = max(1, int(round(duration * sample_rate)))
        x_old = np.linspace(0.0, 1.0, int(pcm.size), endpoint=False)
        x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
        pcm = np.interp(x_new, x_old, pcm).astype(np.float32)
    return np.ascontiguousarray(pcm, dtype=np.float32)


def too_quiet(samples: np.ndarray, threshold: float, min_samples: int) -> bool:
    if samples.size < min_samples:
        return True
    energy = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    return energy < threshold and peak < threshold * 4


class WhisperEngine:
    def __init__(self, engine_dir: Path, model_path: Path, cfg: AppConfig) -> None:
        self.engine_dir = engine_dir
        self.model_path = model_path
        self.cfg = cfg
        self.backend = "unknown"
        self.ready = False
        self._impl: _DllEngine | _CliEngine | None = None

    def load(self, *, warmup: bool = True) -> None:
        dll_path = self.engine_dir / "whisper.dll"
        if dll_path.is_file():
            try:
                self._impl = _DllEngine(self.engine_dir, self.model_path, self.cfg)
                self._impl.load()
                self.backend = self._impl.backend
                self.ready = True
                LOG.info("whisper.dll ready backend=%s", self.backend)
                if warmup:
                    self.warmup()
                return
            except Exception:
                LOG.exception("whisper.dll init failed; falling back to whisper-cli")
        self._impl = _CliEngine(self.engine_dir, self.model_path, self.cfg)
        self._impl.load()
        self.backend = self._impl.backend
        self.ready = True
        LOG.info("whisper-cli ready backend=%s", self.backend)
        if warmup:
            self.warmup()

    def warmup(self) -> None:
        """Run one throwaway inference so Vulkan shaders compile before PTT."""
        if self._impl is None:
            return
        n = max(1, int(self.cfg.sample_rate * 0.5))
        rng = np.random.default_rng(0)
        samples = (rng.standard_normal(n) * 0.05).astype(np.float32)
        LOG.info("warmup transcribe starting samples=%s", n)
        t0 = time.perf_counter()
        try:
            self._impl.transcribe(samples)
        except Exception:
            LOG.exception("warmup transcribe failed")
            return
        LOG.info("warmup transcribe done in %.2fs backend=%s", time.perf_counter() - t0, self.backend)

    def transcribe(self, samples: np.ndarray, *, skip_gate: bool = False) -> str | None:
        if samples.size == 0:
            LOG.info("skipping empty capture")
            return None
        min_samples = int(self.cfg.sample_rate * self.cfg.min_hold_ms / 1000)
        if not skip_gate and too_quiet(samples, self.cfg.energy_threshold, min_samples):
            LOG.info("skipping quiet/short capture (%s samples)", samples.size)
            return None
        if self._impl is None:
            raise RuntimeError("engine not loaded")
        vocab = load_vocabulary()
        prompt = vocab.prompt()
        raw = self._impl.transcribe(samples, prompt=prompt)
        text = apply_replacements(strip_fillers(raw), vocab)
        if is_ghost(text):
            LOG.info("skipping ghost transcript: %r", text)
            return None
        return text

    def close(self) -> None:
        if self._impl is not None:
            self._impl.close()
            self._impl = None
        self.ready = False


class _DllEngine:
    def __init__(self, engine_dir: Path, model_path: Path, cfg: AppConfig) -> None:
        self.engine_dir = engine_dir
        self.model_path = model_path
        self.cfg = cfg
        self.backend = "cpu"
        self._dll: Any | None = None
        self._ctx = c_void_p()
        self._log_cb = None
        self._lang = create_string_buffer(cfg.language.encode("ascii") or b"en")
        self._prompt_buf = None
        self._logs: list[str] = []

    def _on_log(self, level: int, text: bytes | None, user: int) -> None:
        if not text:
            return
        line = text.decode("utf-8", "replace").rstrip()
        if not line:
            return
        self._logs.append(line)
        LOG.info("whisper: %s", line)

    def _bind(self) -> Any:
        from ctypes import WinDLL

        os.add_dll_directory(str(self.engine_dir))
        dll = WinDLL(str(self.engine_dir / "whisper.dll"))
        dll.whisper_log_set.argtypes = [LogCallback, c_void_p]
        dll.whisper_context_default_params_by_ref.restype = c_void_p
        dll.whisper_init_from_file_with_params.argtypes = [c_char_p, c_void_p]
        dll.whisper_init_from_file_with_params.restype = c_void_p
        dll.whisper_free.argtypes = [c_void_p]
        dll.whisper_free_context_params.argtypes = [c_void_p]
        dll.whisper_free_params.argtypes = [c_void_p]
        dll.whisper_full_default_params_by_ref.argtypes = [c_int]
        dll.whisper_full_default_params_by_ref.restype = c_void_p
        # Win64: large structs are passed as a pointer to a copy.
        dll.whisper_full.argtypes = [c_void_p, c_void_p, POINTER(c_float), c_int]
        dll.whisper_full.restype = c_int
        dll.whisper_full_n_segments.argtypes = [c_void_p]
        dll.whisper_full_n_segments.restype = c_int
        dll.whisper_full_get_segment_text.argtypes = [c_void_p, c_int]
        dll.whisper_full_get_segment_text.restype = c_char_p
        dll.whisper_print_system_info.restype = c_char_p
        return dll

    def _init_ctx(self, use_gpu: bool) -> c_void_p:
        if self._dll is None:
            raise RuntimeError("whisper.dll is not bound")
        params_ptr = self._dll.whisper_context_default_params_by_ref()
        if not params_ptr:
            raise RuntimeError("whisper_context_default_params_by_ref returned NULL")
        overlay = WhisperContextParams.from_address(_as_addr(params_ptr))
        overlay.use_gpu = use_gpu
        # Flash-attn Vulkan shaders on AMD can stall the first whisper_full for minutes.
        overlay.flash_attn = False
        overlay.gpu_device = 0
        try:
            ctx = self._dll.whisper_init_from_file_with_params(
                _path_for_fopen(self.model_path), params_ptr
            )
        finally:
            self._dll.whisper_free_context_params(params_ptr)
        return ctx

    def load(self) -> None:
        self._dll = self._bind()
        self._log_cb = LogCallback(self._on_log)
        self._dll.whisper_log_set(self._log_cb, None)
        ctx = self._init_ctx(use_gpu=True)
        if ctx:
            self.backend = "vulkan"
            self._ctx = c_void_p(ctx)
            info = (self._dll.whisper_print_system_info() or b"").decode("utf-8", "replace")
            LOG.info("system info: %s", info)
            return
        LOG.warning("Vulkan/GPU init failed; retrying CPU")
        ctx = self._init_ctx(use_gpu=False)
        if not ctx:
            raise RuntimeError("whisper_init_from_file_with_params failed (GPU and CPU)")
        self.backend = "cpu"
        self._ctx = c_void_p(ctx)

    def transcribe(self, samples: np.ndarray, prompt: str = "") -> str:
        if self._dll is None or not self._ctx:
            raise RuntimeError("whisper.dll context is not loaded")
        pcm = np.ascontiguousarray(samples, dtype=np.float32)
        if pcm.size == 0:
            return ""
        params_ptr = self._dll.whisper_full_default_params_by_ref(WHISPER_SAMPLING_GREEDY)
        if not params_ptr:
            raise RuntimeError("whisper_full_default_params_by_ref returned NULL")
        p = WhisperFullParamsPrefix.from_address(_as_addr(params_ptr))
        if not (1 <= p.n_threads <= 512):
            self._dll.whisper_free_params(params_ptr)
            raise RuntimeError(f"whisper_full_params overlay looks wrong (n_threads={p.n_threads})")
        threads = os.cpu_count() or 4
        p.n_threads = max(1, min(8, threads))
        p.translate = False
        p.no_context = True
        p.no_timestamps = True
        p.single_segment = True
        p.print_special = False
        p.print_progress = True
        p.print_realtime = False
        p.print_timestamps = False
        p.language = cast(self._lang, c_char_p)
        p.detect_language = False
        p.suppress_nst = True
        p.no_speech_thold = 0.6
        if prompt:
            self._prompt_buf = create_string_buffer(prompt.encode("utf-8"))
            p.initial_prompt = cast(self._prompt_buf, c_char_p)
            LOG.info("whisper prompt: %s", prompt[:120])
        else:
            self._prompt_buf = None
        LOG.info("whisper_full begin n_samples=%s", int(pcm.size))
        t0 = time.perf_counter()
        try:
            rc = self._dll.whisper_full(
                self._ctx, params_ptr, pcm.ctypes.data_as(POINTER(c_float)), int(pcm.size)
            )
        finally:
            self._dll.whisper_free_params(params_ptr)
        LOG.info("whisper_full done rc=%s elapsed=%.2fs", rc, time.perf_counter() - t0)
        if rc != 0:
            raise RuntimeError(f"whisper_full failed rc={rc}")
        n = self._dll.whisper_full_n_segments(self._ctx)
        parts: list[str] = []
        for i in range(n):
            seg = self._dll.whisper_full_get_segment_text(self._ctx, i)
            if seg:
                parts.append(seg.decode("utf-8", "replace") if isinstance(seg, bytes) else str(seg))
        return "".join(parts).strip()

    def close(self) -> None:
        if self._dll is not None and self._ctx:
            self._dll.whisper_free(self._ctx)
            self._ctx = c_void_p()


class _CliEngine:
    def __init__(self, engine_dir: Path, model_path: Path, cfg: AppConfig) -> None:
        self.exe = engine_dir / "whisper-cli.exe"
        self.model_path = model_path
        self.cfg = cfg
        self.backend = "cli-gpu"
        self._gpu_ok = True

    def load(self) -> None:
        if not self.exe.is_file():
            raise FileNotFoundError(self.exe)

    def transcribe(self, samples: np.ndarray, prompt: str = "") -> str:
        try:
            return self._run(samples, use_gpu=self._gpu_ok, prompt=prompt)
        except Exception:
            if not self._gpu_ok:
                raise
            LOG.exception("whisper-cli GPU run failed; retrying --no-gpu")
            self._gpu_ok = False
            self.backend = "cli-cpu"
            return self._run(samples, use_gpu=False, prompt=prompt)

    def _run(self, samples: np.ndarray, use_gpu: bool, prompt: str = "") -> str:
        import shutil

        tmp = Path(tempfile.mkdtemp(dir=tmp_dir()))
        try:
            wav = tmp / "utt.wav"
            out_prefix = tmp / "utt"
            _write_wav(wav, samples, self.cfg.sample_rate)
            cmd = [
                str(self.exe),
                "-m",
                str(self.model_path),
                "-f",
                str(wav),
                "-l",
                self.cfg.language,
                "-nt",
                "-sns",
                "-np",
                "-otxt",
                "-of",
                str(out_prefix),
            ]
            if prompt:
                cmd.extend(["-prompt", prompt])
            if not use_gpu:
                cmd.append("-ng")
                self.backend = "cli-cpu"
            LOG.info("running %s", " ".join(cmd))
            kwargs: dict[str, Any] = {
                "cwd": str(self.exe.parent),
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "timeout": 120,
            }
            if sys.platform == "win32":
                kwargs["creationflags"] = CREATE_NO_WINDOW
            proc = subprocess.run(cmd, **kwargs)
            if proc.stderr:
                LOG.info("whisper-cli stderr: %s", proc.stderr[-2000:])
                if "vulkan" in proc.stderr.lower() and use_gpu:
                    self.backend = "cli-vulkan"
            if proc.returncode != 0:
                raise RuntimeError(f"whisper-cli exited {proc.returncode}: {proc.stderr[-500:]}")
            txt = out_prefix.with_suffix(".txt")
            if txt.is_file():
                return txt.read_text(encoding="utf-8", errors="replace").strip()
            return (proc.stdout or "").strip()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def close(self) -> None:
        return
