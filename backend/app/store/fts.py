"""Turn free text into a safe FTS5 MATCH expression.

Raw user text in MATCH is a syntax error waiting to happen (quotes, `&`, `-`, `*`, `NEAR`, ...).
We keep only word tokens, quote each one (so FTS5 treats it as a literal term) and OR them.
"""

from app.utils.text import STOP_WORDS, word_tokens

MAX_FTS_TOKENS = 32


def build_fts_query(text: str) -> str | None:
    """Return a MATCH expression, or None when no searchable terms remain."""
    terms: list[str] = []
    seen: set[str] = set()
    for token in word_tokens(text):
        if token in STOP_WORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
        if len(terms) == MAX_FTS_TOKENS:
            break
    if not terms:
        return None
    return " OR ".join(f'"{term}"' for term in terms)
