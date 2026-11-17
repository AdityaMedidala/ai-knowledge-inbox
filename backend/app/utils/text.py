"""Text helpers: word tokens (FTS, fake embedder), previews, note titles and hashing."""

import hashlib
import re
import unicodedata

_WORD = re.compile(r"\w+")

STOP_WORDS = frozenset(
    """
    a about an and any are as at be been but by can could did do does for from had has have
    how i if in into is it its me my no not of on or our s should so t than that the their them
    then there these they this to was we were what when where which who whom why will with would
    you your
    """.split()  # noqa: SIM905 — a word block is easier to read and edit than a long list
)


def word_tokens(text: str) -> list[str]:
    """Lowercased unicode word tokens, in order, duplicates kept."""
    return _WORD.findall(text.lower())


PREVIEW_CHARS = 160
DERIVED_TITLE_CHARS = 60
ELLIPSIS = "…"


def clip_at_word(text: str, max_chars: int) -> str:
    """Collapse whitespace; if longer than max_chars, cut at the last word boundary + ellipsis."""
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    cut = flat[: max_chars - len(ELLIPSIS) + 1]
    head = cut.rsplit(" ", 1)[0] if " " in cut else cut[: max_chars - len(ELLIPSIS)]
    return head.rstrip(" ,;:.-") + ELLIPSIS


def preview_of(text: str | None) -> str | None:
    return clip_at_word(text, PREVIEW_CHARS) if text and text.strip() else None


def derive_title(text: str) -> str | None:
    """Title for an untitled note: its first non-empty line, markdown heading marks removed."""
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return clip_at_word(stripped, DERIVED_TITLE_CHARS)
    return None


def normalize_note(text: str) -> str:
    """Canonical note text for duplicate detection: NFC, whitespace runs collapsed."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
