import sys


def pytest_ignore_collect(collection_path, config):
    if sys.platform != "win32" and collection_path.name in {
        "test_hotkey.py",
        "test_paste.py",
        "test_hardware.py",
    }:
        return True