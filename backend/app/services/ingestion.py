"""One ingestion job: claim -> (fetch -> extract) -> chunk -> embed -> store, synchronously.

This service owns every status transition of a job and decides retry vs fail; the worker only
schedules. It never raises for an item-level problem: it returns an Outcome.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import structlog

from app.domain.errors import (
    IngestError,
    InvalidStatusTransitionError,
    ItemNotFoundError,
    ItemNotProcessingError,
    ProviderError,
)
from app.domain.models import Item, ItemErrorCode, ItemStatus, ItemType
from app.providers.base import Embedder
from app.services.chunker import ChunkLimits, build_embed_text, chunk_document
from app.services.fetcher import FetchedPage
from app.services.renderer import PageRenderer, extract_with_fallback
from app.store.repository import Repository
from app.utils.text import sha256_hex
from app.utils.timing import Timer
from app.utils.urls import redact_url

logger = structlog.get_logger(__name__)


class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...


class Outcome(StrEnum):
    READY = "ready"
    RETRY = "retry"  # back to 'pending'; the worker re-enqueues after a backoff
    FAILED = "failed"
    ALREADY_CLAIMED = "already_claimed"  # another job got it first
    VANISHED = "vanished"  # deleted (or moved on) while we worked


@dataclass(frozen=True, slots=True)
class JobResult:
    outcome: Outcome
    attempt: int = 0


@dataclass(frozen=True, slots=True)
class IngestionSettings:
    limits: ChunkLimits
    max_attempts: int
    render_min_chars: int = 500  # only used with a renderer


class IngestionService:
    def __init__(
        self,
        repo: Repository,
        embedder: Embedder,
        fetcher: PageFetcher,
        settings: IngestionSettings,
        renderer: PageRenderer | None = None,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        self._fetcher = fetcher
        self._settings = settings
        self._renderer = renderer

    def process(self, item_id: str) -> JobResult:
        item = self._claim(item_id)
        if isinstance(item, Outcome):
            return JobResult(item)
        with structlog.contextvars.bound_contextvars(attempt=item.attempts):
            try:
                self._run(item)
            except (ItemNotProcessingError, ItemNotFoundError, InvalidStatusTransitionError):
                return self._vanished(item)
            except IngestError as exc:
                return self._fail_or_retry(item, exc.code, exc.message, exc.retryable)
            except ProviderError as exc:
                message = f"The embedding provider failed ({exc.kind}). Try again later."
                return self._fail_or_retry(
                    item, ItemErrorCode.EMBEDDING_FAILED, message, exc.retryable
                )
            except Exception:
                logger.exception("ingest.unexpected_error")
                message = f"Unexpected error while processing; quote item id {item.id}."
                return self._fail_or_retry(item, ItemErrorCode.INTERNAL_ERROR, message, False)
            logger.info("ingest.ready")
            return JobResult(Outcome.READY, item.attempts)

    def _claim(self, item_id: str) -> Item | Outcome:
        try:
            self._repo.set_status(item_id, ItemStatus.PROCESSING)
        except ItemNotFoundError:
            logger.info("ingest.item_vanished", stage="claim")
            return Outcome.VANISHED
        except InvalidStatusTransitionError as exc:
            logger.debug("ingest.already_claimed", current=exc.current)
            return Outcome.ALREADY_CLAIMED
        item = self._repo.get_item(item_id)
        if item is None:
            logger.info("ingest.item_vanished", stage="claim")
            return Outcome.VANISHED
        return item

    def _run(self, item: Item) -> None:
        title, text = self._content(item)
        chunks = chunk_document(text, title=title, limits=self._settings.limits)
        if not chunks:
            raise IngestError(ItemErrorCode.EMPTY_CONTENT, "The item has no text to index.")
        logger.info("ingest.chunked", chunks=len(chunks), tokens=sum(c.token_count for c in chunks))
        with Timer() as timer:
            embeddings = self._embedder.embed_documents([build_embed_text(c) for c in chunks])
        logger.info("ingest.embedded", ms=timer.ms)
        self._repo.replace_chunks(item.id, chunks, embeddings)

    def _content(self, item: Item) -> tuple[str | None, str]:
        """(title, markdown) to chunk. Notes already carry their text from submission."""
        if item.type is ItemType.NOTE:
            return item.title, item.extracted_text or item.raw_content or ""
        assert item.source_url is not None  # noqa: S101 — URL items always have one
        with Timer() as timer:
            page = self._fetcher.fetch(item.source_url)
        logger.info(
            "ingest.fetched",
            url=redact_url(page.final_url),
            bytes=len(page.body),
            http_status=page.http_status,
            redirects=page.redirects,
            ms=timer.ms,
        )
        doc = extract_with_fallback(page, self._renderer, self._settings.render_min_chars)
        logger.info(
            "ingest.extracted", chars=len(doc.text), title=doc.title, extractor=doc.extractor
        )
        self._repo.set_content(
            item.id,
            title=doc.title,
            extracted_text=doc.text,
            content_hash=sha256_hex(doc.text),
            raw_content=doc.raw_content,
            extractor=doc.extractor,
        )
        return doc.title, doc.text

    def _fail_or_retry(
        self, item: Item, code: ItemErrorCode, message: str, retryable: bool
    ) -> JobResult:
        try:
            if retryable and item.attempts < self._settings.max_attempts:
                self._repo.set_status(item.id, ItemStatus.PENDING)
                logger.info("ingest.retry_scheduled", error_code=code)
                return JobResult(Outcome.RETRY, item.attempts)
            self._repo.set_status(
                item.id, ItemStatus.FAILED, error_code=code, error_message=message
            )
        except (ItemNotFoundError, InvalidStatusTransitionError):
            return self._vanished(item)
        logger.warning("ingest.failed", error_code=code, retryable=retryable)
        return JobResult(Outcome.FAILED, item.attempts)

    def _vanished(self, item: Item) -> JobResult:
        logger.info("ingest.item_vanished", stage="process")
        return JobResult(Outcome.VANISHED, item.attempts)
