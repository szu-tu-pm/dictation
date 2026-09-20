from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from dictation.fileutil import atomic_write_text, quarantine_corrupt
from dictation.logutil import LOG
from dictation.paths import history_path

HISTORY_LIMIT = 200


def load_history() -> list[dict[str, str]]:
    path = history_path()
    if not path.exists():
        return []
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        LOG.warning("history invalid JSON (%s); quarantining", exc)
        try:
            bak = quarantine_corrupt(path)
            LOG.warning("moved corrupt history to %s", bak)
        except OSError:
            LOG.exception("failed to quarantine corrupt history %s", path)
        return []
    except OSError as exc:
        LOG.warning("history read error (%s)", exc)
        return []
    if not isinstance(raw, list):
        LOG.warning("history JSON root is not a list; quarantining")
        try:
            bak = quarantine_corrupt(path)
            LOG.warning("moved corrupt history to %s", bak)
        except OSError:
            LOG.exception("failed to quarantine corrupt history %s", path)
        return []
    out: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        date = str(item.get("date", "")).strip() or datetime.now().isoformat(timespec="seconds")
        out.append({"date": date, "text": text})
    return out


def record_dictation(text: str, *, limit: int = HISTORY_LIMIT) -> None:
    """Append a transcript to history.json. Failures must not fail paste."""
    cleaned = text.strip()
    if not cleaned:
        return
    items = load_history()
    items.insert(0, {"date": datetime.now().isoformat(timespec="seconds"), "text": cleaned})
    if len(items) > limit:
        items = items[:limit]
    path = history_path()
    try:
        atomic_write_text(path, json.dumps(items, indent=2) + "\n")
    except OSError:
        LOG.exception("failed to write dictation history")
