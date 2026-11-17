"""Real fixture page through trafilatura and the chunker, with production chunk limits."""

from pathlib import Path

import pytest

from app.config import Settings
from app.domain.models import NewChunk
from app.services.chunker import ChunkLimits, chunk_document
from app.services.extractor import extract_document
from app.services.fetcher import FetchedPage
from tests.support.chunk_invariants import assert_chunk_invariants

ARTICLE = (Path(__file__).parents[1] / "fixtures" / "article.html").read_bytes()
TITLE = "Write-Ahead Logging in SQLite"


def production_limits() -> ChunkLimits:
    fields = Settings.model_fields
    return ChunkLimits(
        max_tokens=fields["chunk_tokens"].default,
        overlap_tokens=fields["chunk_overlap_tokens"].default,
        max_block_tokens=fields["chunk_max_block_tokens"].default,
    )


@pytest.fixture(scope="module")
def chunks() -> list[NewChunk]:
    page = FetchedPage(
        final_url="https://blog.example.com/posts/wal",
        http_status=200,
        content_type="text/html",
        charset="utf-8",
        body=ARTICLE,
        redirects=0,
    )
    doc = extract_document(page)
    result = chunk_document(doc.text, title=doc.title, limits=production_limits())
    assert_chunk_invariants(result, doc.text, production_limits())
    return result


def test_sections_follow_the_article_headings(chunks: list[NewChunk]) -> None:
    assert [c.section for c in chunks] == [
        TITLE,
        f"{TITLE} > How the rollback journal works",
        f"{TITLE} > How WAL mode works",
        f"{TITLE} > How WAL mode works > Checkpoints",
        f"{TITLE} > How WAL mode works > Comparing the modes",
        f"{TITLE} > Enabling WAL",
    ]
    assert all(c.context_header.startswith(f"Title: {TITLE}\nSection: ") for c in chunks)


def test_table_and_code_block_stay_whole(chunks: list[NewChunk]) -> None:
    [table_chunk] = [c for c in chunks if "| Property |" in c.text]
    assert "| Readers during a write | Blocked | Allowed |" in table_chunk.text
    assert "| Write throughput | Lower | Higher |" in table_chunk.text

    [code_chunk] = [c for c in chunks if "```" in c.text]
    fence = code_chunk.text[code_chunk.text.index("```") :]
    assert fence.count("```") == 2
    assert "PRAGMA journal_mode=WAL" in fence and "PRAGMA foreign_keys=ON" in fence


def test_boilerplate_is_dropped(chunks: list[NewChunk]) -> None:
    everything = "\n".join(c.text for c in chunks)
    for boilerplate in ("Subscribe", "hiring", "Archive", "Related posts", "Copyright", "Privacy"):
        assert boilerplate not in everything
