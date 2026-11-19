"""Wiring for the ingestion worker: settings + shared providers -> per-job callables."""

from app.config import Settings
from app.providers.base import Embedder
from app.services.chunker import ChunkLimits
from app.services.ingestion import IngestionService, IngestionSettings, JobResult, PageFetcher
from app.services.renderer import PageRenderer
from app.store.session import repository_session
from app.worker import IngestionWorker, Recover, RunJob, exponential_backoff


def build_worker(
    settings: Settings,
    embedder: Embedder,
    fetcher: PageFetcher,
    renderer: PageRenderer | None = None,
) -> IngestionWorker:
    return IngestionWorker(
        _job_runner(settings, embedder, fetcher, renderer),
        _recoverer(settings),
        concurrency=settings.worker_concurrency,
        backoff=exponential_backoff(settings.ingest_retry_base_s),
    )


def _job_runner(
    settings: Settings, embedder: Embedder, fetcher: PageFetcher, renderer: PageRenderer | None
) -> RunJob:
    ingestion = ingestion_settings(settings)

    def run_job(item_id: str) -> JobResult:
        with repository_session(settings.db_path, settings.embedding_dim) as repo:
            return IngestionService(repo, embedder, fetcher, ingestion, renderer).process(item_id)

    return run_job


def ingestion_settings(settings: Settings, *, max_attempts: int | None = None) -> IngestionSettings:
    return IngestionSettings(
        limits=ChunkLimits(
            max_tokens=settings.chunk_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            max_block_tokens=settings.chunk_max_block_tokens,
        ),
        max_attempts=max_attempts or settings.ingest_max_attempts,
        render_min_chars=settings.render_min_chars,
    )


def _recoverer(settings: Settings) -> Recover:
    def recover() -> list[str]:
        with repository_session(settings.db_path, settings.embedding_dim) as repo:
            return repo.recover_interrupted()

    return recover
