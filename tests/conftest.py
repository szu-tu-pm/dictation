import sys
from types import SimpleNamespace
from unittest.mock import MagicMock


class _MenuItem:
    def __init__(
        self,
        text,
        action=None,
        checked=None,
        enabled=True,
        default=False,
        radio=False,
    ):
        # Keep callables as-is (pystray evaluates them later with the item).
        self.text = text
        self._action = action
        self.checked = checked
        self.enabled = enabled
        self.default = default
        self.radio = radio


class _Menu:
    SEPARATOR = object()

    def __init__(self, *items):
        if len(items) == 1 and callable(items[0]):
            self.items = items[0]
        else:
            self.items = items


def pytest_ignore_collect(collection_path, config):
    if sys.platform != "win32" and collection_path.name in {
        "test_hotkey.py",
        "test_paste.py",
        "test_hardware.py",
    }:
        return True


# Lightweight pystray stub so tray MenuItem keeps text/action/enabled in CI.
if "pystray" not in sys.modules:
    sys.modules["pystray"] = SimpleNamespace(  # type: ignore[assignment]
        MenuItem=_MenuItem,
        Menu=_Menu,
        Icon=MagicMock,
    )

# sounddevice imports PortAudio at import time; unit tests only need RingBuffer/rms.
try:
    import sounddevice  # noqa: F401
except OSError:
    sys.modules.setdefault("sounddevice", MagicMock())
