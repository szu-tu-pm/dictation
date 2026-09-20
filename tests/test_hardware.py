import sys

import pytest

pytestmark = [
    pytest.mark.hardware,
    pytest.mark.skipif(sys.platform != "win32", reason="Windows only"),
]


def test_wasapi_device_exists() -> None:
    from dictation.audio import find_wasapi_input

    device = find_wasapi_input(None)
    assert isinstance(device, int)
    assert device >= 0


def test_right_ctrl_hook_installs() -> None:
    from dictation.hotkey import RightCtrlHook

    hook = RightCtrlHook(lambda _ev: None)
    hook.start()
    try:
        assert hook._hook
    finally:
        hook.stop()


def test_clipboard_restore() -> None:
    from dictation.paste import _restore, _set_text, _snapshot

    marker = "dictation-clipboard-test-7c2e"
    snap = _snapshot()
    try:
        _set_text(marker)
    finally:
        _restore(snap)


def test_whisper_dll_params_overlay() -> None:
    import os
    from ctypes import WinDLL, c_char_p, c_int, c_void_p

    from dictation.assets import engine_ready
    from dictation.paths import engine_dir
    from dictation.transcribe import WHISPER_SAMPLING_GREEDY, WhisperFullParamsPrefix, _as_addr

    root = engine_dir()
    if not engine_ready(root):
        pytest.skip("whisper engine not downloaded yet")
    os.add_dll_directory(str(root))
    dll = WinDLL(str(root / "whisper.dll"))
    dll.whisper_full_default_params_by_ref.argtypes = [c_int]
    dll.whisper_full_default_params_by_ref.restype = c_void_p
    dll.whisper_free_params.argtypes = [c_void_p]
    dll.whisper_print_system_info.restype = c_char_p
    ptr = dll.whisper_full_default_params_by_ref(WHISPER_SAMPLING_GREEDY)
    try:
        params = WhisperFullParamsPrefix.from_address(_as_addr(ptr))
        assert 1 <= params.n_threads <= 512
        assert params.strategy in (0, 1)
    finally:
        dll.whisper_free_params(ptr)
