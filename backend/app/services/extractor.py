"""Fetched page -> markdown + title. No JS rendering (see README "Known limitations")."""

import codecs
from dataclasses import dataclass
from urllib.parse import urlsplit

import trafilatura

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.fetcher import FetchedPage
from app.services.html_fallback import extract_markdown, prefer_fallback, strip_pilcrows

TITLE_MAX_CHARS = 200
DEFAULT_CHARSET = "utf-8"


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    title: str
    text: str  # markdown used for chunking
    raw_content: str  # decoded page source, stored for re-extraction; never returned by the API
    extractor: str = "plain"  # plain | trafilatura | fallback (which one produced `text`)


def extract_document(page: FetchedPage) -> ExtractedDocument:
    raw = _decode(page.body, page.charset)
    if page.content_type == "text/plain":
        text, title, extractor = raw.strip(), None, "plain"
    else:
        text, extractor = _html_markdown(page.body)
        title = _html_title(page.body)
    if not text:
        raise IngestError(
            ItemErrorCode.EMPTY_CONTENT,
            "No readable text was found on the page (it may need JavaScript to render).",
        )
    return ExtractedDocument(
        title=_clip(title or _url_title(page.final_url)),
        text=text,
        raw_content=raw,
        extractor=extractor,
    )


def _html_markdown(body: bytes) -> tuple[str, str]:
    """trafilatura (favor_recall keeps bullet lists that favor_precision drops), unless the
    structural fallback shows it lost text or every heading. Pilcrow anchors are removed."""
    # Raw bytes, so trafilatura can honour the document's own <meta charset>.
    primary = (
        trafilatura.extract(
            body,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        or ""
    ).strip()
    fallback = extract_markdown(body).strip()
    if prefer_fallback(primary, fallback):
        return strip_pilcrows(fallback), "fallback"
    return strip_pilcrows(primary), "trafilatura"


def _html_title(body: bytes) -> str | None:
    metadata = trafilatura.extract_metadata(body)
    if metadata is not None and metadata.title and metadata.title.strip():
        return metadata.title.strip()
    tree = trafilatura.load_html(body)
    tag_title = tree.findtext(".//title") if tree is not None else None
    return tag_title.strip() if tag_title and tag_title.strip() else None


def _url_title(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.hostname or ''}{parts.path.rstrip('/')}" or url


def _decode(body: bytes, charset: str | None) -> str:
    encoding = DEFAULT_CHARSET
    if charset:
        try:
            encoding = codecs.lookup(charset).name
        except LookupError:
            encoding = DEFAULT_CHARSET
    return body.decode(encoding, errors="replace")


def _clip(title: str) -> str:
    title = " ".join(title.split())
    return title if len(title) <= TITLE_MAX_CHARS else title[: TITLE_MAX_CHARS - 1].rstrip() + "…"
