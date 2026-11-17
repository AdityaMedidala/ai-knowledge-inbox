"""SSRF-safe HTTP fetch: every hop is vetted, redirects are followed by hand, the body is capped.

Per hop: check_url (same rules as submission) -> check_resolved_host -> send -> peer-IP check
(before any body byte is read) -> redirect or read. httpx2 connects by hostname itself, so the
peer check is what catches DNS rebinding; the request has already been sent by then (see README
"Known limitations").
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx2
import structlog

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.url_guard import (
    Resolver,
    UrlRejectedError,
    UrlRejection,
    check_peer_address,
    check_resolved_host,
    check_url,
)
from app.utils.urls import redact_url

logger = structlog.get_logger(__name__)

USER_AGENT = "AIKnowledgeInbox/0.1 (personal read-later fetcher; one request per saved URL)"
ACCEPT = "text/html,application/xhtml+xml,text/plain;q=0.9"
ALLOWED_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml", "text/plain"})
RETRYABLE_STATUSES = frozenset({408, 425, 429})


@dataclass(frozen=True, slots=True)
class FetchedPage:
    final_url: str
    http_status: int
    content_type: str  # media type only, lowercased, e.g. "text/html"
    charset: str | None
    body: bytes  # decoded Content-Encoding, at most max_bytes
    redirects: int


def build_fetch_client() -> httpx2.Client:
    """trust_env=False: an HTTP(S)_PROXY from the environment would bypass the peer check."""
    return httpx2.Client(follow_redirects=False, trust_env=False)


class Fetcher:
    def __init__(
        self,
        client: httpx2.Client,
        *,
        timeout_s: float,
        max_bytes: int,
        max_redirects: int,
        resolver: Resolver | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._resolver = resolver
        self._monotonic = monotonic

    def fetch(self, url: str) -> FetchedPage:
        """Raises IngestError with FETCH_* / UNSUPPORTED_CONTENT / CONTENT_TOO_LARGE codes."""
        deadline = self._monotonic() + self._timeout_s
        current = url
        try:
            for hop in range(self._max_redirects + 1):
                self._vet_target(current)
                with self._client.stream(
                    "GET", current, headers=_request_headers(), timeout=self._timeout_s
                ) as response:
                    self._vet_peer(response)
                    location = _redirect_location(response, current)
                    if location is None:
                        return self._read(response, current, hop, deadline)
                logger.debug(
                    "fetch.redirect",
                    hop=hop + 1,
                    status=response.status_code,
                    to=redact_url(location),
                )
                current = location
        except httpx2.TimeoutException as exc:
            raise IngestError(
                ItemErrorCode.FETCH_TIMEOUT, "The site took too long to respond.", retryable=True
            ) from exc
        except httpx2.DecodingError as exc:
            raise IngestError(
                ItemErrorCode.FETCH_FAILED, "The site sent a corrupt compressed response."
            ) from exc
        except httpx2.TransportError as exc:
            raise IngestError(
                ItemErrorCode.FETCH_FAILED, "Could not connect to the site.", retryable=True
            ) from exc
        raise IngestError(
            ItemErrorCode.FETCH_FAILED, f"Too many redirects (limit {self._max_redirects})."
        )

    def _vet_target(self, url: str) -> None:
        try:
            target = check_url(url)
            check_resolved_host(target.host, target.port, self._resolver)
        except UrlRejectedError as exc:
            raise _blocked_or_unresolvable(exc, url) from exc

    def _vet_peer(self, response: httpx2.Response) -> None:
        stream = response.extensions.get("network_stream")
        peer = stream.get_extra_info("server_addr") if stream is not None else None
        try:
            check_peer_address(peer or ())  # unknown peer fails closed
        except UrlRejectedError as exc:
            raise _blocked_or_unresolvable(exc, str(response.url)) from exc

    def _read(
        self, response: httpx2.Response, url: str, redirects: int, deadline: float
    ) -> FetchedPage:
        _check_status(response.status_code)
        media_type, charset = _parse_content_type(response.headers.get("content-type", ""))
        if media_type not in ALLOWED_CONTENT_TYPES:
            raise IngestError(
                ItemErrorCode.UNSUPPORTED_CONTENT,
                f"Unsupported content type '{media_type or 'unknown'}'; "
                "only HTML and plain-text pages can be saved.",
            )
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise self._too_large()

        body = bytearray()
        for piece in response.iter_bytes():  # yields bytes AFTER Content-Encoding decoding
            body += piece
            if len(body) > self._max_bytes:
                raise self._too_large()
            if self._monotonic() > deadline:
                raise httpx2.ReadTimeout("fetch deadline exceeded")
        return FetchedPage(
            final_url=url,
            http_status=response.status_code,
            content_type=media_type,
            charset=charset,
            body=bytes(body),
            redirects=redirects,
        )

    def _too_large(self) -> IngestError:
        limit_mb = self._max_bytes / 1_000_000
        return IngestError(
            ItemErrorCode.CONTENT_TOO_LARGE, f"The page is larger than the {limit_mb:g} MB limit."
        )


def _request_headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT, "Accept": ACCEPT}


def _redirect_location(response: httpx2.Response, current: str) -> str | None:
    if not response.is_redirect:
        return None
    location = response.headers.get("location")
    if not location:
        raise IngestError(ItemErrorCode.FETCH_FAILED, "The site sent a redirect with no target.")
    return urljoin(current, location)


def _check_status(status: int) -> None:
    if 200 <= status < 300:
        return
    retryable = status >= 500 or status in RETRYABLE_STATUSES
    raise IngestError(
        ItemErrorCode.FETCH_FAILED, f"The site responded with HTTP {status}.", retryable=retryable
    )


def _parse_content_type(header: str) -> tuple[str, str | None]:
    media_type, *params = (part.strip() for part in header.split(";"))
    charset = None
    for param in params:
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset" and value.strip():
            charset = value.strip().strip('"').lower()
    return media_type.lower(), charset


def _blocked_or_unresolvable(exc: UrlRejectedError, url: str) -> IngestError:
    if exc.reason is UrlRejection.UNRESOLVABLE:
        return IngestError(ItemErrorCode.FETCH_FAILED, exc.message, retryable=exc.transient)
    logger.warning("fetch.blocked", reason=exc.reason, url=redact_url(url))
    return IngestError(ItemErrorCode.FETCH_BLOCKED, exc.message)
