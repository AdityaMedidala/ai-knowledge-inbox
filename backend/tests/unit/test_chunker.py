import random
from itertools import pairwise

import pytest

from app.config import Settings
from app.domain.models import NewChunk
from app.services.chunker import (
    CONTEXT_HEADER_MAX_TOKENS,
    EMBEDDER_MAX_TOKENS,
    EMBEDDER_TOKENS_PER_TIKTOKEN,
    MIN_CHUNK_TOKENS,
    SENTENCE_END,
    ChunkLimits,
    build_context_header,
    build_embed_text,
    chunk_document,
)
from app.services.markdown_blocks import BlockKind, parse_sections
from app.utils.tokens import count_tokens
from tests.support.chunk_invariants import assert_chunk_invariants

LIMITS = ChunkLimits(max_tokens=120, overlap_tokens=30, max_block_tokens=160)
WORDS = (
    "sqlite", "wal", "checkpoint", "reader", "writer", "page", "journal", "index", "commit",
    "lock", "frame", "snapshot", "database", "connection", "pragma", "timeout", "table",
    "vector", "search", "query", "token", "chunk",
)  # fmt: skip


def sentences(rng: random.Random, count: int, words: int = 12) -> str:
    return " ".join(
        " ".join(rng.choice(WORDS) for _ in range(words)).capitalize() + "." for _ in range(count)
    )


def table(rows: int, tag: str = "") -> str:
    lines = ["| Key | Value | Notes |", "|---|---|---|"]
    lines += [f"| key{i}{tag} | value {i} | note about row {i} |" for i in range(rows)]
    return "\n".join(lines)


def code(lines: int, tag: str = "") -> str:
    body = [f"result_{i}{tag} = compute(step={i}, retries=3, verbose=True)" for i in range(lines)]
    return "\n".join(["```python", *body, "```"])


def chunk(text: str, limits: ChunkLimits = LIMITS, title: str | None = "Doc") -> list[NewChunk]:
    chunks = chunk_document(text, title=title, limits=limits)
    assert_chunk_invariants(chunks, text, limits)
    return chunks


# --- markdown parsing -----------------------------------------------------------------------


def test_heading_paths_and_code_comments_are_not_headings() -> None:
    markdown = "# A\nintro\n## B\n```\n# not a heading\n```\n### C\ntext\n## D\nmore\n#### deep\nx"
    sections = parse_sections(markdown)
    assert [s.path for s in sections] == ["A", "A > B", "A > B > C", "A > D"]
    assert sections[1].blocks[0].kind is BlockKind.CODE
    assert "#### deep" in sections[3].blocks[0].text  # h4+ stays body text


def test_unclosed_fence_runs_to_end() -> None:
    sections = parse_sections("text\n\n```\ncode\n## still code")
    assert [b.kind for b in sections[0].blocks] == [BlockKind.TEXT, BlockKind.CODE]


# --- basic behaviour ------------------------------------------------------------------------


def test_empty_document_has_no_chunks() -> None:
    assert chunk_document("  \n ", title="t", limits=LIMITS) == []


def test_short_note_is_exactly_one_chunk() -> None:
    note = "Buy milk.\n\nCall the dentist about Tuesday."
    [only] = chunk(note, title=None)
    assert (only.ordinal, only.section, only.text) == (0, None, note)
    assert only.context_header == ""


def test_short_document_with_headings_is_one_chunk() -> None:
    markdown = "# Title\n\nA line.\n\n## Part\n\nAnother line."
    [only] = chunk(markdown)
    assert only.text == markdown
    assert only.section == "Title"


def test_context_header_is_kept_out_of_chunk_text() -> None:
    rng = random.Random(1)
    markdown = f"# Guide\n\n{sentences(rng, 12)}\n\n## Install\n\n{sentences(rng, 12)}"
    chunks = chunk(markdown, title="My Guide")
    assert chunks[-1].context_header == "Title: My Guide\nSection: Guide > Install"
    assert all("Title:" not in c.text for c in chunks)
    assert build_embed_text(chunks[-1]).startswith("Title: My Guide\nSection: Guide > Install\n\n")


def test_overlap_repeats_trailing_sentences_within_a_section() -> None:
    rng = random.Random(2)
    chunks = chunk(f"## Only\n\n{sentences(rng, 30)}")
    assert len(chunks) >= 3
    for previous, current in pairwise(chunks):
        first_sentence = SENTENCE_END.split(current.text)[0]
        tail = previous.text[-len(first_sentence) - 200 :]
        assert first_sentence in tail, "new chunk should open with the previous chunk's tail"


def test_no_overlap_across_sections() -> None:
    rng = random.Random(3)
    first, second = sentences(rng, 12), sentences(rng, 12)
    chunks = chunk(f"## One\n\n{first}\n\n## Two\n\n{second}")
    two = [c for c in chunks if c.section == "Two"]
    assert two[0].text.startswith(second[:40])


# --- protected blocks -----------------------------------------------------------------------


def test_table_larger_than_chunk_but_within_block_cap_stays_whole() -> None:
    rng = random.Random(4)
    big_table = table(10)
    assert LIMITS.max_tokens < count_tokens(big_table) <= LIMITS.max_block_tokens
    chunks = chunk(f"## Data\n\n{sentences(rng, 6)}\n\n{big_table}\n\n{sentences(rng, 6)}")
    assert big_table in [c.text for c in chunks]


def test_oversized_table_is_split_by_row_repeating_the_header() -> None:
    huge = table(40)
    chunks = chunk(f"## Data\n\n{huge}")
    assert len(chunks) > 1
    for part in chunks:
        assert part.text.startswith("| Key | Value | Notes |\n|---|---|---|\n| key")
        assert part.token_count <= LIMITS.max_block_tokens


def test_code_block_stays_whole_and_oversized_code_is_split_by_line() -> None:
    small, huge = code(6), code(40)
    assert count_tokens(small) <= LIMITS.max_block_tokens < count_tokens(huge)
    rng = random.Random(5)
    whole = chunk(f"## A\n\n{sentences(rng, 8)}\n\n{small}\n\n{sentences(rng, 8)}")
    assert small in [c.text for c in whole]

    parts = chunk(f"## B\n\n{huge}")
    assert len(parts) > 1
    for part in parts:
        assert part.text.startswith("```python\n") and part.text.endswith("\n```")


def test_run_on_text_without_punctuation_is_hard_split() -> None:
    run_on = " ".join(WORDS * 40)
    chunks = chunk(f"## Wall\n\n{run_on}")
    assert len(chunks) > 1
    assert all(c.token_count <= LIMITS.max_tokens for c in chunks)


# --- tiny-fragment merging ------------------------------------------------------------------


def test_tiny_section_merges_into_previous_chunk_with_heading_inlined() -> None:
    rng = random.Random(6)
    big, big2 = sentences(rng, 6), sentences(rng, 8)
    markdown = f"## Big\n\n{big}\n\n## Tiny\n\nJust a line.\n\n## Big2\n\n{big2}"
    chunks = chunk(markdown)
    merged = next(c for c in chunks if "Just a line." in c.text)
    assert merged.section == "Big"
    assert "## Tiny\n\nJust a line." in merged.text


def test_tiny_leading_fragment_merges_forward() -> None:
    rng = random.Random(7)
    chunks = chunk(f"Intro line.\n\n## Body\n\n{sentences(rng, 12)}")
    assert chunks[0].text.startswith("Intro line.\n\n")
    assert chunks[0].section == "Body"


def test_merge_never_duplicates_overlap_text() -> None:
    rng = random.Random(8)
    chunks = chunk(f"## S\n\n{sentences(rng, 11)}")
    joined = " ".join(c.text for c in chunks)
    assert all(c.token_count >= MIN_CHUNK_TOKENS or len(chunks) == 1 for c in chunks[:-1])
    assert joined.count(chunks[0].text[:60]) == 1


# --- embedder budget (bge truncates at 512 of its own tokens) -------------------------------


def test_max_size_chunks_fit_the_embedder_with_header() -> None:
    defaults = Settings.model_fields
    block_cap = defaults["chunk_max_block_tokens"].default
    chunk_cap = defaults["chunk_tokens"].default
    header = build_context_header("T" * 200 + " title words " * 20, " > ".join(["Section"] * 30))
    assert count_tokens(header) <= CONTEXT_HEADER_MAX_TOKENS

    for size in (block_cap, chunk_cap):
        text = " ".join(["token"] * size)
        assert count_tokens(text) == size
        embedded = build_embed_text(
            NewChunk(ordinal=0, section="s", context_header=header, text=text, token_count=size)
        )
        assert count_tokens(embedded) * EMBEDDER_TOKENS_PER_TIKTOKEN <= EMBEDDER_MAX_TOKENS


# --- property-style: random documents must always satisfy the invariants --------------------


def random_document(rng: random.Random) -> str:
    parts: list[str] = []
    for _ in range(rng.randint(1, 12)):
        roll = rng.random()
        if roll < 0.2:
            parts.append(
                f"{'#' * rng.randint(1, 3)} {rng.choice(WORDS).title()} {rng.randint(1, 99)}"
            )
        elif roll < 0.3:
            parts.append(table(rng.randint(1, 45), tag=f"t{len(parts)}"))
        elif roll < 0.4:
            parts.append(code(rng.randint(1, 45), tag=f"c{len(parts)}"))
        else:
            parts.append(sentences(rng, rng.randint(1, 25), words=rng.randint(3, 30)))
    return "\n\n".join(parts)


# 1561/1789/1805 once caught overlap leaking into the next section via a forward tiny-merge.
@pytest.mark.parametrize("seed", [*range(40), 1561, 1789, 1805])
def test_random_documents_satisfy_invariants(seed: int) -> None:
    rng = random.Random(seed)
    limits = ChunkLimits(
        max_tokens=rng.choice([80, 120, 350]),
        overlap_tokens=rng.choice([0, 20, 40]),
        max_block_tokens=rng.choice([350, 400]),
    )
    limits = ChunkLimits(
        limits.max_tokens, limits.overlap_tokens, max(limits.max_block_tokens, limits.max_tokens)
    )
    chunk(random_document(rng), limits)
