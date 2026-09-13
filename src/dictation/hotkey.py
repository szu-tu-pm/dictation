from __future__ import annotations

import threading
from collections.abc import Callable
from ctypes import CFUNCTYPE, POINTER, byref, windll, wintypes
import ctypes

from dictation.logutil import LOG

WH_KEYBOARD_LL = 13
WM_QUIT = 0x0012
HC_ACTION = 0
LLKHF_EXTENDED = 0x01
LLKHF_UP = 0x80
VK_RCONTROL = 0xA3
VK_CONTROL = 0x11
SCAN_CTRL = 0x1D

LRESULT = ctypes.c_ssize_t
HHOOK = wintypes.HANDLE
HOOKPROC = CFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32 = windll.user32
kernel32 = windll.kernel32

user32.SetWindowsHookExW.restype = HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.GetMessageW.argtypes = [POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = wintypes.SHORT
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetCurrentThreadId.restype = wintypes.DWORD
kernel32.GetLastError.restype = wintypes.DWORD


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


def _is_right_ctrl(data: KBDLLHOOKSTRUCT) -> bool:
    if data.vkCode == VK_RCONTROL:
        return True
    extended = bool(data.flags & LLKHF_EXTENDED)
    if data.scanCode == SCAN_CTRL and extended:
        return True
    if data.vkCode == VK_CONTROL and extended:
        return True
    return False


def right_ctrl_physically_down() -> bool:
    """True if Right Ctrl is currently down according to GetAsyncKeyState."""
    return bool(user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000)


class RightCtrlHook:
    """Low-level hook that swallows Right Ctrl and never Left Ctrl."""

    def __init__(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._down = False
        self._down_lock = threading.Lock()
        self._hook = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._proc = HOOKPROC(self._ll_proc)
        self._ready = threading.Event()

    @property
    def down(self) -> bool:
        with self._down_lock:
            return self._down

    def force_release(self, reason: str) -> bool:
        """Synthesize on_release if hook still thinks Right Ctrl is down."""
        with self._down_lock:
            if not self._down:
                return False
            self._down = False
        LOG.warning("force_release Right Ctrl: %s", reason)
        self._on_release()
        return True

    def _ll_proc(self, ncode: int, wparam: int, lparam: int) -> int:
        try:
            if ncode == HC_ACTION:
                data = ctypes.cast(lparam, POINTER(KBDLLHOOKSTRUCT)).contents
                if _is_right_ctrl(data):
                    going_up = bool(data.flags & LLKHF_UP)
                    if going_up:
                        fire = False
                        with self._down_lock:
                            if self._down:
                                self._down = False
                                fire = True
                        if fire:
                            self._on_release()
                    else:
                        fire = False
                        with self._down_lock:
                            if not self._down:
                                self._down = True
                                fire = True
                        if fire:
                            self._on_press()
                    return 1
        except Exception:
            LOG.exception("keyboard hook callback failed")
        return int(user32.CallNextHookEx(self._hook, ncode, wparam, lparam) or 0)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="rctrl-hook", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("Right Ctrl hook thread failed to start")

    def _loop(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        handle = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, handle, 0)
        if not self._hook:
            LOG.error("SetWindowsHookExW failed: %s", kernel32.GetLastError())
            self._ready.set()
            return
        LOG.info("Right Ctrl low-level hook installed (swallowed)")
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    def stop(self) -> None:
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
