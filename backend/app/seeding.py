"""Demo items: a few notes plus the eval's web pages, replayed from saved snapshots (offline).

Used on startup when SEED_ON_EMPTY=on and the inbox is empty, and by `make seed`.
"""

import json
import threading
from pathlib import Path

import structlog

from app.config import Settings
from app.domain.errors import AppError
from app.domain.models import ItemType
from app.ingest_jobs import ingestion_settings
from app.providers.base import Embedder
from app.services.ingestion import IngestionService, Outcome
from app.services.snapshots import CorpusItem, SnapshotFetcher, load_items
from app.services.submission import SubmissionService
from app.store.session import repository_session

logger = structlog.get_logger(__name__)

SEED_NOTE_KEYS = ("wal", "async_notes", "sourdough", "coffee", "lisbon")  # every URL is added


def demo_items(seed_dir: Path) -> list[CorpusItem]:
    data = json.loads((seed_dir / "eval_set.json").read_text("utf-8"))
    return [item for item in load_items(data) if item.type == "url" or item.key in SEED_NOTE_KEYS]


def demo_fetcher(seed_dir: Path, items: list[CorpusItem]) -> SnapshotFetcher:
    return SnapshotFetcher(items, seed_dir / "corpus")


def seed_if_empty(settings: Settings, embedder: Embedder, stop: threading.Event) -> int:
    """Insert and index the demo items when the inbox has none; returns how many became ready.
    Runs synchronously (call it in a thread); checks `stop` between items. Never raises: a
    failed seed is logged and leaves the app running with whatever was indexed."""
    try:
        return _seed(settings, embedder, stop)
    except Exception:
        logger.exception("seed.failed")
        return 0


def _seed(settings: Settings, embedder: Embedder, stop: threading.Event) -> int:
    items = demo_items(settings.seed_dir)
    with repository_session(settings.db_path, settings.embedding_dim) as repo:
        if repo.stats().items > 0:
            logger.info("seed.skipped", reason="inbox_not_empty")
            return 0
        submission = SubmissionService(repo, note_max_chars=settings.note_max_chars)
        ids = [item_id for item in items if (item_id := _submit(submission, item))]
        service = IngestionService(
            repo,
            embedder,
            demo_fetcher(settings.seed_dir, items),
            ingestion_settings(settings, max_attempts=1),
        )
        ready = 0
        for item_id in ids:
            if stop.is_set():
                logger.info("seed.interrupted", remaining=len(ids) - ready)
                break
            ready += service.process(item_id).outcome is Outcome.READY
    logger.info("seed.done", items=len(ids), ready=ready)
    return ready


def _submit(submission: SubmissionService, item: CorpusItem) -> str | None:
    try:
        if item.type == ItemType.URL:
            assert item.url is not None  # noqa: S101 — url items always carry one
            return submission.submit_url(item.url).id
        assert item.content is not None  # noqa: S101 — note items always carry text
        return submission.submit_note(item.content, item.title).id
    except AppError as exc:  # a duplicate from a concurrent save; nothing to seed
        logger.info("seed.item_skipped", key=item.key, error_code=exc.code)
        return None
