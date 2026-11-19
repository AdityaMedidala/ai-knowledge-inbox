"""Real headless Chromium against a local fixture server. Skipped unless the "render" extra and
its Chromium are installed (`uv sync --extra render && uv run playwright install chromium`)."""

import asyncio
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.async_api")
from playwright.sync_api import sync_playwright

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.browser_renderer import PlaywrightRenderer
from app.services.fetcher import FetchedPage
from app.services.renderer import extract_with_fallback

pytestmark = pytest.mark.browser

APP_HTML = (Path(__file__).parents[1] / "fixtures" / "js_render" / "app.html").read_bytes()
METADATA_URL = "http://169.254.169.254/latest/meta-data/"


def chromium_installed() -> bool:
    with sync_playwright() as playwright:
        return os.path.exists(playwright.chromium.executable_path)


if not chromium_installed():
    pytest.skip("Playwright's Chromium is not installed", allow_module_level=True)


class FixtureHandler(BaseHTTPRequestHandler):
    hits: list[str] = []  # noqa: RUF012 — shared request log, reset per server

    def do_GET(self) -> None:
        self.hits.append(self.path)
        if self.path == "/app":
            self._send(200, APP_HTML)
        elif self.path in ("/to-metadata", "/page-to-metadata"):
            self.send_response(302)
            self.send_header("Location", METADATA_URL)
            self.end_headers()
        elif self.path == "/refuse":
            self._send(403, b"<html><body>Are you a robot?</body></html>")
        else:
            self._send(404, b"not found")

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="module")
def base_url() -> Iterator[str]:
    FixtureHandler.hits = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def renderer() -> Iterator[PlaywrightRenderer]:
    """Like the app: the renderer lives on an event loop, render() is called from another thread."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    start = PlaywrightRenderer.start(
        timeout_s=10,
        max_bytes=5_000_000,
        max_pages=2,
        allowed_hosts=frozenset({"127.0.0.1"}),  # test-only: the fixture server is local
    )
    instance = asyncio.run_coroutine_threadsafe(start, loop).result(timeout=60)
    yield instance
    asyncio.run_coroutine_threadsafe(instance.close(), loop).result(timeout=30)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=10)


def test_text_that_only_javascript_writes_is_extracted(
    base_url: str, renderer: PlaywrightRenderer
) -> None:
    shell = FetchedPage(f"{base_url}/app", 200, "text/html", "utf-8", APP_HTML, 0)

    doc = extract_with_fallback(shell, renderer, min_chars=500)

    assert doc.extractor == "rendered"
    assert "this text only exists after JavaScript runs" in doc.text


def test_requests_to_private_addresses_and_redirects_to_them_are_blocked(
    base_url: str, renderer: PlaywrightRenderer
) -> None:
    page = renderer.render(f"{base_url}/app")

    assert "private: blocked" in page.html
    assert "redirect: blocked" in page.html
    assert any(url.startswith("http://10.0.0.1/") for url in page.blocked_requests)
    # The same-origin request was allowed; the hop it redirected to was checked and refused
    # (a fulfilled 3xx would make Chromium follow it unchecked, so the handler follows it).
    assert any(url.startswith("http://169.254.169.254/") for url in page.blocked_requests)
    assert "/to-metadata" in FixtureHandler.hits
    assert "/pixel.png" not in FixtureHandler.hits  # images are never requested


def test_navigation_redirecting_to_metadata_is_blocked(
    base_url: str, renderer: PlaywrightRenderer
) -> None:
    with pytest.raises(IngestError) as caught:
        renderer.render(f"{base_url}/page-to-metadata")
    assert caught.value.code is ItemErrorCode.FETCH_BLOCKED


def test_a_site_refusing_the_browser_fails_with_site_blocked(
    base_url: str, renderer: PlaywrightRenderer
) -> None:
    with pytest.raises(IngestError) as caught:
        renderer.render(f"{base_url}/refuse")
    assert caught.value.code is ItemErrorCode.SITE_BLOCKED
