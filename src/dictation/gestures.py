from __future__ import annotations

import threading
import time
from collections.abc import Callable

from dictation.logutil import LOG


class GestureClassifier:
    """Classify Right Ctrl edges into press / release / tap / double_tap.

    Hold (>= hold_ms without release) → press, then release on key-up.
    Short tap → wait for a second tap within double_tap_ms; else emit tap.
    Two short taps → double_tap (no press).

    When ``continuous`` is set, the next key-down emits ``tap`` immediately
    (stop continuous) so the user does not wait out the double-tap window.

    All ``_emit`` calls happen while ``_lock`` is held so press/release cannot
    reorder at the 250ms hold boundary.
    """

    def __init__(
        self,
        emit: Callable[[str], None],
        *,
        hold_ms: int = 250,
        double_tap_ms: int = 350,
        clock: Callable[[], float] | None = None,
        timer_factory: Callable[..., threading.Timer] | None = None,
    ) -> None:
        self._emit = emit
        self._hold_ms = max(50, int(hold_ms))
        self._double_tap_ms = max(self._hold_ms + 50, int(double_tap_ms))
        self._clock = clock or time.monotonic
        self._timer_factory = timer_factory or threading.Timer
        self._lock = threading.RLock()
        self._down = False
        self._holding = False
        self._ignore_next_up = False
        self._continuous = False
        self._first_tap_at = 0.0
        self._hold_timer: threading.Timer | None = None
        self._tap_timer: threading.Timer | None = None

    @property
    def continuous(self) -> bool:
        with self._lock:
            return self._continuous

    def set_continuous(self, value: bool) -> None:
        with self._lock:
            self._continuous = bool(value)

    def _cancel_timer(self, attr: str) -> None:
        timer = getattr(self, attr)
        if timer is not None:
            timer.cancel()
            setattr(self, attr, None)

    def _emit_locked(self, ev: str) -> None:
        """Emit while holding ``_lock`` so ordering is preserved."""
        self._emit(ev)

    def on_down(self) -> None:
        with self._lock:
            if self._down:
                return
            # Continuous stop: fire tap immediately on key-down (no double-tap wait).
            if self._continuous:
                self._down = True
                self._ignore_next_up = True
                self._holding = False
                self._cancel_timer("_hold_timer")
                self._cancel_timer("_tap_timer")
                self._emit_locked("tap")
                return
            # Second tap while waiting for double-tap window.
            if self._tap_timer is not None:
                self._cancel_timer("_tap_timer")
                self._down = True
                self._ignore_next_up = True
                self._holding = False
                self._emit_locked("double_tap")
                return
            self._down = True
            self._holding = False
            self._ignore_next_up = False
            self._first_tap_at = self._clock()
            self._cancel_timer("_hold_timer")
            hold = self._timer_factory(self._hold_ms / 1000.0, self._on_hold_elapsed)
            hold.daemon = True
            self._hold_timer = hold
            hold.start()

    def on_up(self) -> None:
        with self._lock:
            if not self._down:
                return
            self._down = False
            self._cancel_timer("_hold_timer")
            if self._ignore_next_up:
                self._ignore_next_up = False
                self._holding = False
                return
            if self._holding:
                self._holding = False
                self._emit_locked("release")
                return
            # Short tap: wait to see if a second tap arrives.
            remaining = self._double_tap_ms / 1000.0 - (self._clock() - self._first_tap_at)
            delay = max(0.01, remaining)
            self._cancel_timer("_tap_timer")
            tap = self._timer_factory(delay, self._on_tap_elapsed)
            tap.daemon = True
            self._tap_timer = tap
            tap.start()

    def _on_hold_elapsed(self) -> None:
        with self._lock:
            self._hold_timer = None
            if not self._down or self._holding:
                return
            self._holding = True
            self._cancel_timer("_tap_timer")
            # Emit under lock so a near-boundary on_up cannot enqueue release first.
            self._emit_locked("press")

    def _on_tap_elapsed(self) -> None:
        with self._lock:
            self._tap_timer = None
            if self._down or self._holding:
                return
            self._emit_locked("tap")

    def force_release(self, reason: str) -> bool:
        """End an active hold-to-talk press; cancel pending tap/hold timers."""
        with self._lock:
            self._cancel_timer("_hold_timer")
            self._cancel_timer("_tap_timer")
            self._ignore_next_up = False
            was_holding = self._holding
            self._holding = False
            self._down = False
            if was_holding:
                LOG.info("force_release Right Ctrl: %s", reason)
                self._emit_locked("release")
                return True
            return False

    def reset(self) -> None:
        """Clear gesture state without emitting (used after Escape cancel)."""
        with self._lock:
            self._cancel_timer("_hold_timer")
            self._cancel_timer("_tap_timer")
            self._down = False
            self._holding = False
            self._ignore_next_up = False
