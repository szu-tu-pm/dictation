from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any

from dictation.paths import vocabulary_path

PROMPT_CHAR_LIMIT = 400


@dataclass
class Replacement:
    heard: str
    meant: str


@dataclass
class Vocabulary:
    words: list[str] = field(default_factory=list)
    replacements: list[Replacement] = field(default_factory=list)

    def prompt(self, limit: int = PROMPT_CHAR_LIMIT) -> str:
        """Comma-separated names for Whisper initial_prompt biasing."""
        names: list[str] = []
        seen: set[str] = set()
        for w in [*self.words, *(r.meant for r in self.replacements)]:
            w = w.strip()
            if not w:
                continue
            key = w.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(w)
        if not names:
            return ""
        out = ", ".join(names)
        if len(out) <= limit:
            return out
        return out[:limit].rsplit(",", 1)[0].strip()


def _parse_replacements(raw: Any) -> list[Replacement]:
    out: list[Replacement] = []
    if isinstance(raw, dict):
        items = raw.items()
        for heard, meant in items:
            h, m = str(heard).strip(), str(meant).strip()
            if h and m:
                out.append(Replacement(heard=h, meant=m))
        return out
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        h = str(item.get("heard", "")).strip()
        m = str(item.get("meant", "")).strip()
        if h and m:
            out.append(Replacement(heard=h, meant=m))
    return out


def load_vocabulary() -> Vocabulary:
    path = vocabulary_path()
    if not path.exists():
        vocab = Vocabulary()
        save_vocabulary(vocab)
        return vocab
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Vocabulary()
    if not isinstance(raw, dict):
        return Vocabulary()
    words_raw = raw.get("words", [])
    words = [str(w).strip() for w in words_raw] if isinstance(words_raw, list) else []
    words = [w for w in words if w]
    return Vocabulary(words=words, replacements=_parse_replacements(raw.get("replacements")))


def save_vocabulary(vocab: Vocabulary) -> None:
    path = vocabulary_path()
    payload = {
        "words": vocab.words,
        "replacements": [{"heard": r.heard, "meant": r.meant} for r in vocab.replacements],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _boundary_pattern(term: str) -> str:
    """Whole-token match that still works for C++, C#, Node.js, etc."""
    escaped = re.escape(term)
    if not term:
        return escaped
    prefix = r"(?<!\w)" if term[0].isalnum() or term[0] == "_" else ""
    suffix = r"(?!\w)" if term[-1].isalnum() or term[-1] == "_" else ""
    return rf"(?i){prefix}{escaped}{suffix}"


def apply_replacements(text: str, vocab: Vocabulary) -> str:
    out = text
    for r in vocab.replacements:
        if not r.heard or not r.meant:
            continue
        pattern = _boundary_pattern(r.heard)
        out = re.sub(pattern, lambda _m, meant=r.meant: meant, out)
    return out
