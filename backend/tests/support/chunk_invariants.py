"""Invariants every chunk_document() result must satisfy, shared by unit and integration tests."""

import re
from itertools import pairwise

from app.domain.models import NewChunk
from app.services.chunker import SENTENCE_END, ChunkLimits
from app.services.markdown_blocks import BlockKind, parse_sections
from app.utils.tokens import count_tokens

_WHITESPACE = re.compile(r"\s+")
PROTECTED = (BlockKind.TABLE, BlockKind.CODE)


def assert_chunk_invariants(chunks: list[NewChunk], source: str, limits: ChunkLimits) -> None:
    assert [c.ordinal for c in chunks] == list(range(len(chunks))), "ordinals not contiguous"
    for c in chunks:
        assert c.text.strip(), f"chunk {c.ordinal} is empty"
        assert c.token_count == count_tokens(c.text)
        if c.token_count > limits.max_tokens:
            assert _is_single_protected_block(c.text), f"chunk {c.ordinal} oversized prose"
            assert c.token_count <= limits.max_block_tokens, f"chunk {c.ordinal} over block cap"
    _assert_no_cross_section_overlap(chunks)
    _assert_nothing_dropped(chunks, source)


def _is_single_protected_block(text: str) -> bool:
    sections = parse_sections(text)
    return (
        len(sections) == 1
        and len(sections[0].blocks) == 1
        and sections[0].blocks[0].kind in PROTECTED
    )


def _assert_no_cross_section_overlap(chunks: list[NewChunk]) -> None:
    for previous, current in pairwise(chunks):
        if previous.section == current.section:
            continue
        tail = SENTENCE_END.split(previous.text)[-1]
        if len(tail) > 20:
            assert not current.text.startswith(tail), (
                f"chunk {current.ordinal} starts with overlap from another section"
            )


def _assert_nothing_dropped(chunks: list[NewChunk], source: str) -> None:
    """Every sentence / table row / code line of the source survives somewhere, in order-
    insensitive, whitespace-insensitive form (hard splits may break a sentence across chunks)."""
    everything = _squash("".join(c.text for c in chunks))
    for section in parse_sections(source):
        for block in section.blocks:
            if block.kind is BlockKind.TEXT:
                pieces = SENTENCE_END.split(block.text)
            else:
                pieces = block.text.splitlines()
            for piece in pieces:
                assert _squash(piece) in everything, f"dropped source text: {piece[:60]!r}"


def _squash(text: str) -> str:
    return _WHITESPACE.sub("", text)
