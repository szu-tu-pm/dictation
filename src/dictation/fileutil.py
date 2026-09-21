from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from dictation.logutil import LOG


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text via a sibling .tmp file, then replace the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding=encoding)
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def quarantine_corrupt(path: Path) -> Path:
    """Rename a bad file to a timestamped ``*.bak`` so repeats keep history."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak = path.with_name(f"{path.name}.{stamp}.bak")
    n = 0
    while bak.exists():
        n += 1
        bak = path.with_name(f"{path.name}.{stamp}.{n}.bak")
    path.replace(bak)
    return bak


def try_quarantine(path: Path, label: str) -> Path | None:
    """Quarantine ``path`` if present; log outcome. Returns bak path or None."""
    if not path.exists():
        return None
    try:
        bak = quarantine_corrupt(path)
        LOG.warning("moved corrupt %s to %s", label, bak)
        return bak
    except OSError:
        LOG.exception("failed to quarantine corrupt %s %s", label, path)
        return None
