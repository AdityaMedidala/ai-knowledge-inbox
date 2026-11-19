"""The JS-rendering fallback, with a fake renderer: when it runs, what it keeps, how it fails."""

import asyncio
import sys

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.errors import IngestError, RenderSetupError
from app.domain.models import ItemErrorCode, ItemStatus
from app.main import create_app
from app.providers.fakes import FakeEmbedder
from app.render_setup import start_renderer
from app.services.fetcher import FetchedPage
from app.services.ingestion import IngestionService, Outcome
from app.services.renderer import RenderedPage
from app.store.repository import Repository
from tests.conftest import TEST_DIM
from tests.unit.test_ingestion import SETTINGS, URL, StubFetcher, add_url, stored

SHELL_HTML = "<html><head><title>App</title></head><body><div id='root'></div></body></html>"
TEASER = "Short teaser before the app loads its content."
JS_TEXT = "This paragraph only exists after JavaScript runs on the page."


def html_page(*paragraphs: str, title: str = "Rendered article") -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f"<html><head><title>{title}</title></head><body><article>{body}</article></body></html>"


def long_paragraphs(tag: str) -> list[str]:
    return [f"{tag} paragraph {n}: {JS_TEXT} It adds detail number {n}." for n in range(12)]


def fetched(html: str, content_type: str = "text/html") -> FetchedPage:
    return FetchedPage(URL, 200, content_type, "utf-8", html.encode(), 0)


class FakeRenderer:
    def __init__(self, result: RenderedPage | IngestError) -> None:
        self.result = result
        self.urls: list[str] = []

    def render(self, url: str) -> RenderedPage:
        self.urls.append(url)
        if isinstance(self.result, IngestError):
            raise self.result
        return self.result


def rendered(*paragraphs: str) -> RenderedPage:
    return RenderedPage(URL, 200, html_page(*paragraphs), blocked_requests=[])


def run(repo: Repository, page: FetchedPage, renderer: FakeRenderer | None) -> str:
    item = add_url(repo)
    service = IngestionService(repo, FakeEmbedder(TEST_DIM), StubFetcher(page), SETTINGS, renderer)
    service.process(item.id)
    return item.id


def test_short_page_is_rendered_and_the_rendered_text_is_indexed(repo: Repository) -> None:
    renderer = FakeRenderer(rendered(*long_paragraphs("JS")))

    item = stored(repo, run(repo, fetched(html_page(TEASER)), renderer))

    assert renderer.urls == [URL]
    assert item.status is ItemStatus.READY
    assert item.extractor == "rendered"
    assert JS_TEXT in (item.extracted_text or "")
    assert item.title == "Rendered article"


def test_page_with_enough_text_is_not_rendered(repo: Repository) -> None:
    renderer = FakeRenderer(rendered("unused"))

    item = stored(repo, run(repo, fetched(html_page(*long_paragraphs("Plain"))), renderer))

    assert renderer.urls == []
    assert item.extractor in {"trafilatura", "fallback"}


def test_empty_page_is_rendered_instead_of_failing(repo: Repository) -> None:
    item = stored(
        repo, run(repo, fetched(SHELL_HTML), FakeRenderer(rendered(*long_paragraphs("JS"))))
    )

    assert item.status is ItemStatus.READY
    assert item.extractor == "rendered"


def test_without_a_renderer_an_empty_page_still_fails_as_empty(repo: Repository) -> None:
    item = stored(repo, run(repo, fetched(SHELL_HTML), None))

    assert item.status is ItemStatus.FAILED
    assert item.error_code is ItemErrorCode.EMPTY_CONTENT


def test_refused_render_of_an_empty_page_fails_with_a_clear_code(repo: Repository) -> None:
    refusal = IngestError(ItemErrorCode.SITE_BLOCKED, "The site refused automated access.")

    item = stored(repo, run(repo, fetched(SHELL_HTML), FakeRenderer(refusal)))

    assert item.status is ItemStatus.FAILED
    assert item.error_code is ItemErrorCode.SITE_BLOCKED


def test_failed_render_of_a_short_page_keeps_the_plain_text(repo: Repository) -> None:
    timeout = IngestError(ItemErrorCode.FETCH_TIMEOUT, "slow", retryable=True)

    item = stored(repo, run(repo, fetched(html_page(TEASER)), FakeRenderer(timeout)))

    assert item.status is ItemStatus.READY
    assert item.extractor != "rendered"
    assert TEASER in (item.extracted_text or "")


def test_rendered_page_with_less_text_is_ignored(repo: Repository) -> None:
    item = stored(repo, run(repo, fetched(html_page(TEASER)), FakeRenderer(rendered("Hi."))))

    assert item.extractor != "rendered"
    assert TEASER in (item.extracted_text or "")


def test_plain_text_pages_are_never_rendered(repo: Repository) -> None:
    renderer = FakeRenderer(rendered(*long_paragraphs("JS")))

    item = stored(repo, run(repo, fetched("Short plain text.", "text/plain"), renderer))

    assert renderer.urls == []
    assert item.extractor == "plain"


def test_render_timeout_is_retried_like_a_fetch_timeout(repo: Repository) -> None:
    timeout = IngestError(ItemErrorCode.FETCH_TIMEOUT, "slow", retryable=True)
    item = add_url(repo)
    service = IngestionService(
        repo,
        FakeEmbedder(TEST_DIM),
        StubFetcher(fetched(SHELL_HTML)),
        SETTINGS,
        FakeRenderer(timeout),
    )

    assert service.process(item.id).outcome is Outcome.RETRY


def test_render_off_starts_nothing(settings: Settings) -> None:
    assert asyncio.run(start_renderer(settings)) is None


def test_render_on_without_playwright_fails_startup_with_install_steps(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "app.services.browser_renderer", None)  # import fails
    app = create_app(settings.model_copy(update={"js_render": "on"}))

    with pytest.raises(RenderSetupError) as caught, TestClient(app):
        pass
    assert "uv sync --extra render" in str(caught.value)
    assert "playwright install chromium" in str(caught.value)
