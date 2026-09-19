from dictation.icons import tray_icon


def test_tray_icon_states() -> None:
    for state in ("idle", "recording", "transcribing", "downloading", "loading", "error"):
        img = tray_icon(state)
        assert img.size == (64, 64)
        assert img.mode == "RGBA"


def test_recording_icon_reacts_to_level() -> None:
    quiet = tray_icon("recording", level=0.0)
    loud = tray_icon("recording", level=1.0)
    assert quiet.tobytes() != loud.tobytes()
