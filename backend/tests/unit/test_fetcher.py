import gzip
import logging
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from structlog.testing import capture_logs

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.logging import QUIET_LIBRARY_LOGGERS, configure_logging
from app.services.fetcher import USER_AGENT, FetchedPage, Fetcher
from tests.support.dns import PUBLIC_IP, FakeResolver, fake_resolver
from tests.support.http_pages import HTML, page, redirect
from tests.support.mock_http import MockRouter

URL = "https://example.com/post"
MAX_BYTES = 1_000


def make_fetcher(
    router: MockRouter,
    *,
    resolver: FakeResolver | None = None,
    max_redirects: int = 3,
    monotonic: Any = None,
) -> Fetcher:
    kwargs = {"monotonic": monotonic} if monotonic else {}
    return Fetcher(
        router.client(),
        timeout_s=5,
        max_bytes=MAX_BYTES,
        max_redirects=max_redirects,
        resolver=resolver or fake_resolver(PUBLIC_IP),
        **kwargs,
    )


def fetch_error(fetcher: Fetcher, url: str = URL) -> IngestError:
    with pytest.raises(IngestError) as info:
        fetcher.fetch(url)
    return info.value


class CountingBody:
    """Streaming body without Content-Length; records how many pieces were pulled."""

    def __init__(self, pieces: int, size: int) -> None:
        self.pieces, self.size, self.pulled = pieces, size, 0

    def __iter__(self) -> Iterator[bytes]:
        for _ in range(self.pieces):
            self.pulled += 1
            yield b"a" * self.size


# --- success --------------------------------------------------------------------------------


def test_fetches_html_with_honest_headers(mock_http: MockRouter) -> None:
    route = mock_http.add("GET", URL, page())
    result = make_fetcher(mock_http).fetch(URL)
    assert result == FetchedPage(
        final_url=URL,
        http_status=200,
        content_type="text/html",
        charset="utf-8",
        body=HTML,
        redirects=0,
    )
    assert route.last_request.headers["user-agent"] == USER_AGENT
    assert "text/html" in route.last_request.headers["accept"]


@pytest.mark.parametrize("content_type", ["text/plain", "application/xhtml+xml", "TEXT/HTML"])
def test_accepts_supported_content_types(mock_http: MockRouter, content_type: str) -> None:
    mock_http.add("GET", URL, page(content_type=content_type))
    assert make_fetcher(mock_http).fetch(URL).content_type == content_type.lower()


# --- content type and size ------------------------------------------------------------------


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "application/json", None])
def test_rejects_unsupported_content(mock_http: MockRouter, content_type: str | None) -> None:
    mock_http.add("GET", URL, page(content_type=content_type))
    error = fetch_error(make_fetcher(mock_http))
    assert error.code is ItemErrorCode.UNSUPPORTED_CONTENT
    assert not error.retryable


def test_declared_content_length_over_cap_is_rejected_before_reading(
    mock_http: MockRouter,
) -> None:
    body = CountingBody(pieces=1, size=10)
    mock_http.add("GET", URL, page(body=body, headers={"content-length": str(MAX_BYTES + 1)}))
    assert fetch_error(make_fetcher(mock_http)).code is ItemErrorCode.CONTENT_TOO_LARGE
    assert body.pulled == 0


def test_streamed_body_stops_reading_once_over_cap(mock_http: MockRouter) -> None:
    body = CountingBody(pieces=50, size=400)  # 20 KB total, no Content-Length
    mock_http.add("GET", URL, page(body=body))
    assert fetch_error(make_fetcher(mock_http)).code is ItemErrorCode.CONTENT_TOO_LARGE
    assert body.pulled == 3  # 1200 bytes > 1000: stopped on the third piece


def test_cap_counts_decoded_bytes_not_wire_bytes(mock_http: MockRouter) -> None:
    compressed = gzip.compress(b"a" * (MAX_BYTES * 50))
    assert len(compressed) < MAX_BYTES  # small on the wire
    mock_http.add("GET", URL, page(body=compressed, headers={"content-encoding": "gzip"}))
    assert fetch_error(make_fetcher(mock_http)).code is ItemErrorCode.CONTENT_TOO_LARGE


def test_body_exactly_at_cap_is_accepted(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, page(body=b"a" * MAX_BYTES, content_type="text/plain"))
    assert len(make_fetcher(mock_http).fetch(URL).body) == MAX_BYTES


def test_corrupt_gzip_is_a_permanent_fetch_failure(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, page(body=b"not gzip", headers={"content-encoding": "gzip"}))
    error = fetch_error(make_fetcher(mock_http))
    assert (error.code, error.retryable) == (ItemErrorCode.FETCH_FAILED, False)


# --- status codes, timeouts, transport errors -----------------------------------------------


@pytest.mark.parametrize(
    ("status", "retryable"), [(404, False), (403, False), (410, False), (429, True), (503, True)]
)
def test_http_error_status(mock_http: MockRouter, status: int, retryable: bool) -> None:
    mock_http.add("GET", URL, page(status))
    error = fetch_error(make_fetcher(mock_http))
    assert (error.code, error.retryable) == (ItemErrorCode.FETCH_FAILED, retryable)
    assert str(status) in error.message


def test_timeout_is_retryable(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, httpx2.ReadTimeout("slow"))
    error = fetch_error(make_fetcher(mock_http))
    assert (error.code, error.retryable) == (ItemErrorCode.FETCH_TIMEOUT, True)


def test_connect_error_is_retryable(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, httpx2.ConnectError("refused"))
    error = fetch_error(make_fetcher(mock_http))
    assert (error.code, error.retryable) == (ItemErrorCode.FETCH_FAILED, True)


def test_trickling_body_hits_the_overall_deadline(mock_http: MockRouter) -> None:
    ticks = iter(range(0, 1000, 2))  # every reading advances the clock 2 s; timeout is 5 s
    body = CountingBody(pieces=10, size=1)
    mock_http.add("GET", URL, page(body=body))
    error = fetch_error(make_fetcher(mock_http, monotonic=lambda: next(ticks)))
    assert error.code is ItemErrorCode.FETCH_TIMEOUT
    assert body.pulled < 10


# --- redirects ------------------------------------------------------------------------------


def test_follows_redirect_chain_manually(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, redirect("/moved", 301))
    mock_http.add("GET", "https://example.com/moved", redirect("https://www.example.com/final"))
    mock_http.add("GET", "https://www.example.com/final", page())
    result = make_fetcher(mock_http).fetch(URL)
    assert (result.final_url, result.redirects) == ("https://www.example.com/final", 2)
    mock_http.assert_all_called()


def test_too_many_redirects(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, redirect("/a"))
    mock_http.add("GET", "https://example.com/a", redirect("/b"))
    error = fetch_error(make_fetcher(mock_http, max_redirects=1))
    assert (error.code, error.retryable) == (ItemErrorCode.FETCH_FAILED, False)
    assert "redirects" in error.message


def test_redirect_without_location_fails(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, page(302, b""))
    assert fetch_error(make_fetcher(mock_http)).code is ItemErrorCode.FETCH_FAILED


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:10.0.0.1]/",
        "http://user:pass@example.com/",
        "https://example.com:8080/",
        "ftp://example.com/file",
        "http://localhost/",
        "http://metadata.google.internal/",
    ],
)
def test_redirect_hop_gets_submission_rules(mock_http: MockRouter, location: str) -> None:
    mock_http.add("GET", URL, redirect(location))
    error = fetch_error(make_fetcher(mock_http))
    assert (error.code, error.retryable) == (ItemErrorCode.FETCH_BLOCKED, False)


def test_redirect_to_host_resolving_privately_is_blocked(mock_http: MockRouter) -> None:
    resolver = FakeResolver({"example.com": [PUBLIC_IP], "sneaky.example": ["10.0.0.7"]})
    mock_http.add("GET", URL, redirect("https://sneaky.example/"))
    error = fetch_error(make_fetcher(mock_http, resolver=resolver))
    assert error.code is ItemErrorCode.FETCH_BLOCKED
    assert resolver.queried == ["example.com", "sneaky.example"]


# --- resolution and peer checks -------------------------------------------------------------


def test_private_resolution_blocks_before_any_request(mock_http: MockRouter) -> None:
    error = fetch_error(make_fetcher(mock_http, resolver=fake_resolver("192.168.1.5")))
    assert error.code is ItemErrorCode.FETCH_BLOCKED
    assert mock_http.unmatched == []  # nothing was sent


def test_unresolvable_host_is_a_fetch_failure(mock_http: MockRouter) -> None:
    error = fetch_error(make_fetcher(mock_http, resolver=FakeResolver({})))
    assert (error.code, error.retryable) == (ItemErrorCode.FETCH_FAILED, False)


@pytest.mark.parametrize("peer", [("127.0.0.1", 443), ("::ffff:192.168.0.1", 443, 0, 0), None])
def test_rebinding_peer_is_blocked_before_body_is_read(
    mock_http: MockRouter, peer: tuple[Any, ...] | None
) -> None:
    body = CountingBody(pieces=1, size=10)
    mock_http.add("GET", URL, page(body=body, peer=peer))
    assert fetch_error(make_fetcher(mock_http)).code is ItemErrorCode.FETCH_BLOCKED
    assert body.pulled == 0


def test_missing_network_stream_fails_closed(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, httpx2.Response(200, headers={"content-type": "text/html"}))
    assert fetch_error(make_fetcher(mock_http)).code is ItemErrorCode.FETCH_BLOCKED


# --- logging hygiene ------------------------------------------------------------------------


def test_blocked_log_line_redacts_query_and_fragment(mock_http: MockRouter) -> None:
    mock_http.add("GET", URL, redirect("http://10.0.0.1/hook?token=SECRET#x"))
    with capture_logs() as logs:
        fetch_error(make_fetcher(mock_http))
    blocked = [line for line in logs if line["event"] == "fetch.blocked"]
    assert blocked and blocked[0]["url"] == "http://10.0.0.1/hook"
    assert "SECRET" not in repr(logs)


def test_http_library_loggers_are_quieted() -> None:
    configure_logging("DEBUG", json_logs=True)
    for name in ("httpx2", "httpcore2"):
        assert name in QUIET_LIBRARY_LOGGERS
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
