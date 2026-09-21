import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

if sys.platform == "win32":
    import dictation.paste as paste_mod
    from dictation.paste import copy_to_clipboard, paste_text


def test_send_unicode_empty() -> None:
    assert paste_mod._send_unicode("") == 0


def test_send_unicode_surrogate_and_newlines() -> None:
    # Test normalization and event generation by intercepting SendInput
    with patch.object(paste_mod.user32, "SendInput", side_effect=lambda n, arr, size: n) as mock_send:
        # String with newline and emoji (code > 0xFFFF)
        text = "Hello\nWorld\U0001F600"
        count = paste_mod._send_unicode(text)
        # 'Hello' (5) + '\r' (1) + 'World' (5) + emoji (2 utf-16 surrogate chars) = 13 chars * 2 = 26 events
        assert count == 26
        assert mock_send.called
        n, arr, size = mock_send.call_args[0]
        assert n == 26


def test_send_unicode_chunks_long_text() -> None:
    with (
        patch.object(paste_mod.user32, "SendInput", side_effect=lambda n, arr, size: n) as mock_send,
        patch("dictation.paste.time.sleep") as mock_sleep,
    ):
        count = paste_mod._send_unicode("a" * 25)
        assert count == 50
        assert mock_send.call_count == 2
        assert mock_sleep.call_count == 1


def test_send_unicode_keeps_surrogate_pair_in_one_chunk() -> None:
    # 19 BMP chars + one emoji => 21 UTF-16 units; chunk size is 20, so the
    # naive split would orphan the high surrogate at index 19.
    text = ("x" * 19) + "\U0001F600"
    with (
        patch.object(paste_mod.user32, "SendInput", side_effect=lambda n, arr, size: n) as mock_send,
        patch("dictation.paste.time.sleep"),
    ):
        count = paste_mod._send_unicode(text)
        assert count == 42  # 21 units * 2 events
        assert mock_send.call_count == 2
        first_n = mock_send.call_args_list[0][0][0]
        second_n = mock_send.call_args_list[1][0][0]
        # First chunk ends before the high surrogate (19 units -> 38 events).
        assert first_n == 38
        assert second_n == 4  # high+low surrogate, down+up each


def test_paste_text_send_unicode_primary_path() -> None:
    with (
        patch("dictation.paste._send_unicode", return_value=10) as mock_unicode,
        patch("dictation.paste._snapshot") as mock_snap,
        patch("dictation.paste._set_text") as mock_set,
        patch("dictation.paste._restore") as mock_restore,
    ):
        paste_text("test sentence")
        assert mock_unicode.called
        # Happy path must NOT touch clipboard
        assert not mock_snap.called
        assert not mock_set.called
        assert not mock_restore.called


def test_paste_text_fallback_to_wm_paste() -> None:
    with (
        patch("dictation.paste._send_unicode", return_value=0),
        patch("dictation.paste._snapshot", return_value={13: b"abc"}) as mock_snap,
        patch("dictation.paste._set_text") as mock_set,
        patch("dictation.paste._focused_hwnd", return_value=1234),
        patch("dictation.paste._wm_paste", return_value=True) as mock_wm,
        patch("dictation.paste._send_ctrl_v") as mock_ctrl_v,
        patch("dictation.paste._restore") as mock_restore,
    ):
        paste_text("test sentence")
        assert mock_snap.called
        assert mock_set.called
        assert mock_wm.called
        assert not mock_ctrl_v.called
        mock_restore.assert_called_once_with({13: b"abc"})


def test_paste_text_fallback_to_ctrl_v() -> None:
    with (
        patch("dictation.paste._send_unicode", return_value=0),
        patch("dictation.paste._snapshot", return_value={13: b"abc"}),
        patch("dictation.paste._set_text"),
        patch("dictation.paste._focused_hwnd", return_value=1234),
        patch("dictation.paste._wm_paste", return_value=False),
        patch("dictation.paste._send_ctrl_v") as mock_ctrl_v,
        patch("dictation.paste._wait_paste_consumed") as mock_wait,
        patch("dictation.paste._restore") as mock_restore,
    ):
        paste_text("test sentence")
        assert mock_ctrl_v.called
        assert mock_wait.called
        mock_restore.assert_called_once_with({13: b"abc"})


def test_copy_to_clipboard_success() -> None:
    with patch("dictation.paste._set_text") as mock_set:
        assert copy_to_clipboard("test copy") is True
        mock_set.assert_called_once_with("test copy")


def test_copy_to_clipboard_failure() -> None:
    with patch("dictation.paste._set_text", side_effect=RuntimeError("Clipboard locked")):
        assert copy_to_clipboard("test copy") is False

def test_paste_text_raises_when_uipi_blocks() -> None:
    with (
        patch("dictation.paste._uipi_blocks_paste", return_value=True),
        patch("dictation.paste._send_unicode") as mock_unicode,
        pytest.raises(PermissionError, match="elevated"),
    ):
        paste_text("hello")
    assert not mock_unicode.called


def test_send_ctrl_v_releases_modifiers_first() -> None:
    calls: list[int] = []

    def _capture(n, arr, size):  # noqa: ANN001
        calls.append(int(n))
        return n

    with patch.object(paste_mod.user32, "SendInput", side_effect=_capture):
        paste_mod._send_ctrl_v()

    # First SendInput: 8 modifier key-ups; second: Ctrl+V chord (4 events).
    assert calls == [8, 4]
