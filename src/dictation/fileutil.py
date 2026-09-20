from __future__ import annotations

from pathlib import Path


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
    """Rename a bad file to ``*.bak`` (replacing any prior backup). Returns bak path."""
    bak = path.with_name(path.name + ".bak")
    try:
        bak.unlink(missing_ok=True)
    except OSError:
        pass
    path.replace(bak)
    return bak
