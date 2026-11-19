"""Demo items: a few notes plus the eval's web pages, replayed from saved snapshots (offline).

Used on startup when SEED_ON_EMPTY=on and the inbox is empty, and by `make seed`.
"""

import json
import threading
from pathlib import Path

import structlog

from app.config import Settings
from app.domain.errors import AppError, DuplicateItemError
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
    """Outside demo mode: seed only an empty inbox. In demo mode: re-add any demo item that is
    missing (someone deleted it before deletes were blocked, or the set grew) and mark every demo
    item as seeded, which protects it from deletion."""
    items = demo_items(settings.seed_dir)
    restore = settings.demo_mode == "on"
    with repository_session(settings.db_path, settings.embedding_dim) as repo:
        if not restore and repo.stats().items > 0:
            logger.info("seed.skipped", reason="inbox_not_empty")
            return 0
        submission = SubmissionService(repo, note_max_chars=settings.note_max_chars)
        added = []
        for item in items:
            item_id, created = _submit_or_find(submission, item)
            if item_id is None:
                continue
            repo.mark_seeded(item_id)
            if created:
                added.append(item_id)
        service = IngestionService(
            repo,
            embedder,
            demo_fetcher(settings.seed_dir, items),
            ingestion_settings(settings, max_attempts=1),
        )
        ready = 0
        for item_id in added:
            if stop.is_set():
                logger.info("seed.interrupted", remaining=len(added) - ready)
                break
            ready += service.process(item_id).outcome is Outcome.READY
    logger.info("seed.done", added=len(added), ready=ready, demo_items=len(items))
    return ready


def _submit_or_find(submission: SubmissionService, item: CorpusItem) -> tuple[str | None, bool]:
    """(item id, whether it was just created). An existing copy is found via the duplicate check."""
    try:
        if item.type == ItemType.URL:
            assert item.url is not None  # noqa: S101 — url items always carry one
            return submission.submit_url(item.url).id, True
        assert item.content is not None  # noqa: S101 — note items always carry text
        return submission.submit_note(item.content, item.title).id, True
    except DuplicateItemError as exc:
        return str(exc.details["existing_id"]), False  # type: ignore[index]
    except AppError as exc:
        logger.warning("seed.item_skipped", key=item.key, error_code=exc.code)
        return None, False
