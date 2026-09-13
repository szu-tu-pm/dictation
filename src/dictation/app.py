from __future__ import annotations

import argparse
import queue
import threading
import time
from enum import Enum

import pystray

from dictation.assets import ensure_engine, ensure_model
from dictation.audio import AudioCapture, find_wasapi_input
from dictation.config import load_config
from dictation.hotkey import RightCtrlHook, right_ctrl_physically_down
from dictation.icons import tray_icon
from dictation.logutil import LOG, setup_logging
from dictation.paste import paste_text
from dictation.paths import appdata_dir, config_path, log_path
from dictation.transcribe import WhisperEngine


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
        self._coord: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._error_gen = 0
        self._progress_last_pct = -1
        self._progress_last_ts = 0.0
        self._record_started = 0.0

    def _set_state(self, state: State, status: str, *, log: bool = True) -> None:
        with self._lock:
            self.state = state
            self.status = status
            if log:
                LOG.info("state=%s %s", state.value, status)
            self._refresh_icon()

    def _refresh_icon(self) -> None:
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
        self.icon.icon = tray_icon(visual)
        self.icon.title = f"Dictation — {self.status}"
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
                elif self.hook.down and not right_ctrl_physically_down():
                    self.hook.force_release("right_ctrl_physically_up")

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
            elif ev == "release":
                with self._lock:
                    if self.state is not State.RECORDING or self.audio is None:
                        continue
                    self._set_state(State.TRANSCRIBING, "Transcribing…")
                self._jobs.put("slice")

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                assert self.engine is not None
                assert self.audio is not None
                if job == "slice":
                    samples = self.audio.take_slice()
                else:
                    samples = job  # type: ignore[assignment]
                text = self.engine.transcribe(samples)  # type: ignore[arg-type]
                if text:
                    LOG.info("transcript: %s", text)
                    paste_text(text)
                else:
                    LOG.info("nothing to paste")
            except Exception:
                LOG.exception("transcribe/paste failed")
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
            model_path = ensure_model(self.cfg, self._on_progress)
            self._set_state(State.LOADING, "Loading model…")
            self.engine = WhisperEngine(engine_dir, model_path, self.cfg)
            self.engine.load()
            self.backend = self.engine.backend
            if self.hook is None:
                self.hook = RightCtrlHook(self._on_press, self._on_release)
            self.hook.start()
            self._set_state(State.IDLE, f"Idle ({self.backend})")
        except Exception as exc:
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
        self.hook = RightCtrlHook(self._on_press, self._on_release)
        self._coord = threading.Thread(target=self._coordinator, name="ptt", daemon=True)
        self._worker = threading.Thread(target=self._worker, name="stt", daemon=True)
        self._coord.start()
        self._worker.start()
        threading.Thread(target=self._startup, name="startup", daemon=True).start()
        self.icon = pystray.Icon(
            "dictation",
            tray_icon("loading"),
            "Dictation — Starting…",
            self._menu(),
        )
        self.icon.run()
        self.shutdown()


def run_check() -> int:
    setup_logging()
    cfg = load_config()
    print(f"config: {config_path()}")
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
    args = parser.parse_args(argv)
    if args.check:
        raise SystemExit(run_check())
    setup_logging()
    LOG.info("dictation starting")
    DictationApp().run()


if __name__ == "__main__":
    main()
