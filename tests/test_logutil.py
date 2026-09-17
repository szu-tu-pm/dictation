import logging
from pathlib import Path

from dictation.logutil import LOG, setup_logging


def test_setup_logging_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    # Clear existing handlers for clean test
    LOG.handlers.clear()

    setup_logging()
    assert len(LOG.handlers) >= 2
    assert LOG.level == logging.INFO

    # Call again, should not add duplicate handlers
    setup_logging()
    assert len(LOG.handlers) >= 2
