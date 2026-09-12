from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from dictation.paths import log_path

LOG = logging.getLogger("dictation")


def setup_logging() -> None:
    if LOG.handlers:
        return
    LOG.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = RotatingFileHandler(
        log_path(), maxBytes=2_000_000, backupCount=2, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    LOG.addHandler(file_handler)
    LOG.addHandler(stream)
