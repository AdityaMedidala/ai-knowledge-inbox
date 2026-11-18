"""Structural HTML → markdown, used when trafilatura drops content it shouldn't.

trafilatura is good at removing boilerplate from arbitrary pages but, on documentation pages,
it can drop short definition-list sections (Python's "Priority Queue") and headings whose text
starts with a <span> (every sqlite.org heading). This walker keeps the page structure instead:
headings, paragraphs, lists, definition lists, code blocks and tables of the main content,
minus navigation, sidebars and footers. It is cruder at boilerplate removal, so extractor.py
only picks it when trafilatura kept clearly less (see `prefer_fallback`).
"""

import re
from collections.abc import Iterator

import trafilatura
from lxml.html import HtmlElement

PILCROW = "¶"
_HEADINGS = {f"h{level}": level for level in range(1, 7)}
_DROP_TAGS = ("script", "style", "nav", "header", "footer", "aside", "noscript", "form", "button")
_DROP_CLASS = re.compile(r"\b(nav|sidebar|related|footer|menu|toc|breadcrumb)", re.I)
_INLINE = frozenset({"a", "span", "code", "em", "strong", "b", "i"})
_MAIN_XPATH = "//main | //article | //*[@role='main']"
_CONTAINERS = frozenset({"div", "section", "body", "main", "article", "dd", "blockquote", "span"})
_BLOCKS = frozenset(
    {*_HEADINGS, "p", "ul", "ol", "pre", "table", "dl", "dt", *_CONTAINERS} - {"span"}
)
_MD_SYNTAX = re.compile(r"^#+ |^- |^\| |^```", re.M)
_MD_HEADING = re.compile(r"^#{1,6} ", re.M)

MIN_KEPT_RATIO = 0.9  # trafilatura must keep 90% of the structural text
MIN_HEADINGS = 3
SECTION_PROBE_WORDS = 6  # a section counts as kept if its first words appear in trafilatura's
_WORD = re.compile(r"[a-z0-9]+")


def extract_markdown(body: bytes) -> str:
    tree = trafilatura.load_html(body)
    if tree is None:
        return ""
    roots = tree.xpath(_MAIN_XPATH)
    root = roots[0] if roots else tree.find(".//body")
    if root is None:
        return ""
    _strip_boilerplate(root)
    return "\n\n".join(block for block in _blocks(root) if block.strip())


def prefer_fallback(trafilatura_md: str, fallback_md: str) -> bool:
    """True when trafilatura kept < 90% of the structural text, lost every heading, or dropped
    the body of any section (small sections vanish without moving the overall ratio)."""
    kept, full = _plain_length(trafilatura_md), _plain_length(fallback_md)
    if full == 0:
        return False
    lost_text = kept < MIN_KEPT_RATIO * full
    lost_headings = (
        count_headings(fallback_md) >= MIN_HEADINGS and count_headings(trafilatura_md) == 0
    )
    return lost_text or lost_headings or bool(missing_sections(trafilatura_md, fallback_md))


def missing_sections(trafilatura_md: str, fallback_md: str) -> list[str]:
    """Headings of fallback sections whose opening words are absent from trafilatura's text."""
    kept_words = " ".join(_words(trafilatura_md))
    missing = []
    for heading, body in _sections(fallback_md):
        probe = _words(body)[:SECTION_PROBE_WORDS]
        if len(probe) == SECTION_PROBE_WORDS and " ".join(probe) not in kept_words:
            missing.append(heading)
    return missing


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _sections(markdown: str) -> Iterator[tuple[str, str]]:
    outside_code = re.sub(r"```.*?```", "", markdown, flags=re.S)
    parts = re.split(r"^(#{1,6} .*)$", outside_code, flags=re.M)
    yield from zip(parts[1::2], parts[2::2], strict=True)


def count_headings(markdown: str) -> int:
    """Markdown headings outside fenced code (a '# comment' in code is not a heading)."""
    outside_code = re.sub(r"```.*?```", "", markdown, flags=re.S)
    return len(_MD_HEADING.findall(outside_code))


def strip_pilcrows(markdown: str) -> str:
    return markdown.replace(PILCROW, "")


def _plain_length(markdown: str) -> int:
    return len("".join(_MD_SYNTAX.sub("", markdown).split()))


def _strip_boilerplate(root: HtmlElement) -> None:
    for element in list(root.iter()):
        if not isinstance(element.tag, str) or element.getparent() is None:
            continue
        css = f"{element.get('class', '')} {element.get('role', '')}"
        boilerplate_block = element.tag not in _INLINE and (
            _DROP_CLASS.search(css) or "navigation" in css
        )
        if element.tag in _DROP_TAGS or boilerplate_block or "headerlink" in css:
            element.drop_tree()


def _text(element: HtmlElement) -> str:
    return " ".join(strip_pilcrows(element.text_content()).split())


def _blocks(element: HtmlElement) -> Iterator[str]:
    for child in element:
        if not isinstance(child.tag, str):
            continue
        tag = child.tag
        if tag in _HEADINGS:
            yield f"{'#' * _HEADINGS[tag]} {_text(child)}"
        elif tag in ("p", "dt"):
            yield _text(child)
        elif tag in ("ul", "ol"):
            yield "\n".join(_list_items(child, depth=0))
        elif tag == "pre":
            yield f"```\n{strip_pilcrows(child.text_content()).strip()}\n```"
        elif tag == "table":
            yield "\n".join(_table_rows(child))
        elif tag in ("dl", *_CONTAINERS):
            has_blocks = any(
                isinstance(e.tag, str) and e.tag in _BLOCKS for e in child.iterdescendants()
            )
            yield from _blocks(child) if has_blocks else iter([_text(child)])


def _list_items(list_element: HtmlElement, depth: int) -> Iterator[str]:
    for item in list_element.findall("li"):
        nested = item.findall("ul") + item.findall("ol")
        for sub in nested:
            item.remove(sub)
        text = _text(item)
        if text:
            yield f"{'  ' * depth}- {text}"
        for sub in nested:
            yield from _list_items(sub, depth + 1)


def _table_rows(table: HtmlElement) -> Iterator[str]:
    for row in table.iter("tr"):
        cells = [_text(cell).replace("|", "\\|") for cell in row if cell.tag in ("td", "th")]
        if cells:
            yield "| " + " | ".join(cells) + " |"
