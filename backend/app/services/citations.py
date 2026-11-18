"""Turn [n] markers in an answer into citations; never invent one the model didn't make."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from app.domain.models import RetrievedChunk
from app.utils.text import clip_at_word

logger = structlog.get_logger(__name__)

SNIPPET_MAX_CHARS = 320
# [1], [1, 2] and [1][2] (the latter as two matches). Some models (gpt-oss) emit fullwidth
# lenticular brackets 【1】 despite the prompt, sometimes with a locator suffix after the
# number (【2†section 6】, 【4:0†source】, [3†L10-L20]); those count as a citation of the number.
MARKER = re.compile(r"[\[【](\d+(?:\s*,\s*\d+)*)(?:[†‡:][^\]】\n]{0,80})?[\]】]")
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


@dataclass(frozen=True, slots=True)
class Citation:
    ref: int
    source: RetrievedChunk
    snippet: str


def parse_refs(answer: str) -> list[int]:
    """Every referenced number in order of first appearance, duplicates removed."""
    refs = (int(n) for match in MARKER.finditer(answer) for n in match.group(1).split(","))
    return list(dict.fromkeys(refs))


def build_citations(answer: str, sources: Sequence[RetrievedChunk]) -> list[Citation]:
    """Resolve refs against the numbered sources (ref n = sources[n-1]); drop unknown refs."""
    citations: list[Citation] = []
    for ref in parse_refs(answer):
        if not 1 <= ref <= len(sources):
            logger.warning("query.invalid_citation", ref=ref, n_sources=len(sources))
            continue
        source = sources[ref - 1]
        citations.append(Citation(ref=ref, source=source, snippet=make_snippet(source.chunk.text)))
    if not citations and answer.strip():
        logger.warning("query.uncited_answer", n_sources=len(sources))
    return citations


def make_snippet(text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """Whitespace-collapsed text, cut at the last sentence end that fits (else a word end)."""
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    head = flat[: max_chars + 1]  # one extra char so the lookahead sees what follows
    ends = [m.end() for m in _SENTENCE_END.finditer(head) if m.end() <= max_chars]
    if ends:
        return flat[: ends[-1]]
    return clip_at_word(flat, max_chars)
