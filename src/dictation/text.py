from __future__ import annotations

import re

FILLER_RE = re.compile(r"\b(?:um+|uh+|er+|ah+|hmm+|mm+)\b[,\.]?", re.IGNORECASE)
SPACE_RE = re.compile(r"[ \t]{2,}")

GHOSTS = {
    "thanks for watching",
    "thank you for watching",
    "subtitle",
    "subtitles by",
    "subtitles by the amara org",
    "please subscribe",
}


def strip_fillers(text: str) -> str:
    cleaned = FILLER_RE.sub("", text)
    cleaned = SPACE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned.strip()


def is_ghost(text: str) -> bool:
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    normalized = SPACE_RE.sub(" ", normalized).strip()
    if not normalized:
        return True
    return normalized in GHOSTS
