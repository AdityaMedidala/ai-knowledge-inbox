"""Header-aware, token-sized chunking. Pure: markdown in, NewChunks out.

Ported from Nova's chunking.py (heading-based grouping, table-safe splitting). Unlike Nova it
sizes with tiktoken instead of characters, keeps fenced code whole too, overlaps consecutive
chunks only within a section, and merges tiny fragments into a neighbour.
"""

import re
from dataclasses import dataclass

from app.domain.models import NewChunk
from app.services.markdown_blocks import Block, BlockKind, Section, parse_sections
from app.utils.tokens import count_tokens, split_by_tokens, truncate_to_tokens

MIN_CHUNK_TOKENS = 50
CONTEXT_HEADER_MAX_TOKENS = 40
# The embedder (bge-small) truncates at 512 of ITS tokens; cl100k undercounts them ~1.15x on
# English prose. Chunk and block limits are chosen so header + text stays under the limit.
EMBEDDER_MAX_TOKENS = 512
EMBEDDER_TOKENS_PER_TIKTOKEN = 1.15
BLOCK_SEPARATOR = "\n\n"
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True, slots=True)
class ChunkLimits:
    max_tokens: int
    overlap_tokens: int
    max_block_tokens: int  # a table / code block up to this size is never split


@dataclass(frozen=True, slots=True)
class _Unit:
    """An indivisible piece of a section. `sep` re-joins it to the preceding unit faithfully."""

    text: str
    kind: BlockKind
    sep: str


@dataclass(frozen=True, slots=True)
class _Draft:
    section: Section
    text: str
    overlap_chars: int = 0  # length of the overlap prefix copied from the previous chunk


def build_context_header(title: str | None, section: str | None) -> str:
    lines = [f"Title: {title}"] if title else []
    if section:
        lines.append(f"Section: {section}")
    return truncate_to_tokens("\n".join(lines), CONTEXT_HEADER_MAX_TOKENS)


def build_embed_text(chunk: NewChunk) -> str:
    """What gets embedded (and FTS-indexed): the context header is a retrieval-only prefix."""
    if not chunk.context_header:
        return chunk.text
    return f"{chunk.context_header}{BLOCK_SEPARATOR}{chunk.text}"


def chunk_document(markdown: str, *, title: str | None, limits: ChunkLimits) -> list[NewChunk]:
    text = markdown.strip()
    sections = parse_sections(text)
    if not sections:
        return []
    if count_tokens(text) <= limits.max_tokens:
        drafts = [_Draft(sections[0], text)]  # short documents are exactly one chunk
    else:
        packed = [draft for section in sections for draft in _pack_section(section, limits)]
        drafts = _merge_tiny(packed, limits.max_tokens)
    return [
        NewChunk(
            ordinal=ordinal,
            section=draft.section.path,
            context_header=build_context_header(title, draft.section.path),
            text=draft.text,
            token_count=count_tokens(draft.text),
        )
        for ordinal, draft in enumerate(drafts)
    ]


# --- splitting blocks into units ------------------------------------------------------------


def _units(block: Block, limits: ChunkLimits) -> list[_Unit]:
    if block.kind is BlockKind.TEXT:
        return _text_units(block.text, limits.max_tokens)
    if count_tokens(block.text) <= limits.max_block_tokens:
        return [_Unit(block.text, block.kind, BLOCK_SEPARATOR)]
    if block.kind is BlockKind.TABLE:
        parts = _split_table(block.text, limits.max_block_tokens)
    else:
        parts = _split_code(block.text, limits.max_block_tokens)
    return [_Unit(part, block.kind, BLOCK_SEPARATOR) for part in parts]


def _text_units(text: str, max_tokens: int) -> list[_Unit]:
    if count_tokens(text) <= max_tokens:
        return [_Unit(text, BlockKind.TEXT, BLOCK_SEPARATOR)]
    units: list[_Unit] = []
    for sentence in SENTENCE_END.split(text):
        pieces = split_by_tokens(sentence, max_tokens)
        for index, piece in enumerate(pieces):
            sep = ("" if index else " ") if units else BLOCK_SEPARATOR
            units.append(_Unit(piece, BlockKind.TEXT, sep))
    return units


def _split_table(table: str, max_tokens: int) -> list[str]:
    """Split by row; every part repeats the header row (and its |---| separator line)."""
    rows = table.splitlines()
    has_header = len(rows) > 1 and set(rows[1].replace("|", "").strip()) <= set("-: ")
    header = rows[:2] if has_header else []
    return _pack_lines(rows[len(header) :], header, [], max_tokens)


def _split_code(code: str, max_tokens: int) -> list[str]:
    """Split by line; every part is re-wrapped in the original fence so it stays valid."""
    lines = code.splitlines()
    opening = lines[0]
    closed = len(lines) > 1 and lines[-1].strip().startswith(opening.strip()[:3])
    body = lines[1:-1] if closed else lines[1:]
    closing = [lines[-1]] if closed else [opening.strip()[:3]]
    return _pack_lines(body, [opening], closing, max_tokens)


def _pack_lines(lines: list[str], head: list[str], tail: list[str], max_tokens: int) -> list[str]:
    budget = max_tokens - count_tokens("\n".join(head + tail)) - 2  # 2 for the joining newlines
    parts: list[str] = []
    current: list[str] = []
    for line in lines:
        for piece in split_by_tokens(line, budget) if count_tokens(line) > budget else [line]:
            if current and count_tokens("\n".join([*current, piece])) > budget:
                parts.append("\n".join(head + current + tail))
                current = []
            current.append(piece)
    if current:
        parts.append("\n".join(head + current + tail))
    return parts


# --- packing units into chunks, overlap and tiny-fragment merging ---------------------------


def _pack_section(section: Section, limits: ChunkLimits) -> list[_Draft]:
    drafts: list[_Draft] = []
    current: _Draft | None = None
    last: _Unit | None = None
    for unit in (unit for block in section.blocks for unit in _units(block, limits)):
        if current is None or last is None:
            current = _Draft(section, unit.text)
        elif count_tokens(current.text + unit.sep + unit.text) <= limits.max_tokens:
            current = _Draft(section, current.text + unit.sep + unit.text, current.overlap_chars)
        else:
            drafts.append(current)
            current = _start_after(current.text, last, unit, section, limits)
        last = unit
    if current is not None:
        drafts.append(current)
    return drafts


def _start_after(
    previous: str, last: _Unit, unit: _Unit, section: Section, limits: ChunkLimits
) -> _Draft:
    """Begin a new chunk, prefixed with the previous chunk's trailing sentences when prose."""
    if last.kind is BlockKind.TEXT and unit.kind is BlockKind.TEXT:
        overlap = _tail_sentences(previous, limits.overlap_tokens)
        joined = overlap + unit.sep + unit.text
        if overlap and count_tokens(joined) <= limits.max_tokens:
            return _Draft(section, joined, len(overlap))
    return _Draft(section, unit.text)


def _tail_sentences(text: str, max_tokens: int) -> str:
    sentences = SENTENCE_END.split(text.rsplit(BLOCK_SEPARATOR, 1)[-1])
    taken: list[str] = []
    for sentence in reversed(sentences):
        if count_tokens(" ".join([sentence, *taken])) > max_tokens:
            break
        taken.insert(0, sentence)
    return " ".join(taken)


def _merge_tiny(drafts: list[_Draft], max_tokens: int) -> list[_Draft]:
    """Fold chunks under MIN_CHUNK_TOKENS into the previous (else next) chunk when they fit."""
    result = list(drafts)
    i = 0
    while i < len(result):
        if len(result) == 1 or count_tokens(result[i].text) >= MIN_CHUNK_TOKENS:
            i += 1
            continue
        if i > 0 and (merged := _merge(result[i - 1], result[i], max_tokens, label_first=True)):
            result[i - 1 : i + 1] = [merged]
        elif i + 1 < len(result) and (
            merged := _merge(result[i], result[i + 1], max_tokens, label_first=False)
        ):
            result[i : i + 2] = [merged]
        else:
            i += 1
    return result


def _merge(first: _Draft, second: _Draft, max_tokens: int, *, label_first: bool) -> _Draft | None:
    """Join adjacent drafts; the merged chunk keeps the section label of the larger side.

    Within a section the second draft's overlap prefix is dropped (it is already in `first`).
    Across sections the absorbed side's heading is inlined, so its content stays attributed.
    """
    if first.section is second.section:
        text = first.text + BLOCK_SEPARATOR + second.text[second.overlap_chars :].lstrip()
    elif label_first:
        text = first.text + BLOCK_SEPARATOR + _with_heading(second)
    else:  # `first` joins the next section: shed its overlap, which belongs to its own section
        own = _Draft(first.section, first.text[first.overlap_chars :].lstrip())
        text = _with_heading(own) + BLOCK_SEPARATOR + second.text
    if count_tokens(text) > max_tokens:
        return None
    starts_with_first = first.section is second.section or label_first
    section = first.section if label_first else second.section
    return _Draft(section, text, first.overlap_chars if starts_with_first else 0)


def _with_heading(draft: _Draft) -> str:
    heading = draft.section.heading_line
    return f"{heading}{BLOCK_SEPARATOR}{draft.text}" if heading else draft.text
