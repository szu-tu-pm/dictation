import ctypes
import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

if sys.platform == "win32":
    from dictation.hotkey import (
        HC_ACTION,
        KBDLLHOOKSTRUCT,
        LLKHF_EXTENDED,
        LLKHF_UP,
        SCAN_CTRL,
        VK_CONTROL,
        VK_ESCAPE,
        VK_RCONTROL,
        RightCtrlHook,
        _is_right_ctrl,
    )


def _make_kbd_struct(vk: int, scan: int = 0, flags: int = 0):
    s = KBDLLHOOKSTRUCT()
    s.vkCode = vk
    s.scanCode = scan
    s.flags = flags
    return s


def test_is_right_ctrl_by_vk_rcontrol() -> None:
    data = _make_kbd_struct(vk=VK_RCONTROL)
    assert _is_right_ctrl(data) is True


def test_is_right_ctrl_by_vk_control_extended() -> None:
    data = _make_kbd_struct(vk=VK_CONTROL, flags=LLKHF_EXTENDED)
    assert _is_right_ctrl(data) is True


def test_is_right_ctrl_by_scan_ctrl_extended() -> None:
    data = _make_kbd_struct(vk=0, scan=SCAN_CTRL, flags=LLKHF_EXTENDED)
    assert _is_right_ctrl(data) is True


def test_is_left_ctrl_not_right_ctrl() -> None:
    data = _make_kbd_struct(vk=VK_CONTROL, scan=SCAN_CTRL, flags=0)
    assert _is_right_ctrl(data) is False


def test_other_keys_not_right_ctrl() -> None:
    data = _make_kbd_struct(vk=0x41)  # 'A'
    assert _is_right_ctrl(data) is False


def test_hook_force_release() -> None:
    on_event = MagicMock()
    hook = RightCtrlHook(on_event, hold_ms=50, double_tap_ms=120)

    assert hook.down is False
    assert hook.force_release("test_idle") is False
    assert on_event.call_count == 0

    with hook._down_lock:
        hook._down = True
    with hook._gestures._lock:
        hook._gestures._down = True
        hook._gestures._holding = True

    assert hook.force_release("test_stuck") is True
    assert hook.down is False
    on_event.assert_called_with("release")

    assert hook.force_release("test_stuck_again") is False


def test_hook_ll_proc_transitions() -> None:
    on_event = MagicMock()
    # Large hold_ms so classification does not fire during this LL-layer test.
    hook = RightCtrlHook(on_event, hold_ms=60_000, double_tap_ms=60_100)

    data_down = _make_kbd_struct(vk=VK_RCONTROL, flags=0)
    addr_down = ctypes.addressof(data_down)
    ret = hook._ll_proc(HC_ACTION, 0, addr_down)
    assert ret == 1
    assert hook.down is True

    # Typematic repeat while held
    ret = hook._ll_proc(HC_ACTION, 0, addr_down)
    assert ret == 1
    assert hook.down is True

    data_up = _make_kbd_struct(vk=VK_RCONTROL, flags=LLKHF_UP)
    addr_up = ctypes.addressof(data_up)
    ret = hook._ll_proc(HC_ACTION, 0, addr_up)
    assert ret == 1
    assert hook.down is False


def test_hook_escape_cancels_when_down() -> None:
    on_event = MagicMock()
    on_cancel = MagicMock(return_value=True)
    hook = RightCtrlHook(on_event, on_cancel, hold_ms=60_000, double_tap_ms=60_100)

    data_down = _make_kbd_struct(vk=VK_RCONTROL, flags=0)
    hook._ll_proc(HC_ACTION, 0, ctypes.addressof(data_down))
    assert hook.down is True

    esc_down = _make_kbd_struct(vk=VK_ESCAPE, flags=0)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_down))
    assert ret == 1
    assert hook.down is False
    assert on_cancel.call_count == 1

    data_up = _make_kbd_struct(vk=VK_RCONTROL, flags=LLKHF_UP)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(data_up))
    assert ret == 1
    assert on_event.call_count == 0

    esc_up = _make_kbd_struct(vk=VK_ESCAPE, flags=LLKHF_UP)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_up))
    assert ret == 1


def test_hook_escape_cancels_continuous_without_key_down() -> None:
    on_event = MagicMock()
    on_cancel = MagicMock(return_value=True)
    hook = RightCtrlHook(on_event, on_cancel)
    hook.set_continuous(True)
    assert hook.down is False

    esc_down = _make_kbd_struct(vk=VK_ESCAPE, flags=0)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_down))
    assert ret == 1
    assert on_cancel.call_count == 1
    assert hook._gestures.continuous is False


def test_hook_escape_auto_repeat_swallowed_while_cancelling() -> None:
    on_event = MagicMock()
    on_cancel = MagicMock(return_value=True)
    hook = RightCtrlHook(on_event, on_cancel, hold_ms=60_000, double_tap_ms=60_100)

    data_down = _make_kbd_struct(vk=VK_RCONTROL, flags=0)
    hook._ll_proc(HC_ACTION, 0, ctypes.addressof(data_down))
    assert hook.down is True

    esc_down = _make_kbd_struct(vk=VK_ESCAPE, flags=0)
    ret1 = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_down))
    assert ret1 == 1
    assert on_cancel.call_count == 1
    assert hook.down is False

    ret2 = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_down))
    assert ret2 == 1
    assert on_cancel.call_count == 1

    esc_up = _make_kbd_struct(vk=VK_ESCAPE, flags=LLKHF_UP)
    ret3 = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_up))
    assert ret3 == 1

    ret4 = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_down))
    assert ret4 == 0


def test_hook_escape_not_swallowed_when_on_cancel_returns_false() -> None:
    on_event = MagicMock()
    on_cancel = MagicMock(return_value=False)
    hook = RightCtrlHook(on_event, on_cancel, hold_ms=60_000, double_tap_ms=60_100)

    data_down = _make_kbd_struct(vk=VK_RCONTROL, flags=0)
    hook._ll_proc(HC_ACTION, 0, ctypes.addressof(data_down))
    assert hook.down is True

    esc_down = _make_kbd_struct(vk=VK_ESCAPE, flags=0)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_down))
    assert ret == 0
    assert hook.down is True
    assert on_cancel.call_count == 1


def test_hook_escape_passed_through_when_not_down() -> None:
    on_event = MagicMock()
    on_cancel = MagicMock()
    hook = RightCtrlHook(on_event, on_cancel)

    esc_down = _make_kbd_struct(vk=VK_ESCAPE, flags=0)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(esc_down))
    assert ret == 0
    assert on_cancel.call_count == 0


def test_hook_disabled_passthrough() -> None:
    on_event = MagicMock()
    hook = RightCtrlHook(on_event, hold_ms=60_000, double_tap_ms=60_100)
    assert hook.enabled is True

    hook.set_enabled(False)
    assert hook.enabled is False

    data_down = _make_kbd_struct(vk=VK_RCONTROL, flags=0)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(data_down))
    assert ret == 0
    assert hook.down is False
    assert on_event.call_count == 0

    hook.set_enabled(True)
    ret = hook._ll_proc(HC_ACTION, 0, ctypes.addressof(data_down))
    assert ret == 1
    assert hook.down is True
