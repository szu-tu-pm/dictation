from __future__ import annotations

import math
import queue
import threading
import time
from dataclasses import dataclass

from PIL import Image, ImageDraw

from dictation.icons import COLORS
from dictation.logutil import LOG


# Visual modes the pill can show. None / hidden means the window is withdrawn.
HudMode = str  # "recording" | "transcribing" | "success" | "hidden"


@dataclass(frozen=True)
class HudFrame:
    mode: HudMode
    level: float = 0.0
    continuous: bool = False
    elapsed_s: float = 0.0


def map_app_state(
    state_value: str,
    *,
    level: float = 0.0,
    continuous: bool = False,
    elapsed_s: float = 0.0,
) -> HudFrame:
    """Map DictationApp state strings to a HUD frame."""
    if state_value == "recording":
        return HudFrame("recording", level=level, continuous=continuous)
    if state_value == "transcribing":
        return HudFrame("transcribing", elapsed_s=elapsed_s)
    # idle / starting / downloading / loading / error → hide
    return HudFrame("hidden")


def pill_size(frame: HudFrame) -> tuple[int, int]:
    if frame.mode == "hidden":
        return (0, 0)
    width = 168 if frame.continuous and frame.mode == "recording" else 148
    return (width, 36)


def work_area_position(work: tuple[int, int, int, int], size: tuple[int, int]) -> tuple[int, int]:
    """Bottom-center of the work area (above the taskbar), 12px margin."""
    left, top, right, bottom = work
    w, h = size
    if w <= 0 or h <= 0:
        return (left, top)
    x = left + (right - left - w) // 2
    y = bottom - h - 12
    return (x, y)


def render_pill(frame: HudFrame) -> Image.Image | None:
    """Render an RGBA capsule for UpdateLayeredWindow. None → hide."""
    if frame.mode == "hidden":
        return None
    w, h = pill_size(frame)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Semi-transparent dark capsule
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=(20, 24, 32, 200))

    cx, cy = 22, h // 2
    if frame.mode == "recording":
        color = COLORS["recording"]
        # Level-reactive glow ring
        t = max(0.0, min(1.0, float(frame.level)))
        r = 6 + int(t * 5)
        draw.ellipse((cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), fill=(*color[:3], 80))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        label = "REC  LOCK" if frame.continuous else "REC"
        draw.text((cx + r + 10, cy - 6), label, fill=(255, 255, 255, 230))
    elif frame.mode == "transcribing":
        color = COLORS["transcribing"]
        # Soft pulse via elapsed phase
        phase = 0.55 + 0.45 * abs(math.sin(frame.elapsed_s * 6.0))
        alpha = int(120 + 100 * phase)
        r = 7
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color[:3], alpha))
        draw.text((cx + r + 10, cy - 6), f"{frame.elapsed_s:.1f}s", fill=(255, 255, 255, 230))
    elif frame.mode == "success":
        color = (22, 163, 74, 255)  # green
        r = 8
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        # Simple checkmark
        draw.line((cx - 4, cy, cx - 1, cy + 3), fill=(255, 255, 255, 255), width=2)
        draw.line((cx - 1, cy + 3, cx + 5, cy - 3), fill=(255, 255, 255, 255), width=2)
        draw.text((cx + r + 10, cy - 6), "Done", fill=(255, 255, 255, 230))
    return img


def _bind_hud_win32():
    """Bind user32/gdi32/kernel32 with pointer-sized HANDLE/LPARAM types (Win64-safe)."""
    import ctypes
    from ctypes import POINTER, wintypes

    # windll caches DLLs; set argtypes once so later calls stay correct.
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

    LRESULT = ctypes.c_ssize_t
    HDC = wintypes.HDC
    HBITMAP = wintypes.HBITMAP
    HWND = wintypes.HWND
    HGDIOBJ = wintypes.HGDIOBJ
    COLORREF = wintypes.COLORREF

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD

    user32.DefWindowProcW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = HWND
    user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        HWND,
        HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.GetDC.argtypes = [HWND]
    user32.GetDC.restype = HDC
    user32.ReleaseDC.argtypes = [HWND, HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.UpdateLayeredWindow.argtypes = [
        HWND,
        HDC,
        ctypes.c_void_p,
        ctypes.c_void_p,
        HDC,
        ctypes.c_void_p,
        COLORREF,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        POINTER(wintypes.MSG),
        HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT

    gdi32.CreateCompatibleDC.argtypes = [HDC]
    gdi32.CreateCompatibleDC.restype = HDC
    gdi32.CreateDIBSection.argtypes = [
        HDC,
        ctypes.c_void_p,
        wintypes.UINT,
        POINTER(ctypes.c_void_p),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = HBITMAP
    gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
    gdi32.SelectObject.restype = HGDIOBJ
    gdi32.DeleteObject.argtypes = [HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL

    return user32, gdi32, kernel32


class HudOverlay:
    """Bottom-center layered pill. No-op when disabled or Win32 is unavailable."""

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled
        self._q: queue.Queue[HudFrame | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frame = HudFrame("hidden")
        self._transcribe_started = 0.0
        self._success_until = 0.0
        self._hwnd = None
        self._user32 = None
        self._gdi32 = None
        self._ctypes = None
        self._available = False

    def start(self) -> None:
        if not self.enabled:
            return
        try:
            import ctypes  # noqa: F401
            from ctypes import windll  # noqa: F401
        except Exception:
            LOG.info("HUD disabled: Win32 unavailable")
            return
        self._available = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="hud", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._q.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def update(
        self,
        state_value: str,
        *,
        level: float = 0.0,
        continuous: bool = False,
        elapsed_s: float = 0.0,
    ) -> None:
        if not self.enabled:
            return
        if state_value == "transcribing" and self._frame.mode != "transcribing":
            self._transcribe_started = time.monotonic()
        if state_value == "transcribing" and elapsed_s <= 0:
            elapsed_s = max(0.0, time.monotonic() - self._transcribe_started)
        frame = map_app_state(
            state_value,
            level=level,
            continuous=continuous,
            elapsed_s=elapsed_s,
        )
        # Keep the green success flash visible even if IDLE arrives immediately.
        if frame.mode == "hidden" and time.monotonic() < self._success_until:
            return
        self._frame = frame
        if self._available:
            try:
                self._q.put_nowait(frame)
            except queue.Full:
                pass

    def show_success(self, duration_s: float = 0.6) -> None:
        if not self.enabled:
            return
        self._success_until = time.monotonic() + duration_s
        frame = HudFrame("success")
        self._frame = frame
        if self._available:
            try:
                self._q.put_nowait(frame)
            except queue.Full:
                pass
            threading.Timer(duration_s, lambda: self.update("idle")).start()

    # --- Win32 implementation -------------------------------------------------

    def _loop(self) -> None:
        try:
            self._create_window()
        except Exception:
            LOG.exception("HUD window create failed")
            self._available = False
            return
        last_paint = 0.0
        while not self._stop.is_set():
            from_queue = False
            try:
                frame = self._q.get(timeout=0.05)
                from_queue = True
            except queue.Empty:
                frame = self._frame
            if frame is None:
                break
            if frame.mode == "transcribing":
                frame = HudFrame(
                    "transcribing",
                    elapsed_s=max(0.0, time.monotonic() - self._transcribe_started),
                )
                self._frame = frame
            # Idle Empty wakes: only repaint animated modes (transcribing pulse).
            # Queue updates always paint (subject to the recording throttle below).
            if not from_queue and frame.mode != "transcribing":
                self._pump_messages()
                continue
            now = time.monotonic()
            # Cap recording level floods at ~20 Hz.
            if (
                from_queue
                and frame.mode == "recording"
                and now - last_paint < 0.05
            ):
                self._pump_messages()
                continue
            try:
                self._paint(frame)
            except Exception:
                LOG.exception("HUD paint failed")
            last_paint = now
            self._pump_messages()
        try:
            self._destroy_window()
        except Exception:
            LOG.exception("HUD destroy failed")

    def _create_window(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32, gdi32, kernel32 = _bind_hud_win32()
        WS_POPUP = 0x80000000
        WS_EX_LAYERED = 0x00080000
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_TOPMOST = 0x00000008
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TRANSPARENT = 0x00000020
        HWND_TOPMOST = -1
        SWP_NOACTIVATE = 0x0010
        SW_HIDE = 0

        # LRESULT is pointer-sized; c_long truncates on Win64 and overflows LPARAM.
        LRESULT = ctypes.c_ssize_t
        WNDPROC = ctypes.WINFUNCTYPE(
            LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        def _wnd_proc(hwnd, msg, wparam, lparam):
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        # Keep a strong reference so the callback is not GC'd.
        self._wnd_proc = WNDPROC(_wnd_proc)
        hinst = kernel32.GetModuleHandleW(None)
        class_name = "DictationHudPill"
        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = self._wnd_proc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinst
        wc.hIcon = None
        wc.hCursor = None
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = class_name
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            # Already registered from a previous run in-process is fine.
            err = kernel32.GetLastError()
            if err not in (0, 1410):  # ERROR_CLASS_ALREADY_EXISTS
                raise OSError(f"RegisterClassW failed: {err}")

        ex = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        hwnd = user32.CreateWindowExW(
            ex,
            class_name,
            "Dictation HUD",
            WS_POPUP,
            0,
            0,
            10,
            10,
            None,
            None,
            hinst,
            None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed: {kernel32.GetLastError()}")
        self._hwnd = hwnd
        self._user32 = user32
        self._gdi32 = gdi32
        self._ctypes = ctypes
        user32.ShowWindow(hwnd, SW_HIDE)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOACTIVATE | 0x0001 | 0x0002)
        LOG.info("HUD overlay window created")

    def _work_area(self) -> tuple[int, int, int, int]:
        import ctypes
        from ctypes import wintypes

        SPI_GETWORKAREA = 0x0030

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rc = RECT()
        user32 = self._user32 or _bind_hud_win32()[0]
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rc), 0)
        return (rc.left, rc.top, rc.right, rc.bottom)

    def _paint(self, frame: HudFrame) -> None:
        if self._hwnd is None:
            return
        img = render_pill(frame)
        user32 = self._user32
        gdi32 = self._gdi32
        ctypes = self._ctypes
        if img is None:
            user32.ShowWindow(self._hwnd, 0)  # SW_HIDE
            return
        w, h = img.size
        x, y = work_area_position(self._work_area(), (w, h))
        # Convert RGBA → premultiplied BGRA for UpdateLayeredWindow
        rgba = img.tobytes("raw", "RGBA")
        bgra = bytearray(len(rgba))
        for i in range(0, len(rgba), 4):
            r, g, b, a = rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]
            bgra[i] = (b * a) // 255
            bgra[i + 1] = (g * a) // 255
            bgra[i + 2] = (r * a) // 255
            bgra[i + 3] = a

        hdc_screen = None
        hdc_mem = None
        hbmp = None
        old = None
        try:
            hdc_screen = user32.GetDC(None)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ("biSize", ctypes.c_uint32),
                    ("biWidth", ctypes.c_long),
                    ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16),
                    ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32),
                    ("biXPelsPerMeter", ctypes.c_long),
                    ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32),
                ]

            class BITMAPINFO(ctypes.Structure):
                _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = w
            bmi.bmiHeader.biHeight = -h  # top-down
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            bits = ctypes.c_void_p()
            hbmp = gdi32.CreateDIBSection(
                hdc_mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0
            )
            if not hbmp or not bits:
                return
            ctypes.memmove(bits, bytes(bgra), len(bgra))
            old = gdi32.SelectObject(hdc_mem, hbmp)

            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            class SIZE(ctypes.Structure):
                _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

            class BLENDFUNCTION(ctypes.Structure):
                _fields_ = [
                    ("BlendOp", ctypes.c_byte),
                    ("BlendFlags", ctypes.c_byte),
                    ("SourceConstantAlpha", ctypes.c_byte),
                    ("AlphaFormat", ctypes.c_byte),
                ]

            pt_dst = POINT(x, y)
            pt_src = POINT(0, 0)
            size = SIZE(w, h)
            blend = BLENDFUNCTION(0, 0, 255, 1)  # AC_SRC_OVER, AC_SRC_ALPHA
            ULW_ALPHA = 0x00000002
            user32.UpdateLayeredWindow(
                self._hwnd,
                hdc_screen,
                ctypes.byref(pt_dst),
                ctypes.byref(size),
                hdc_mem,
                ctypes.byref(pt_src),
                0,
                ctypes.byref(blend),
                ULW_ALPHA,
            )
            user32.ShowWindow(self._hwnd, 8)  # SW_SHOWNA — show without activate
        finally:
            if hdc_mem is not None and old is not None:
                gdi32.SelectObject(hdc_mem, old)
            if hbmp:
                gdi32.DeleteObject(hbmp)
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
            if hdc_screen:
                user32.ReleaseDC(None, hdc_screen)

    def _pump_messages(self) -> None:
        import ctypes
        from ctypes import wintypes

        msg = wintypes.MSG()
        user32 = self._user32 or _bind_hud_win32()[0]
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _destroy_window(self) -> None:
        if self._hwnd is None:
            return
        self._user32.DestroyWindow(self._hwnd)
        self._hwnd = None
