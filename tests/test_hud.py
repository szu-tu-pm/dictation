from __future__ import annotations

import time

from dictation.hud import (
    HudFrame,
    HudOverlay,
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
