from __future__ import annotations

import argparse
from enum import Enum
from pathlib import Path
import queue
import threading
import time

import pystray

from dictation.assets import ensure_engine, ensure_model
from dictation.audio import AudioCapture, find_wasapi_input, peak_abs, rms
from dictation.config import load_config
from dictation.history import record_dictation
from dictation.hotkey import RightCtrlHook
from dictation.icons import tray_icon
from dictation.logutil import LOG, setup_logging
from dictation.paste import paste_text
from dictation.paths import appdata_dir, config_path, history_path, log_path, vocabulary_path
from dictation.sound import play_cue
from dictation.transcribe import WhisperEngine, load_wav_mono


class State(Enum):
    STARTING = "starting"
    DOWNLOADING = "downloading"
    LOADING = "loading"
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    ERROR = "error"


class DictationApp:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.state = State.STARTING
        self.status = "Starting…"
        self.backend = "unknown"
        self._lock = threading.RLock()
        self._ptt: queue.Queue[str] = queue.Queue()
        self._jobs: queue.Queue[object] = queue.Queue()
        self._stop = threading.Event()
        self.audio: AudioCapture | None = None
        self.hook: RightCtrlHook | None = None
        self.engine: WhisperEngine | None = None
        self.icon: pystray.Icon | None = None
        self._coord_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._error_gen = 0
        self._progress_last_pct = -1
        self._progress_last_ts = 0.0
        self._record_started = 0.0
        self._level_ui_ts = 0.0

    def _set_state(self, state: State, status: str, *, log: bool = True) -> None:
        with self._lock:
            self.state = state
            self.status = status
            if log:
                LOG.info("state=%s %s", state.value, status)
            self._refresh_icon(update_menu=True)

    def _refresh_icon(self, *, update_menu: bool = True) -> None:
        if self.icon is None:
            return
        visual = {
            State.STARTING: "loading",
            State.DOWNLOADING: "downloading",
            State.LOADING: "loading",
            State.IDLE: "idle",
            State.RECORDING: "recording",
            State.TRANSCRIBING: "transcribing",
            State.ERROR: "error",
        }[self.state]
        level = 0.0
        if self.state is State.RECORDING and self.audio is not None:
            level = self.audio.level
        self.icon.icon = tray_icon(visual, level=level)
        if self.state is State.RECORDING:
            self.icon.title = f"Dictation — Recording {int(level * 100)}%"
        else:
            self.icon.title = f"Dictation — {self.status}"
        if not update_menu:
            return
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(lambda _: self.status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self.quit),
        )

    def _on_progress(self, label: str, got: int, total: int) -> None:
        now = time.monotonic()
        if total > 0:
            pct = int(got * 100 / total)
            with self._lock:
                last_pct = self._progress_last_pct
                last_ts = self._progress_last_ts
                if (pct - last_pct) < 1 and (now - last_ts) < 0.5:
                    return
                log_progress = last_pct < 0 or (pct // 5) != (last_pct // 5) or pct >= 100
                self._progress_last_pct = pct
                self._progress_last_ts = now
            mb = got / (1024 * 1024)
            tot = total / (1024 * 1024)
            self._set_state(
                State.DOWNLOADING,
                f"Downloading {label} {pct}% ({mb:.0f}/{tot:.0f} MB)",
                log=log_progress,
            )
        else:
            with self._lock:
                if (now - self._progress_last_ts) < 0.5:
                    return
                self._progress_last_ts = now
            self._set_state(State.DOWNLOADING, f"Downloading {label}…")

    def _on_press(self) -> None:
        self._ptt.put("press")

    def _on_release(self) -> None:
        self._ptt.put("release")

    def _recover_from_error(self, gen: int) -> None:
        with self._lock:
            if self._error_gen != gen or self.state is not State.ERROR:
                return
            self._set_state(State.IDLE, f"Idle ({self.backend})")

    def _coordinator(self) -> None:
        while not self._stop.is_set():
            if self.audio is not None:
                pa = self.audio.drain_portaudio_status()
                if pa is not None:
                    LOG.warning("PortAudio status: %s", pa)

            with self._lock:
                recording = self.state is State.RECORDING
            if recording and self.hook is not None:
                elapsed = time.monotonic() - self._record_started
                if elapsed >= self.cfg.max_record_seconds:
                    self.hook.force_release("max_record_seconds")
            # Do not poll GetAsyncKeyState for Right Ctrl. The hook swallows the
            # key, so Windows key state stays "up" and a physical-up watchdog
            # would stop recording after ~50ms while the user is still holding.
            if recording and self.audio is not None:
                now = time.monotonic()
                if now - self._level_ui_ts >= 0.1:
                    self._level_ui_ts = now
                    with self._lock:
                        if self.state is State.RECORDING:
                            # Skip update_menu: rebuilding the tray menu at 10 Hz
                            # is expensive and dismisses an open context menu.
                            self._refresh_icon(update_menu=False)

            try:
                ev = self._ptt.get(timeout=0.05)
            except queue.Empty:
                continue
            if ev == "press":
                with self._lock:
                    if self.state is not State.IDLE or self.engine is None or not self.engine.ready:
                        continue
                    if self.audio is None:
                        continue
                    self.audio.mark_start()
                    self._record_started = time.monotonic()
                    self._set_state(State.RECORDING, "Recording")
                play_cue("start", enabled=self.cfg.sound_effects)
            elif ev == "release":
                with self._lock:
                    if self.state is not State.RECORDING or self.audio is None:
                        continue
                    self._set_state(State.TRANSCRIBING, "Transcribing…")
                play_cue("stop", enabled=self.cfg.sound_effects)
                self._jobs.put("slice")

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if self.engine is None or self.audio is None:
                    raise RuntimeError("worker started before engine/audio were ready")
                if job == "slice":
                    samples = self.audio.take_slice()
                else:
                    samples = job  # type: ignore[assignment]
                n = int(getattr(samples, "size", 0))
                LOG.info(
                    "transcribe start samples=%s duration=%.2fs rms=%.4f peak=%.4f",
                    n,
                    n / float(self.cfg.sample_rate),
                    rms(samples),
                    peak_abs(samples),
                )
                text = self.engine.transcribe(samples)  # type: ignore[arg-type]
                if text:
                    LOG.info("transcript: %s", text)
                    to_paste = text if text.endswith((" ", "\n")) else text + " "
                    paste_text(to_paste)
                    record_dictation(text)
                    play_cue("paste", enabled=self.cfg.sound_effects)
                else:
                    LOG.info("nothing to paste")
                    play_cue("discard", enabled=self.cfg.sound_effects)
            except Exception:
                LOG.exception("transcribe/paste failed")
                play_cue("discard", enabled=self.cfg.sound_effects)
                with self._lock:
                    self._error_gen += 1
                    gen = self._error_gen
                    self._set_state(State.ERROR, "Error — see log")
                threading.Timer(2.0, self._recover_from_error, args=(gen,)).start()
                continue
            if not self._stop.is_set():
                self._set_state(State.IDLE, f"Idle ({self.backend})")

    def _startup(self) -> None:
        try:
            self._set_state(State.DOWNLOADING, "Checking engine…")
            engine_dir = ensure_engine(self.cfg, self._on_progress)
            if self._stop.is_set():
                return
            model_path = ensure_model(self.cfg, self._on_progress)
            if self._stop.is_set():
                return
            self._set_state(State.LOADING, "Loading model…")
            self.engine = WhisperEngine(engine_dir, model_path, self.cfg)
            self._set_state(State.LOADING, "Warming up GPU (first run can take a minute)…")
            self.engine.load()
            if self._stop.is_set():
                return
            self.backend = self.engine.backend
            self.hook = RightCtrlHook(self._on_press, self._on_release)
            self.hook.start()
            self._set_state(State.IDLE, f"Idle ({self.backend})")
        except Exception as exc:
            if self._stop.is_set():
                return
            LOG.exception("startup failed")
            self._set_state(State.ERROR, f"Error: {exc}")

    def quit(self, icon=None, item=None) -> None:  # noqa: ANN001
        LOG.info("quit requested")
        self._stop.set()
        if self.icon is not None:
            self.icon.stop()

    def shutdown(self) -> None:
        if self.hook is not None:
            self.hook.stop()
        if self.audio is not None:
            self.audio.stop()
        if self.engine is not None:
            self.engine.close()
        LOG.info("stopped")

    def run(self) -> None:
        self.audio = AudioCapture(self.cfg)
        self.audio.start()
        # Hook is created and started in _startup after the model is ready,
        # so Right Ctrl is not swallowed during download/warmup.
        self._coord_thread = threading.Thread(target=self._coordinator, name="ptt", daemon=True)
        self._worker_thread = threading.Thread(target=self._worker, name="stt", daemon=True)
        self._coord_thread.start()
        self._worker_thread.start()
        threading.Thread(target=self._startup, name="startup", daemon=True).start()
        self.icon = pystray.Icon(
            "dictation",
            tray_icon("loading"),
            "Dictation — Starting…",
            self._menu(),
        )
        self.icon.run()
        self.shutdown()


def run_transcribe(wav: str) -> int:
    setup_logging()
    cfg = load_config()
    path = Path(wav)
    if not path.is_file():
        print(f"not found: {path}")
        return 2
    samples = load_wav_mono(path, cfg.sample_rate)
    n = int(samples.size)
    print(
        f"audio: {n / cfg.sample_rate:.2f}s rms={rms(samples):.4f} "
        f"peak={peak_abs(samples):.4f} path={path}"
    )
    if n == 0:
        print("empty audio; nothing to transcribe")
        return 1
    engine_dir = ensure_engine(cfg, lambda *_a, **_k: None)
    model_path = ensure_model(cfg, lambda *_a, **_k: None)
    engine = WhisperEngine(engine_dir, model_path, cfg)
    try:
        t0 = time.perf_counter()
        engine.load(warmup=False)
        t1 = time.perf_counter()
        text = engine.transcribe(samples, skip_gate=True)
        t2 = time.perf_counter()
        print(f"backend: {engine.backend}")
        print(f"load {t1 - t0:.2f}s | transcribe {t2 - t1:.2f}s")
        print(text or "(empty)")
    finally:
        engine.close()
    return 0


def run_check() -> int:
    setup_logging()
    cfg = load_config()
    print(f"config: {config_path()}")
    print(f"vocab:  {vocabulary_path()}")
    print(f"history:{history_path()}")
    print(f"data:   {appdata_dir()}")
    print(f"log:    {log_path()}")
    device = find_wasapi_input(cfg.device)
    print(f"WASAPI input device: {device}")
    hook = RightCtrlHook(lambda: None, lambda: None)
    hook.start()
    print("Right Ctrl hook: installed")
    hook.stop()
    print("Right Ctrl hook: removed")
    print("Hold Right Ctrl to talk after `python -m dictation`.")
    return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Windows local dictation")
    parser.add_argument("--check", action="store_true", help="verify WASAPI + hook, then exit")
    parser.add_argument(
        "--transcribe",
        metavar="WAV",
        help="transcribe a WAV file, print timing, and exit (no paste)",
    )
    args = parser.parse_args(argv)
    if args.check:
        raise SystemExit(run_check())
    if args.transcribe:
        raise SystemExit(run_transcribe(args.transcribe))
    setup_logging()
    LOG.info("dictation starting")
    DictationApp().run()


if __name__ == "__main__":
    main()
