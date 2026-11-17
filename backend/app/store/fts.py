"""Turn free text into a safe FTS5 MATCH expression.

Raw user text in MATCH is a syntax error waiting to happen (quotes, `&`, `-`, `*`, `NEAR`, ...).
We keep only word tokens, quote each one (so FTS5 treats it as a literal term) and OR them.
"""

import re

MAX_FTS_TOKENS = 32
_WORD = re.compile(r"\w+")

STOP_WORDS = frozenset(
    [
        "a",
        "about",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "s",
        "should",
        "so",
        "t",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)


def build_fts_query(text: str) -> str | None:
    """Return a MATCH expression, or None when no searchable terms remain."""
    terms: list[str] = []
    seen: set[str] = set()
    for token in _WORD.findall(text.lower()):
        if token in STOP_WORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) == MAX_FTS_TOKENS:
            break
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms)
