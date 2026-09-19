from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from dictation.paths import history_path

HISTORY_LIMIT = 200


def load_history() -> list[dict[str, str]]:
    path = history_path()
    if not path.exists():
        return []
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
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
    cleaned = text.strip()
    if not cleaned:
        return
    items = load_history()
    items.insert(0, {"date": datetime.now().isoformat(timespec="seconds"), "text": cleaned})
    if len(items) > limit:
        items = items[:limit]
    path = history_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
