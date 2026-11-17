"""Word tokenization shared by FTS query building and the fake embedder."""

import re

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
