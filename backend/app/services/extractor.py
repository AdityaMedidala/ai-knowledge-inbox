"""Fetched page -> markdown + title. No JS rendering (see README "Known limitations")."""

import codecs
from dataclasses import dataclass
from urllib.parse import urlsplit

import trafilatura

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.fetcher import FetchedPage

TITLE_MAX_CHARS = 200
DEFAULT_CHARSET = "utf-8"


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    title: str
    text: str  # markdown used for chunking
    raw_content: str  # decoded page source, stored for re-extraction; never returned by the API


def extract_document(page: FetchedPage) -> ExtractedDocument:
    raw = _decode(page.body, page.charset)
    if page.content_type == "text/plain":
        text, title = raw.strip(), None
    else:
        # Raw bytes, so trafilatura can honour the document's own <meta charset>.
        text = (
            trafilatura.extract(
                page.body,
                output_format="markdown",
                include_comments=False,
                include_tables=True,
                favor_precision=True,
            )
            or ""
        ).strip()
        title = _html_title(page.body)
    if not text:
        raise IngestError(
            ItemErrorCode.EMPTY_CONTENT,
            "No readable text was found on the page (it may need JavaScript to render).",
        )
    return ExtractedDocument(
        title=_clip(title or _url_title(page.final_url)), text=text, raw_content=raw
    )


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
