import sys
from unittest.mock import MagicMock


def pytest_ignore_collect(collection_path, config):
    if sys.platform != "win32" and collection_path.name in {
        "test_hotkey.py",
        "test_paste.py",
        "test_hardware.py",
    }:
        return True


# sounddevice imports PortAudio at import time; unit tests only need RingBuffer/rms.
try:
    import sounddevice  # noqa: F401
except OSError:
    sys.modules.setdefault("sounddevice", MagicMock())
