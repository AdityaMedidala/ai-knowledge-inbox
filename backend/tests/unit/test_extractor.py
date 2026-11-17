from pathlib import Path

import pytest

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.extractor import TITLE_MAX_CHARS, extract_document
from app.services.fetcher import FetchedPage

ARTICLE = (Path(__file__).parents[1] / "fixtures" / "article.html").read_bytes()
URL = "https://blog.example.com/posts/wal/"


def fetched(
    body: bytes, content_type: str = "text/html", charset: str | None = "utf-8"
) -> FetchedPage:
    return FetchedPage(
        final_url=URL,
        http_status=200,
        content_type=content_type,
        charset=charset,
        body=body,
        redirects=0,
    )


def test_article_becomes_markdown_without_boilerplate() -> None:
    doc = extract_document(fetched(ARTICLE))
    assert doc.title == "Write-Ahead Logging in SQLite"
    assert "## How WAL mode works" in doc.text
    assert "### Checkpoints" in doc.text
    assert "| Readers during a write | Blocked | Allowed |" in doc.text
    assert 'conn.execute("PRAGMA journal_mode=WAL")' in doc.text
    for boilerplate in ("newsletter", "We are hiring", "Copyright", "Related posts", "Cookie"):
        assert boilerplate not in doc.text


def test_raw_content_keeps_the_decoded_page_source() -> None:
    doc = extract_document(fetched(ARTICLE))
    assert doc.raw_content == ARTICLE.decode("utf-8")


def test_title_falls_back_to_title_tag() -> None:
    html = (
        b"<html><head><title>Only The Tag</title></head><body><article>"
        + b"<p>"
        + b"Enough body text to count as a real article paragraph. " * 5
        + b"</p>"
        + b"</article></body></html>"
    )
    assert extract_document(fetched(html)).title == "Only The Tag"


def test_title_falls_back_to_host_and_path() -> None:
    html = b"<html><body><article><p>" + b"Body text without any title. " * 10 + b"</p></article>"
    assert extract_document(fetched(html)).title == "blog.example.com/posts/wal"


def test_long_titles_are_clipped() -> None:
    long_title = "Word " * 100
    html = f"<html><head><title>{long_title}</title></head><body><p>x</p></body></html>"
    doc = extract_document(fetched(html.encode(), content_type="text/html"))
    assert len(doc.title) <= TITLE_MAX_CHARS
    assert doc.title.endswith("…")


def test_plain_text_is_used_as_is() -> None:
    doc = extract_document(fetched(b"  line one\n\nline two  \n", content_type="text/plain"))
    assert doc.text == "line one\n\nline two"
    assert doc.title == "blog.example.com/posts/wal"


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (b"<html><body></body></html>", "text/html"),
        (b"<html><body><script>render()</script></body></html>", "text/html"),
        (b"   \n\t ", "text/plain"),
    ],
)
def test_empty_content(body: bytes, content_type: str) -> None:
    with pytest.raises(IngestError) as info:
        extract_document(fetched(body, content_type=content_type))
    assert info.value.code is ItemErrorCode.EMPTY_CONTENT
    assert not info.value.retryable


def test_charset_from_header_is_used_for_raw_content() -> None:
    body = "Café crème".encode("iso-8859-1")
    doc = extract_document(fetched(body, content_type="text/plain", charset="iso-8859-1"))
    assert doc.text == "Café crème"


def test_unknown_charset_falls_back_to_utf8() -> None:
    doc = extract_document(fetched("naïve".encode(), content_type="text/plain", charset="nope-8"))
    assert doc.text == "naïve"
