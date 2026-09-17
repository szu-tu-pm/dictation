from ctypes import byref, pointer
import sys
from unittest.mock import MagicMock

import pytest

from dictation.hotkey import (
    HC_ACTION,
    KBDLLHOOKSTRUCT,
    LLKHF_EXTENDED,
    LLKHF_UP,
    SCAN_CTRL,
    VK_CONTROL,
    VK_RCONTROL,
    RightCtrlHook,
    _is_right_ctrl,
)


def _make_kbd_struct(vk: int, scan: int = 0, flags: int = 0) -> KBDLLHOOKSTRUCT:
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
    # Standard Left Ctrl: vkCode VK_CONTROL without LLKHF_EXTENDED
    data = _make_kbd_struct(vk=VK_CONTROL, scan=SCAN_CTRL, flags=0)
    assert _is_right_ctrl(data) is False


def test_other_keys_not_right_ctrl() -> None:
    data = _make_kbd_struct(vk=0x41)  # 'A'
    assert _is_right_ctrl(data) is False


def test_hook_force_release() -> None:
    on_press = MagicMock()
    on_release = MagicMock()
    hook = RightCtrlHook(on_press, on_release)

    assert hook.down is False
    # Not down: force_release returns False and doesn't call on_release
    assert hook.force_release("test_idle") is False
    assert on_release.call_count == 0

    # Simulate key down
    with hook._down_lock:
        hook._down = True
    assert hook.down is True

    # Force release
    assert hook.force_release("test_stuck") is True
    assert hook.down is False
    assert on_release.call_count == 1

    # Second force release is a no-op
    assert hook.force_release("test_stuck_again") is False
    assert on_release.call_count == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ctypes hook structs only")
def test_hook_ll_proc_transitions() -> None:
    import ctypes

    on_press = MagicMock()
    on_release = MagicMock()
    hook = RightCtrlHook(on_press, on_release)

    # Press Right Ctrl
    data_down = _make_kbd_struct(vk=VK_RCONTROL, flags=0)
    addr_down = ctypes.addressof(data_down)
    ret = hook._ll_proc(HC_ACTION, 0, addr_down)
    assert ret == 1
    assert hook.down is True
    assert on_press.call_count == 1

    # Typematic repeat while held: down stays True, on_press not called again
    ret = hook._ll_proc(HC_ACTION, 0, addr_down)
    assert ret == 1
    assert hook.down is True
    assert on_press.call_count == 1

    # Release Right Ctrl
    data_up = _make_kbd_struct(vk=VK_RCONTROL, flags=LLKHF_UP)
    addr_up = ctypes.addressof(data_up)
    ret = hook._ll_proc(HC_ACTION, 0, addr_up)
    assert ret == 1
    assert hook.down is False
    assert on_release.call_count == 1

