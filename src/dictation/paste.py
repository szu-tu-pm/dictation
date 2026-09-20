from __future__ import annotations

import time
from ctypes import POINTER, byref, c_void_p, sizeof, windll, wintypes
import ctypes

from dictation.logutil import LOG

user32 = windll.user32
kernel32 = windll.kernel32

HWND = wintypes.HWND
BOOL = wintypes.BOOL
UINT = wintypes.UINT
DWORD = wintypes.DWORD
HANDLE = wintypes.HANDLE

CF_TEXT = 1
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
WM_PASTE = 0x0302
SMTO_ABORTIFHUNG = 0x0002
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_MENU = 0x12
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_V = 0x56

user32.OpenClipboard.argtypes = [HWND]
user32.OpenClipboard.restype = BOOL
user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = BOOL
user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = BOOL
user32.GetClipboardData.argtypes = [UINT]
user32.GetClipboardData.restype = HANDLE
user32.SetClipboardData.argtypes = [UINT, HANDLE]
user32.SetClipboardData.restype = HANDLE
user32.EnumClipboardFormats.argtypes = [UINT]
user32.EnumClipboardFormats.restype = UINT
user32.IsClipboardFormatAvailable.argtypes = [UINT]
user32.IsClipboardFormatAvailable.restype = BOOL
user32.GetOpenClipboardWindow.argtypes = []
user32.GetOpenClipboardWindow.restype = HWND
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = HWND
user32.GetWindowThreadProcessId.argtypes = [HWND, POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
user32.AttachThreadInput.restype = BOOL
user32.GetGUIThreadInfo.argtypes = [DWORD, c_void_p]
user32.GetGUIThreadInfo.restype = BOOL
user32.SendMessageTimeoutW.argtypes = [
    HWND, UINT, wintypes.WPARAM, wintypes.LPARAM, UINT, UINT, POINTER(ctypes.c_size_t)
]
user32.SendMessageTimeoutW.restype = ctypes.c_size_t
user32.SendInput.argtypes = [UINT, c_void_p, ctypes.c_int]
user32.SendInput.restype = UINT

kernel32.GlobalAlloc.argtypes = [UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = HANDLE
kernel32.GlobalLock.argtypes = [HANDLE]
kernel32.GlobalLock.restype = c_void_p
kernel32.GlobalUnlock.argtypes = [HANDLE]
kernel32.GlobalUnlock.restype = BOOL
kernel32.GlobalSize.argtypes = [HANDLE]
kernel32.GlobalSize.restype = ctypes.c_size_t
kernel32.GlobalFree.argtypes = [HANDLE]
kernel32.GlobalFree.restype = HANDLE
kernel32.GetCurrentThreadId.restype = DWORD
kernel32.GetCurrentProcessId.restype = DWORD
kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = HANDLE
kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.CloseHandle.restype = BOOL

SKIP_FORMATS = {2, 3, 8, 9, 14}  # bitmaps / palette / metafiles


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("flags", DWORD),
        ("hwndActive", HWND),
        ("hwndFocus", HWND),
        ("hwndCapture", HWND),
        ("hwndMenuOwner", HWND),
        ("hwndMoveSize", HWND),
        ("hwndCaret", HWND),
        ("rcCaret", RECT),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", DWORD),
        ("time", DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]

    _anonymous_ = ("i",)
    _fields_ = [("type", DWORD), ("i", _I)]


def _open_clipboard(retries: int = 20) -> bool:
    for _ in range(retries):
        if user32.OpenClipboard(None):
            return True
        time.sleep(0.01)
    return False


def _snapshot() -> dict[int, bytes]:
    data: dict[int, bytes] = {}
    if not _open_clipboard():
        LOG.warning("OpenClipboard failed while snapshotting")
        return data
    try:
        fmt = 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if fmt == 0:
                break
            if fmt in SKIP_FORMATS:
                continue
            handle = user32.GetClipboardData(fmt)
            if not handle:
                continue
            size = int(kernel32.GlobalSize(handle))
            if size <= 0 or size > 16 * 1024 * 1024:
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                continue
            try:
                data[fmt] = ctypes.string_at(ptr, size)
            finally:
                kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
    return data


def _restore(snapshot: dict[int, bytes]) -> None:
    if not _open_clipboard():
        LOG.warning("OpenClipboard failed while restoring")
        return
    try:
        user32.EmptyClipboard()
        for fmt, blob in snapshot.items():
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(blob))
            if not handle:
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                kernel32.GlobalFree(handle)
                continue
            ctypes.memmove(ptr, blob, len(blob))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(fmt, handle):
                kernel32.GlobalFree(handle)
    finally:
        user32.CloseClipboard()


def _set_text(text: str) -> None:
    payload = text.encode("utf-16-le") + b"\x00\x00"
    if not _open_clipboard():
        raise RuntimeError("OpenClipboard failed while setting transcript")
    try:
        user32.EmptyClipboard()
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not handle:
            raise RuntimeError("GlobalAlloc failed")
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            raise RuntimeError("GlobalLock failed")
        ctypes.memmove(ptr, payload, len(payload))
        kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            kernel32.GlobalFree(handle)
            raise RuntimeError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def _focused_hwnd() -> int:
    fg = user32.GetForegroundWindow()
    if not fg:
        return 0
    pid = DWORD(0)
    tid = user32.GetWindowThreadProcessId(fg, byref(pid))
    our = kernel32.GetCurrentThreadId()
    attached = False
    if tid and tid != our:
        attached = bool(user32.AttachThreadInput(our, tid, True))
    try:
        info = GUITHREADINFO()
        info.cbSize = sizeof(GUITHREADINFO)
        if user32.GetGUIThreadInfo(tid, byref(info)) and info.hwndFocus:
            return int(info.hwndFocus)
        return int(fg)
    finally:
        if attached:
            user32.AttachThreadInput(our, tid, False)


def _token_elevated(token: HANDLE) -> bool | None:
    """Return True/False for TokenElevation, or None if the query fails."""
    TokenElevation = 20
    class TOKEN_ELEVATION(ctypes.Structure):
        _fields_ = [("TokenIsElevated", DWORD)]

    elev = TOKEN_ELEVATION()
    needed = DWORD(0)
    advapi = windll.advapi32
    advapi.GetTokenInformation.argtypes = [
        HANDLE, ctypes.c_int, c_void_p, DWORD, POINTER(DWORD)
    ]
    advapi.GetTokenInformation.restype = BOOL
    ok = advapi.GetTokenInformation(
        token, TokenElevation, byref(elev), sizeof(elev), byref(needed)
    )
    if not ok:
        return None
    return bool(elev.TokenIsElevated)


def _process_elevated(pid: int) -> bool | None:
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        token = HANDLE()
        advapi = windll.advapi32
        advapi.OpenProcessToken.argtypes = [HANDLE, DWORD, POINTER(HANDLE)]
        advapi.OpenProcessToken.restype = BOOL
        if not advapi.OpenProcessToken(handle, TOKEN_QUERY, byref(token)):
            return None
        try:
            return _token_elevated(token)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(handle)


def _uipi_blocks_paste() -> bool:
    """True when the focused window is elevated and we are not (SendInput is a no-op)."""
    fg = user32.GetForegroundWindow()
    if not fg:
        return False
    pid = DWORD(0)
    user32.GetWindowThreadProcessId(fg, byref(pid))
    if not pid.value:
        return False
    ours = _process_elevated(kernel32.GetCurrentProcessId())
    theirs = _process_elevated(int(pid.value))
    if ours is None or theirs is None:
        return False
    return (not ours) and theirs


def _wm_paste(hwnd: int, timeout_ms: int = 200) -> bool:
    if not hwnd:
        return False
    result = ctypes.c_size_t(0)
    sent = user32.SendMessageTimeoutW(
        hwnd, WM_PASTE, 0, 0, SMTO_ABORTIFHUNG, timeout_ms, byref(result)
    )
    return bool(sent)


UNICODE_CHUNK = 20
UNICODE_CHUNK_SLEEP_S = 0.003


def _unicode_units(text: str) -> list[int]:
    chars: list[int] = []
    normalized = text.replace("\r\n", "\n").replace("\n", "\r")
    for ch in normalized:
        code = ord(ch)
        if code == 0:
            continue
        if code > 0xFFFF:
            encoded = ch.encode("utf-16-le")
            chars.append(int.from_bytes(encoded[:2], "little"))
            chars.append(int.from_bytes(encoded[2:], "little"))
        else:
            chars.append(code)
    return chars


def _send_unicode_chunk(units: list[int]) -> int:
    n = len(units) * 2
    if n == 0:
        return 0
    arr = (INPUT * n)()
    for i, code in enumerate(units):
        down = arr[i * 2]
        up = arr[i * 2 + 1]
        down.type = INPUT_KEYBOARD
        down.ki.wVk = 0
        down.ki.wScan = code
        down.ki.dwFlags = KEYEVENTF_UNICODE
        up.type = INPUT_KEYBOARD
        up.ki.wVk = 0
        up.ki.wScan = code
        up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    return int(user32.SendInput(n, arr, sizeof(INPUT)))


def _send_unicode(text: str) -> int:
    units = _unicode_units(text)
    if not units:
        return 0
    sent = 0
    i = 0
    while i < len(units):
        if i:
            time.sleep(UNICODE_CHUNK_SLEEP_S)
        end = min(i + UNICODE_CHUNK, len(units))
        # Do not split a UTF-16 surrogate pair across SendInput chunks.
        if end < len(units) and 0xD800 <= units[end - 1] <= 0xDBFF:
            end -= 1
            if end <= i:
                end = i + 2
        n = _send_unicode_chunk(units[i:end])
        if n == 0:
            return sent
        sent += n
        i = end
    return sent


def _release_modifiers() -> None:
    """Synthesize key-ups for Shift/Alt/Win so Ctrl+V is not Ctrl+Shift+V etc."""
    vks = (
        VK_SHIFT,
        VK_LSHIFT,
        VK_RSHIFT,
        VK_MENU,
        VK_LMENU,
        VK_RMENU,
        VK_LWIN,
        VK_RWIN,
    )
    arr = (INPUT * len(vks))()
    for i, vk in enumerate(vks):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki.wVk = vk
        arr[i].ki.dwFlags = KEYEVENTF_KEYUP
    user32.SendInput(len(vks), arr, sizeof(INPUT))


def _send_ctrl_v() -> None:
    _release_modifiers()
    arr = (INPUT * 4)()
    seq = [
        (VK_CONTROL, 0),
        (VK_V, 0),
        (VK_V, KEYEVENTF_KEYUP),
        (VK_CONTROL, KEYEVENTF_KEYUP),
    ]
    for i, (vk, flags) in enumerate(seq):
        arr[i].type = INPUT_KEYBOARD
        arr[i].ki.wVk = vk
        arr[i].ki.dwFlags = flags
    user32.SendInput(4, arr, sizeof(INPUT))


def _wait_paste_consumed(timeout: float = 0.25) -> None:
    deadline = time.monotonic() + timeout
    saw_open = False
    while time.monotonic() < deadline:
        hwnd = user32.GetOpenClipboardWindow()
        if hwnd:
            saw_open = True
        elif saw_open:
            return
        time.sleep(0.01)


def paste_text(text: str) -> None:
    """Insert text via Unicode SendInput first; clipboard paste only as fallback.

    Raises on hard failure (including UIPI-elevated targets where injection is a
    silent no-op) so the app can surface Recent Transcripts recovery.
    """
    if _uipi_blocks_paste():
        raise PermissionError(
            "focused window is elevated; SendInput blocked by UIPI — use Recent Transcripts"
        )
    try:
        sent = _send_unicode(text)
        if sent:
            LOG.info("pasted via Unicode SendInput (%s events)", sent)
            return
        LOG.warning("Unicode SendInput returned 0; falling back to clipboard")
    except PermissionError:
        raise
    except Exception:
        LOG.exception("Unicode SendInput failed; falling back to clipboard")

    snapshot = _snapshot()
    try:
        _set_text(text)
        hwnd = _focused_hwnd()
        if _wm_paste(hwnd):
            LOG.info("pasted via WM_PASTE hwnd=%s", hwnd)
            return
        LOG.warning("WM_PASTE failed or timed out; trying Ctrl+V")
        _send_ctrl_v()
        _wait_paste_consumed()
    except Exception:
        LOG.exception("clipboard paste failed")
        raise
    finally:
        try:
            _restore(snapshot)
        except Exception:
            LOG.exception("clipboard restore failed")


def copy_to_clipboard(text: str) -> bool:
    """Set text directly onto the Windows clipboard, replacing current clipboard content."""
    try:
        _set_text(text)
        LOG.info("copied %s chars to clipboard", len(text))
        return True
    except Exception:
        LOG.exception("failed to copy text to clipboard")
        return False
