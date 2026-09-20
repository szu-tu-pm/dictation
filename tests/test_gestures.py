from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from dictation.gestures import GestureClassifier


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


class ManualTimer:
    """threading.Timer stand-in that fires only when tests call fire()."""

    def __init__(self, delay: float, callback) -> None:
        self.delay = delay
        self.callback = callback
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


def _classifier(events: list[str], clock: FakeClock, timers: list[ManualTimer]) -> GestureClassifier:
    def factory(delay, cb):
        t = ManualTimer(delay, cb)
        timers.append(t)
        return t

    return GestureClassifier(
        events.append,
        hold_ms=250,
        double_tap_ms=350,
        clock=clock,
        timer_factory=factory,
    )


def test_hold_emits_press_then_release() -> None:
    events: list[str] = []
    clock = FakeClock()
    timers: list[ManualTimer] = []
    g = _classifier(events, clock, timers)

    g.on_down()
    assert events == []
    assert len(timers) == 1
    timers[0].fire()
    assert events == ["press"]
    g.on_up()
    assert events == ["press", "release"]


def test_short_tap_emits_tap_after_window() -> None:
    events: list[str] = []
    clock = FakeClock()
    timers: list[ManualTimer] = []
    g = _classifier(events, clock, timers)

    g.on_down()
    clock.advance(0.05)
    g.on_up()
    assert events == []
    assert timers[-1].cancelled is False
    timers[-1].fire()
    assert events == ["tap"]


def test_double_tap_emits_double_tap() -> None:
    events: list[str] = []
    clock = FakeClock()
    timers: list[ManualTimer] = []
    g = _classifier(events, clock, timers)

    g.on_down()
    clock.advance(0.04)
    g.on_up()
    tap_wait = timers[-1]
    clock.advance(0.1)
    g.on_down()
    assert events == ["double_tap"]
    assert tap_wait.cancelled is True
    g.on_up()
    assert events == ["double_tap"]


def test_continuous_emits_tap_immediately_on_down() -> None:
    events: list[str] = []
    clock = FakeClock()
    timers: list[ManualTimer] = []
    g = _classifier(events, clock, timers)
    g.set_continuous(True)

    g.on_down()
    assert events == ["tap"]
    assert all(t.cancelled or not t.started for t in timers) or len(timers) == 0
    g.on_up()
    assert events == ["tap"]


def test_force_release_only_when_holding() -> None:
    events: list[str] = []
    clock = FakeClock()
    timers: list[ManualTimer] = []
    g = _classifier(events, clock, timers)

    assert g.force_release("idle") is False

    g.on_down()
    assert g.force_release("pending") is False
    assert events == []

    g.on_down()
    timers[-1].fire()
    assert events == ["press"]
    assert g.force_release("max") is True
    assert events == ["press", "release"]


def test_reset_clears_without_emit() -> None:
    events: list[str] = []
    clock = FakeClock()
    timers: list[ManualTimer] = []
    g = _classifier(events, clock, timers)

    g.on_down()
    timers[0].fire()
    assert events == ["press"]
    g.reset()
    g.on_up()
    assert events == ["press"]


def test_emit_under_lock_orders_press_before_release_race() -> None:
    """Hold-boundary race: press must enqueue before release (emit under lock)."""
    events: list[str] = []
    emit_gate = threading.Event()
    release_started = threading.Event()
    clock = FakeClock()
    timers: list[ManualTimer] = []

    def emit(ev: str) -> None:
        events.append(ev)
        if ev == "press":
            # Signal that press emit began; keep the classifier lock held
            # until the racing on_up has blocked on the same lock.
            emit_gate.set()
            release_started.wait(timeout=1.0)
            time.sleep(0.02)

    def factory(delay, cb):
        t = ManualTimer(delay, cb)
        timers.append(t)
        return t

    g = GestureClassifier(
        emit,
        hold_ms=250,
        double_tap_ms=350,
        clock=clock,
        timer_factory=factory,
    )
    g.on_down()

    def racing_up() -> None:
        assert emit_gate.wait(timeout=1.0)
        release_started.set()
        g.on_up()

    thread = threading.Thread(target=racing_up, daemon=True)
    thread.start()
    timers[0].fire()
    thread.join(timeout=2.0)
    assert events == ["press", "release"]


def test_near_boundary_sequential_press_then_release() -> None:
    events: list[str] = []
    clock = FakeClock()
    timers: list[ManualTimer] = []
    g = _classifier(events, clock, timers)

    g.on_down()
    timers[0].fire()
    g.on_up()
    assert events == ["press", "release"]
