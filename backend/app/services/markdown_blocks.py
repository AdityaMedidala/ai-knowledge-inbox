"""Markdown -> sections (by #/##/### heading path) -> blocks (paragraph, table, fenced code).

Tables and fences are recognised first, so a `#` line inside a code block is never a heading.
"""

import re
from dataclasses import dataclass, field
from enum import StrEnum

HEADING = re.compile(r"^(#{1,3})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE_OPEN = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
TABLE_ROW = re.compile(r"^[ \t]*\|")
SECTION_SEPARATOR = " > "


class BlockKind(StrEnum):
    TEXT = "text"
    TABLE = "table"
    CODE = "code"


@dataclass(frozen=True, slots=True)
class Block:
    kind: BlockKind
    text: str


@dataclass(slots=True)
class Section:
    path: str | None  # e.g. "Install > macOS"; None for text before the first heading
    heading_line: str | None  # the markdown heading itself, e.g. "## macOS"
    blocks: list[Block] = field(default_factory=list)


class _Parser:
    def __init__(self, markdown: str) -> None:
        self.lines = markdown.splitlines()
        self.sections = [Section(path=None, heading_line=None)]
        self.trail: list[tuple[int, str]] = []
        self.paragraph: list[str] = []

    def parse(self) -> list[Section]:
        i = 0
        while i < len(self.lines):
            i = self._step(i)
        self._flush_paragraph()
        return [section for section in self.sections if section.blocks]

    def _step(self, i: int) -> int:
        line = self.lines[i]
        if fence := FENCE_OPEN.match(line):
            end = _fence_end(self.lines, i, fence.group(1))
            self._add(BlockKind.CODE, "\n".join(self.lines[i:end]))
            return end
        if TABLE_ROW.match(line):
            end = i
            while end < len(self.lines) and TABLE_ROW.match(self.lines[end]):
                end += 1
            self._add(BlockKind.TABLE, "\n".join(row.strip() for row in self.lines[i:end]))
            return end
        if heading := HEADING.match(line):
            self._start_section(len(heading.group(1)), heading.group(2).strip(), line.strip())
        elif line.strip():
            self.paragraph.append(line.rstrip())
        else:
            self._flush_paragraph()
        return i + 1

    def _start_section(self, level: int, title: str, heading_line: str) -> None:
        self._flush_paragraph()
        self.trail = [(lvl, text) for lvl, text in self.trail if lvl < level] + [(level, title)]
        path = SECTION_SEPARATOR.join(text for _, text in self.trail)
        self.sections.append(Section(path=path, heading_line=heading_line))

    def _add(self, kind: BlockKind, text: str) -> None:
        self._flush_paragraph()
        self.sections[-1].blocks.append(Block(kind, text))

    def _flush_paragraph(self) -> None:
        text = "\n".join(self.paragraph).strip()
        self.paragraph = []
        if text:
            self.sections[-1].blocks.append(Block(BlockKind.TEXT, text))


def parse_sections(markdown: str) -> list[Section]:
    """Sections in document order; sections with no content (heading only) are dropped."""
    return _Parser(markdown).parse()


def _fence_end(lines: list[str], start: int, marker: str) -> int:
    """Index just past the closing fence (same char, at least as long); unclosed runs to EOF."""
    for j in range(start + 1, len(lines)):
        closing = lines[j].strip()
        if closing and set(closing) == {marker[0]} and len(closing) >= len(marker):
            return j + 1
    return len(lines)
