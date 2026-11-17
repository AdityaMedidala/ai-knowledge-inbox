from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from structlog.contextvars import merge_contextvars
from structlog.testing import capture_logs

from app.domain.errors import IngestError, ProviderError, ProviderErrorKind
from app.domain.models import Item, ItemErrorCode, ItemStatus, ItemType, NewItem
from app.providers.fakes import FakeEmbedder
from app.services.chunker import ChunkLimits
from app.services.fetcher import FetchedPage
from app.services.ingestion import IngestionService, IngestionSettings, JobResult, Outcome
from app.store.repository import Repository
from app.utils.text import sha256_hex
from tests.conftest import TEST_DIM

ARTICLE = (Path(__file__).parents[1] / "fixtures" / "article.html").read_bytes()
URL = "https://blog.example.com/posts/wal?session=SECRET"
SETTINGS = IngestionSettings(limits=ChunkLimits(350, 60, 400), max_attempts=3)


class StubFetcher:
    def __init__(
        self, *results: FetchedPage | Exception, on_fetch: Callable[[], None] | None = None
    ):
        self.results = list(results)
        self.on_fetch = on_fetch
        self.urls: list[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.urls.append(url)
        if self.on_fetch:
            self.on_fetch()
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result


class FailingEmbedder:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise self.error

    def embed_query(self, text: str) -> list[float]:
        raise self.error


def article_page() -> FetchedPage:
    return FetchedPage(URL, 200, "text/html", "utf-8", ARTICLE, 0)


def service(
    repo: Repository, fetcher: StubFetcher | None = None, embedder=None
) -> IngestionService:
    return IngestionService(
        repo, embedder or FakeEmbedder(TEST_DIM), fetcher or StubFetcher(article_page()), SETTINGS
    )


def add_note(repo: Repository, text: str = "Remember: WAL lets readers run during writes.") -> Item:
    return repo.create_item(
        NewItem(
            type=ItemType.NOTE,
            title="WAL note",
            content_hash=sha256_hex(text),
            raw_content=text,
            extracted_text=text,
        )
    )


def add_url(repo: Repository) -> Item:
    return repo.create_item(NewItem(type=ItemType.URL, source_url=URL, normalized_url=URL))


def stored(repo: Repository, item_id: str) -> Item:
    item = repo.get_item(item_id)
    assert item is not None
    return item


# --- success paths --------------------------------------------------------------------------


def test_note_becomes_ready_without_fetching(repo: Repository) -> None:
    fetcher = StubFetcher(RuntimeError("must not fetch notes"))
    item = add_note(repo)
    assert service(repo, fetcher).process(item.id) == JobResult(Outcome.READY, 1)
    ready = stored(repo, item.id)
    assert (ready.status, ready.chunk_count, ready.attempts) == (ItemStatus.READY, 1, 1)
    assert fetcher.urls == []


def test_url_is_fetched_extracted_and_indexed(repo: Repository) -> None:
    item = add_url(repo)
    assert service(repo).process(item.id).outcome is Outcome.READY
    ready = stored(repo, item.id)
    assert ready.title == "Write-Ahead Logging in SQLite"
    assert ready.extracted_text is not None and "## How WAL mode works" in ready.extracted_text
    assert ready.content_hash == sha256_hex(ready.extracted_text)
    assert ready.raw_content == ARTICLE.decode()
    assert ready.chunk_count == 6
    assert repo.keyword_search("checkpoint", 5)  # chunks are searchable


def test_stage_logs_are_emitted_without_secrets_or_text(repo: Repository) -> None:
    item = add_url(repo)
    with capture_logs(processors=[merge_contextvars]) as logs:
        service(repo).process(item.id)
    events = [line["event"] for line in logs]
    assert events == ["ingest.fetched", "ingest.extracted", "ingest.chunked", "ingest.embedded",
                      "ingest.ready"]  # fmt: skip
    fetched = logs[0]
    assert fetched["url"] == "https://blog.example.com/posts/wal"
    assert fetched["bytes"] == len(ARTICLE) and fetched["http_status"] == 200
    assert all(line.get("attempt") == 1 for line in logs)
    assert "SECRET" not in repr(logs) and "checkpoint that copies" not in repr(logs)


# --- failures and retries -------------------------------------------------------------------


def test_permanent_error_fails_immediately(repo: Repository) -> None:
    item = add_url(repo)
    error = IngestError(ItemErrorCode.UNSUPPORTED_CONTENT, "Only HTML.")
    assert service(repo, StubFetcher(error)).process(item.id) == JobResult(Outcome.FAILED, 1)
    failed = stored(repo, item.id)
    assert (failed.status, failed.error_code, failed.error_message) == (
        ItemStatus.FAILED,
        ItemErrorCode.UNSUPPORTED_CONTENT,
        "Only HTML.",
    )


def test_transient_error_retries_then_fails_with_last_code(repo: Repository) -> None:
    item = add_url(repo)
    timeout = IngestError(ItemErrorCode.FETCH_TIMEOUT, "Slow.", retryable=True)
    svc = service(repo, StubFetcher(timeout))
    assert svc.process(item.id) == JobResult(Outcome.RETRY, 1)
    assert stored(repo, item.id).status is ItemStatus.PENDING
    assert svc.process(item.id) == JobResult(Outcome.RETRY, 2)
    with capture_logs(processors=[merge_contextvars]) as logs:
        assert svc.process(item.id) == JobResult(Outcome.FAILED, 3)
    failed = stored(repo, item.id)
    assert (failed.status, failed.error_code, failed.attempts) == (
        ItemStatus.FAILED,
        ItemErrorCode.FETCH_TIMEOUT,
        3,
    )
    [line] = [entry for entry in logs if entry["event"] == "ingest.failed"]
    assert (line["error_code"], line["attempt"]) == (ItemErrorCode.FETCH_TIMEOUT, 3)


def test_retry_succeeds_on_second_attempt(repo: Repository) -> None:
    item = add_url(repo)
    flaky = StubFetcher(
        IngestError(ItemErrorCode.FETCH_FAILED, "503", retryable=True), article_page()
    )
    svc = service(repo, flaky)
    assert svc.process(item.id).outcome is Outcome.RETRY
    assert svc.process(item.id) == JobResult(Outcome.READY, 2)


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (ProviderError(ProviderErrorKind.UNAVAILABLE, "fastembed", "down"), Outcome.RETRY),
        (ProviderError(ProviderErrorKind.RATE_LIMITED, "openai", "quota", retryable=False),
         Outcome.FAILED),
        (ProviderError(ProviderErrorKind.AUTH, "openai", "bad key"), Outcome.FAILED),
    ],
)  # fmt: skip
def test_provider_errors_become_embedding_failed(
    repo: Repository, error: ProviderError, outcome: Outcome
) -> None:
    item = add_note(repo)
    assert service(repo, embedder=FailingEmbedder(error)).process(item.id).outcome is outcome
    after = stored(repo, item.id)
    if outcome is Outcome.FAILED:
        assert after.error_code is ItemErrorCode.EMBEDDING_FAILED
        assert "quota" not in (after.error_message or "")  # provider detail stays in logs


def test_unexpected_exception_marks_item_failed_instead_of_stuck(repo: Repository) -> None:
    item = add_url(repo)
    with capture_logs(processors=[merge_contextvars]) as logs:
        result = service(repo, StubFetcher(KeyError("bug"))).process(item.id)
    assert result.outcome is Outcome.FAILED
    assert stored(repo, item.id).error_code is ItemErrorCode.INTERNAL_ERROR
    assert any(line["event"] == "ingest.unexpected_error" for line in logs)


# --- races ----------------------------------------------------------------------------------


def test_already_claimed_item_is_dropped(repo: Repository) -> None:
    item = add_note(repo)
    repo.set_status(item.id, ItemStatus.PROCESSING)
    with capture_logs(processors=[merge_contextvars]) as logs:
        assert service(repo).process(item.id).outcome is Outcome.ALREADY_CLAIMED
    assert [line["event"] for line in logs] == ["ingest.already_claimed"]
    assert stored(repo, item.id).attempts == 1  # untouched


def test_missing_item_is_vanished(repo: Repository) -> None:
    assert service(repo).process("0" * 32).outcome is Outcome.VANISHED


def test_item_deleted_mid_job_is_dropped_not_failed(repo: Repository) -> None:
    item = add_url(repo)
    fetcher = StubFetcher(article_page(), on_fetch=lambda: repo.delete_item(item.id))
    with capture_logs(processors=[merge_contextvars]) as logs:
        assert service(repo, fetcher).process(item.id).outcome is Outcome.VANISHED
    events = [line["event"] for line in logs]
    assert "ingest.item_vanished" in events and "ingest.failed" not in events
    assert repo.get_item(item.id) is None


def test_item_deleted_before_failure_is_recorded_is_dropped(repo: Repository) -> None:
    item = add_url(repo)

    def delete_then_fail() -> None:
        repo.delete_item(item.id)
        raise IngestError(ItemErrorCode.FETCH_BLOCKED, "Blocked.")

    fetcher = StubFetcher(article_page(), on_fetch=delete_then_fail)
    assert service(repo, fetcher).process(item.id).outcome is Outcome.VANISHED
