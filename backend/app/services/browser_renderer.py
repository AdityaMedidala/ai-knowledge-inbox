"""Headless Chromium for the JS-rendering fallback (JS_RENDER=on; needs the "render" extra).

Threading: ingestion jobs run in worker threads, but Playwright objects belong to the event loop
that created them. The renderer therefore lives on the app's event loop, and `render()` (called
from a job thread) schedules the work there and waits for it.

SSRF: every request the page makes, including each redirect hop, passes the same url_guard checks
as the fetcher. The route handler fetches each request itself and follows redirects hop by hop,
checking every hop; a 3xx is never handed to the browser, because Chromium would follow it
without routing the next hop through the handler (the integration test covers this). Images,
media, fonts, downloads, service workers and WebSockets are refused. Each render gets a fresh
context: no cookies, no storage.
"""

import asyncio
import concurrent.futures
import os
import re
from urllib.parse import urljoin

import structlog
from playwright.async_api import (
    APIResponse,
    Browser,
    Page,
    Playwright,
    Route,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.domain.errors import IngestError, RenderSetupError
from app.domain.models import ItemErrorCode
from app.services.renderer import RenderedPage, RequestGuard
from app.services.url_guard import Resolver
from app.utils.urls import redact_url

logger = structlog.get_logger(__name__)

# Statuses a site answers a headless browser with when it refuses bots. Never worked around.
REFUSAL_STATUSES = frozenset({401, 403, 429, 503})
ALL_URLS = re.compile(".*")
REDIRECT_MIN, REDIRECT_MAX = 300, 399
GET_AFTER_REDIRECT = frozenset({301, 302, 303})  # what browsers do for a non-GET request
QUEUE_GRACE_S = 30  # extra time a job may wait for one of the page slots


class PlaywrightRenderer:
    """One lazily launched browser shared by all jobs, at most `max_pages` pages at once."""

    def __init__(
        self,
        playwright: Playwright,
        loop: asyncio.AbstractEventLoop,
        *,
        timeout_s: float,
        max_bytes: int,
        max_pages: int,
        max_redirects: int = 3,
        resolver: Resolver | None = None,
        allowed_hosts: frozenset[str] = frozenset(),
    ) -> None:
        self._playwright = playwright
        self._loop = loop
        self._timeout_s = timeout_s
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._pages = asyncio.Semaphore(max_pages)
        self._launch_lock = asyncio.Lock()
        self._browser: Browser | None = None
        self._resolver = resolver
        self._allowed_hosts = allowed_hosts

    @classmethod
    async def start(
        cls,
        *,
        timeout_s: float,
        max_bytes: int,
        max_pages: int,
        max_redirects: int = 3,
        resolver: Resolver | None = None,
        allowed_hosts: frozenset[str] = frozenset(),
    ) -> "PlaywrightRenderer":
        """Starts the Playwright driver (not the browser) and checks Chromium is installed."""
        playwright = await async_playwright().start()
        if not os.path.exists(playwright.chromium.executable_path):
            await playwright.stop()
            raise RenderSetupError("Playwright's Chromium is not installed.")
        return cls(
            playwright,
            asyncio.get_running_loop(),
            timeout_s=timeout_s,
            max_bytes=max_bytes,
            max_pages=max_pages,
            max_redirects=max_redirects,
            resolver=resolver,
            allowed_hosts=allowed_hosts,
        )

    def render(self, url: str) -> RenderedPage:
        """Blocking; call from a worker thread, never from the event loop itself."""
        future = asyncio.run_coroutine_threadsafe(self._render(url), self._loop)
        try:
            return future.result(timeout=self._timeout_s + QUEUE_GRACE_S)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise _timeout(self._timeout_s) from exc

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        await self._playwright.stop()

    async def _render(self, url: str) -> RenderedPage:
        async with self._pages:
            browser = await self._ensure_browser()
            guard = RequestGuard(self._resolver, self._allowed_hosts)
            context = await browser.new_context(service_workers="block", accept_downloads=False)
            try:
                await context.route("**/*", lambda route: self._handle(route, guard))
                await context.route_web_socket(ALL_URLS, _refuse_websocket)
                page = await context.new_page()
                return await self._load(page, url, guard)
            finally:
                await context.close()

    async def _ensure_browser(self) -> Browser:
        async with self._launch_lock:
            if self._browser is None or not self._browser.is_connected():
                self._browser = await self._playwright.chromium.launch(headless=True)
                logger.info("render.browser_launched")
            return self._browser

    async def _handle(self, route: Route, guard: RequestGuard) -> None:
        try:
            response = await self._fetch_vetted(route, guard)
            if response is None:
                await route.abort("blockedbyclient")
            else:
                await route.fulfill(response=response)
        except PlaywrightError:
            # The page closed mid-request, or the fetch failed: the request simply fails.
            await _abort_quietly(route)

    async def _fetch_vetted(self, route: Route, guard: RequestGuard) -> APIResponse | None:
        """Fetch the request, following redirects here and vetting every hop; None if any hop
        is refused. Redirects are never handed to the browser: Chromium follows a fulfilled 3xx
        on its own, without routing the next hop back through this handler."""
        request = route.request
        url, method = request.url, request.method
        for _ in range(self._max_redirects + 1):
            if not await self._allowed(guard, url, request.resource_type):
                return None
            response = await route.fetch(
                url=url, method=method, max_redirects=0, timeout=self._timeout_s * 1000
            )
            location = response.headers.get("location")
            if not (REDIRECT_MIN <= response.status <= REDIRECT_MAX and location):
                return response
            url = urljoin(url, location)
            if response.status in GET_AFTER_REDIRECT:
                method = "GET"
        logger.info("render.too_many_redirects", url=redact_url(request.url))
        return None

    async def _allowed(self, guard: RequestGuard, url: str, resource_type: str) -> bool:
        reason = await asyncio.to_thread(guard.rejection, url, resource_type)
        if reason is None:
            return True
        if not reason.startswith("resource_type_"):
            guard.blocked.append(redact_url(url))
            logger.info("render.request_blocked", reason=reason, url=redact_url(url))
        return False

    async def _load(self, page: Page, url: str, guard: RequestGuard) -> RenderedPage:
        deadline = self._loop.time() + self._timeout_s
        try:
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=self._timeout_s * 1000
            )
        except PlaywrightTimeoutError as exc:
            raise _timeout(self._timeout_s) from exc
        except PlaywrightError as exc:
            if "ERR_BLOCKED_BY_CLIENT" in str(exc):
                raise IngestError(
                    ItemErrorCode.FETCH_BLOCKED,
                    "The page redirected to a private or local address.",
                ) from exc
            raise IngestError(
                ItemErrorCode.FETCH_FAILED, "The browser could not load the page."
            ) from exc
        if response is None:
            raise IngestError(ItemErrorCode.FETCH_FAILED, "The browser could not load the page.")
        _check_status(response.status)
        remaining_ms = (deadline - self._loop.time()) * 1000
        if remaining_ms > 0:
            try:
                await page.wait_for_load_state("networkidle", timeout=remaining_ms)
            except PlaywrightTimeoutError:
                logger.info("render.network_still_busy", timeout_s=self._timeout_s)
        html = await page.content()
        if len(html.encode("utf-8")) > self._max_bytes:
            raise IngestError(
                ItemErrorCode.CONTENT_TOO_LARGE, "The rendered page is larger than the size limit."
            )
        return RenderedPage(page.url, response.status, html, list(guard.blocked))


def _check_status(status: int) -> None:
    if status in REFUSAL_STATUSES:
        raise IngestError(
            ItemErrorCode.SITE_BLOCKED,
            f"The site refused automated access (HTTP {status}). Bot protection and CAPTCHAs "
            "are not worked around; save the text as a note instead.",
        )
    if status >= 400:
        raise IngestError(
            ItemErrorCode.FETCH_FAILED, f"The site returned HTTP {status} to the browser."
        )


def _timeout(seconds: float) -> IngestError:
    return IngestError(
        ItemErrorCode.FETCH_TIMEOUT,
        f"The page did not load in the browser within {seconds:g} s.",
        retryable=True,
    )


async def _refuse_websocket(websocket: WebSocketRoute) -> None:
    await websocket.close()


async def _abort_quietly(route: Route) -> None:
    try:
        await route.abort("failed")
    except PlaywrightError:
        logger.debug("render.route_already_handled")
