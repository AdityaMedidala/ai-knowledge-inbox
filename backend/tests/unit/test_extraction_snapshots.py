"""Regression test on real pages saved in eval/corpus/ (offline): content trafilatura used to
drop must survive extraction, and section names must not carry pilcrows."""

import json
from pathlib import Path

import pytest

from app.services.chunker import ChunkLimits, chunk_document
from app.services.extractor import extract_document
from app.services.fetcher import FetchedPage
from app.services.html_fallback import count_headings, extract_markdown, prefer_fallback

CORPUS = Path(__file__).resolve().parents[2] / "eval" / "corpus"
LIMITS = ChunkLimits(max_tokens=350, overlap_tokens=60, max_block_tokens=400)


def snapshot(key: str) -> FetchedPage:
    meta = json.loads((CORPUS / f"{key}.meta.json").read_text("utf-8"))
    meta.pop("url")
    return FetchedPage(body=(CORPUS / f"{key}.body").read_bytes(), **meta)


@pytest.mark.parametrize(
    ("key", "min_headings", "must_contain"),
    [
        # bullet lists (favor_precision dropped them) and <span>-prefixed headings
        (
            "sqlite_wal_doc",
            15,
            ["WAL is significantly faster in most scenarios.", "# 2.1. Checkpointing"],
        ),
        # short <dl> section bodies
        ("asyncio_queue_doc", 5, ["retrieves entries in priority order (lowest first)"]),
        # whole sections ("Comments") trafilatura skipped
        ("pep8_doc", 30, ["Block comments generally apply to some (or all) code"]),
        ("sqlite3_doc", 25, ["Default five seconds."]),
    ],
)
def test_snapshot_keeps_lists_sections_and_headings(
    key: str, min_headings: int, must_contain: list[str]
) -> None:
    doc = extract_document(snapshot(key))
    assert count_headings(doc.text) >= min_headings
    for text in must_contain:
        assert text in doc.text
    sections = {c.section for c in chunk_document(doc.text, title=doc.title, limits=LIMITS)}
    assert len(sections - {None}) >= 4
    assert all("¶" not in (section or "") for section in sections)
    assert "¶" not in doc.text


def test_fallback_is_used_only_when_trafilatura_lost_something() -> None:
    assert extract_document(snapshot("sqlite3_doc")).extractor == "trafilatura"
    assert extract_document(snapshot("sqlite_wal_doc")).extractor == "fallback"


HTML = b"""<html><body><nav>Home | Docs</nav><main>
<h2>Queue<a class="headerlink" href="#q">\xc2\xb6</a></h2><p>A first in, first out queue.</p>
<h2>Priority Queue</h2><dl><dt>class PriorityQueue</dt>
<dd><p>Retrieves entries in priority order with the lowest first.</p></dd></dl>
<ul><li><strong>Standard library imports</strong><ul><li>nested item</li></ul></li></ul>
</main><div class="footer">Copyright</div></body></html>"""


def test_fallback_keeps_structure_and_drops_boilerplate() -> None:
    markdown = extract_markdown(HTML)
    assert markdown.splitlines()[0] == "## Queue"
    assert "Retrieves entries in priority order with the lowest first." in markdown
    assert "- Standard library imports\n  - nested item" in markdown
    assert "Home" not in markdown and "Copyright" not in markdown and "¶" not in markdown


def test_prefer_fallback_on_a_missing_section_or_lost_headings() -> None:
    fallback = (
        "## A\n\none two three four five six seven\n\n## B\n\nalpha beta gamma delta eps zeta"
    )
    lost_b = "## A\n\none two three four five six seven alpha"
    three_heads = "## A\n\nx\n\n## B\n\ny\n\n## C\n\nz"
    assert not prefer_fallback(fallback, fallback)
    assert prefer_fallback(lost_b, fallback)
    assert prefer_fallback("x y z", three_heads)
