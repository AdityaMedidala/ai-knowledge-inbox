"""JavaScript-rendering fallback: when plain extraction finds (almost) no text, render the page
in a headless browser and run the same extractor on the rendered HTML.

The browser itself lives in browser_renderer.py (optional Playwright dependency); this module
holds the protocol and the decision of when to render and which result to keep.
"""

from dataclasses import dataclass, field, replace
from typing import Protocol
from urllib.parse import urlsplit

import structlog

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.extractor import ExtractedDocument, extract_document
from app.services.fetcher import FetchedPage
from app.services.url_guard import Resolver, UrlRejectedError, check_resolved_host, check_url
from app.utils.urls import redact_url

logger = structlog.get_logger(__name__)

RENDERED = "rendered"
HTML_TYPES = frozenset({"text/html", "application/xhtml+xml"})
BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})


@dataclass(frozen=True, slots=True)
class RenderedPage:
    final_url: str
    http_status: int
    html: str
    blocked_requests: list[str]  # redacted URLs the browser was not allowed to load


@dataclass(slots=True)
class RequestGuard:
    """Decides, per request, whether the page may make it. `allowed_hosts` is for tests only
    (a local fixture server); production code never passes it."""

    resolver: Resolver | None = None
    allowed_hosts: frozenset[str] = frozenset()
    blocked: list[str] = field(default_factory=list)

    def rejection(self, url: str, resource_type: str) -> str | None:
        """Why this request may not be made, or None to allow it. Resolves DNS: call off-loop."""
        if resource_type in BLOCKED_RESOURCE_TYPES:
            return f"resource_type_{resource_type}"
        if urlsplit(url).hostname in self.allowed_hosts:
            return None
        try:
            target = check_url(url)
            check_resolved_host(target.host, target.port, self.resolver)
        except UrlRejectedError as exc:
            return exc.reason.value
        return None


class PageRenderer(Protocol):
    def render(self, url: str) -> RenderedPage:
        """Raises IngestError (FETCH_BLOCKED, FETCH_TIMEOUT, SITE_BLOCKED, FETCH_FAILED, ...)."""
        ...


def extract_with_fallback(
    page: FetchedPage, renderer: PageRenderer | None, min_chars: int
) -> ExtractedDocument:
    """Normal extraction; if it is empty or shorter than `min_chars` and the page is HTML, try
    the rendered page and keep whichever has more text. A failed render only fails the item
    when plain extraction found nothing at all."""
    try:
        plain: ExtractedDocument | None = extract_document(page)
    except IngestError as exc:
        if exc.code is not ItemErrorCode.EMPTY_CONTENT or not _can_render(page, renderer):
            raise
        plain = None
    if plain is not None and (len(plain.text) >= min_chars or not _can_render(page, renderer)):
        return plain
    assert renderer is not None  # noqa: S101 — _can_render checked it
    rendered = _render(renderer, page.final_url, keep=plain)
    if rendered is None or (plain is not None and len(rendered.text) <= len(plain.text)):
        assert plain is not None  # noqa: S101 — _render only returns None when it can keep plain
        return plain
    return rendered


def _can_render(page: FetchedPage, renderer: PageRenderer | None) -> bool:
    return renderer is not None and page.content_type in HTML_TYPES


def _render(
    renderer: PageRenderer, url: str, *, keep: ExtractedDocument | None
) -> ExtractedDocument | None:
    """The rendered document, or None when rendering failed but `keep` is worth keeping."""
    try:
        result = renderer.render(url)
        doc = extract_document(_as_page(result))
    except IngestError as exc:
        if keep is None:
            raise
        logger.warning("ingest.render_failed", error_code=exc.code, url=redact_url(url))
        return None
    logger.info(
        "ingest.rendered",
        chars=len(doc.text),
        blocked_requests=len(result.blocked_requests),
        url=redact_url(result.final_url),
    )
    return replace(doc, extractor=RENDERED)


def _as_page(result: RenderedPage) -> FetchedPage:
    return FetchedPage(
        final_url=result.final_url,
        http_status=result.http_status,
        content_type="text/html",
        charset="utf-8",
        body=result.html.encode("utf-8"),
        redirects=0,
    )
