from dictation.icons import tray_icon


def test_tray_icon_states() -> None:
    for state in ("idle", "recording", "transcribing", "downloading", "loading", "error"):
        img = tray_icon(state)
        assert img.size == (64, 64)
        assert img.mode == "RGBA"
