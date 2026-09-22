from __future__ import annotations

import time

from dictation.hud import (
    HudFrame,
    HudOverlay,
    _bind_hud_win32,
    map_app_state,
    pill_size,
    render_pill,
    work_area_position,
)


def test_map_app_state_recording_and_hidden() -> None:
    rec = map_app_state("recording", level=0.4, continuous=True)
    assert rec.mode == "recording"
    assert rec.continuous is True
    assert rec.level == 0.4
    assert map_app_state("idle").mode == "hidden"
    assert map_app_state("error").mode == "hidden"
    assert map_app_state("transcribing", elapsed_s=0.4).mode == "transcribing"


def test_pill_size_wider_when_continuous() -> None:
    normal = pill_size(HudFrame("recording", continuous=False))
    locked = pill_size(HudFrame("recording", continuous=True))
    assert locked[0] > normal[0]
    assert pill_size(HudFrame("hidden")) == (0, 0)


def test_work_area_position_bottom_center() -> None:
    x, y = work_area_position((0, 0, 1920, 1040), (148, 36))
    assert x == (1920 - 148) // 2
    assert y == 1040 - 36 - 12


def test_render_pill_modes() -> None:
    assert render_pill(HudFrame("hidden")) is None
    rec = render_pill(HudFrame("recording", level=0.8))
    assert rec is not None and rec.mode == "RGBA"
    tr = render_pill(HudFrame("transcribing", elapsed_s=0.5))
    assert tr is not None
    ok = render_pill(HudFrame("success"))
    assert ok is not None


def test_bind_hud_win32_pointer_sized_handles() -> None:
    """Win64 HDCs/LPARAMs exceed 32-bit; argtypes must accept them."""
    import ctypes
    import sys

    if sys.platform != "win32":
        return
    user32, gdi32, _kernel32 = _bind_hud_win32()
    big = 0x000001A326A44250  # typical high pointer from the OverflowError log
    # Must not raise OverflowError (the previous default c_int path did).
    gdi32.CreateCompatibleDC.argtypes[0].from_param(big)
    user32.ReleaseDC.argtypes[1].from_param(big)
    gdi32.SelectObject.argtypes[1].from_param(big)
    user32.DefWindowProcW.argtypes[3].from_param(big)
    assert user32.DefWindowProcW.restype is ctypes.c_ssize_t


def test_hud_overlay_disabled_is_noop() -> None:
    hud = HudOverlay(enabled=False)
    hud.start()
    hud.update("recording", level=0.5)
    hud.show_success()
    hud.stop()
    assert hud._frame.mode == "hidden"  # never advanced while disabled


def test_hud_success_survives_idle_update() -> None:
    hud = HudOverlay(enabled=True)
    # Do not start Win32 thread; exercise frame bookkeeping only.
    hud.show_success(duration_s=0.3)
    assert hud._frame.mode == "success"
    hud.update("idle")
    assert hud._frame.mode == "success"
    time.sleep(0.35)
    hud.update("idle")
    assert hud._frame.mode == "hidden"


def test_hud_loop_skips_idle_spins(monkeypatch) -> None:
    """Empty-queue wakes must not call _paint for static modes (CPU spin fix)."""
    hud = HudOverlay(enabled=True)
    hud._available = True
    paints: list[str] = []
    empty_wakes = {"n": 0}

    monkeypatch.setattr(hud, "_create_window", lambda: None)
    monkeypatch.setattr(hud, "_destroy_window", lambda: None)
    monkeypatch.setattr(hud, "_paint", lambda frame: paints.append(frame.mode))

    def fake_pump() -> None:
        # After the queued paint, Empty wakes hit pump — stop after a few.
        if not paints:
            return
        empty_wakes["n"] += 1
        if empty_wakes["n"] >= 3:
            hud._stop.set()

    monkeypatch.setattr(hud, "_pump_messages", fake_pump)

    hud._frame = HudFrame("recording", level=0.2)
    hud._q.put(HudFrame("recording", level=0.5))
    hud._loop()
    # Only the queued frame should paint — not Empty idle spins.
    assert paints == ["recording"]
    assert empty_wakes["n"] >= 3
