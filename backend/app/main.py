"""App factory. Run with: uvicorn app.main:create_app --factory"""

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, ingest, items, query
from app.config import Settings
from app.domain.errors import RenderSetupError
from app.errors import register_exception_handlers
from app.frontend import mount_frontend
from app.ingest_jobs import build_worker
from app.logging import configure_logging
from app.middleware import AccessLogMiddleware, UnhandledErrorMiddleware
from app.providers.base import Embedder
from app.providers.factory import build_providers
from app.rate_limit import SlidingWindowLimiter
from app.render_setup import start_renderer
from app.seeding import seed_if_empty
from app.services.fetcher import Fetcher, build_fetch_client
from app.services.ingestion import PageFetcher
from app.store.db import connect
from app.store.migrations import apply_migrations

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    try:
        apply_migrations(
            conn,
            embedding_model=settings.embedding_model,
            embedding_dim=settings.embedding_dim,
            db_label=str(settings.db_path),
        )
    finally:
        conn.close()
    logger.info(
        "app.startup",
        db_path=str(settings.db_path),
        embedding_provider=settings.embedding_provider,
        llm_provider=settings.llm_provider,
    )
    # Loading a local embedding model takes ~1s of CPU; keep it off the event loop.
    app.state.providers = await asyncio.to_thread(build_providers, settings)
    fetch_client = build_fetch_client()
    fetcher: PageFetcher = app.state.fetcher_override or Fetcher(
        fetch_client,
        timeout_s=settings.fetch_timeout_s,
        max_bytes=settings.fetch_max_bytes,
        max_redirects=settings.fetch_max_redirects,
    )
    try:
        renderer = await start_renderer(settings)
    except RenderSetupError as exc:
        logger.error("app.startup_failed", reason=str(exc))  # the one line to read in the logs
        fetch_client.close()
        app.state.providers.close()
        raise
    worker = build_worker(settings, app.state.providers.embedder, fetcher, renderer)
    await worker.start()
    app.state.worker = worker
    stop_seeding = threading.Event()
    seeding = _start_seeding(settings, app.state.providers.embedder, stop_seeding)
    try:
        yield
    finally:
        stop_seeding.set()
        if seeding is not None:
            await seeding  # finishes the item in progress, then stops
        await worker.stop()  # before closing what running jobs use
        if renderer is not None:
            await renderer.close()
        fetch_client.close()
        app.state.providers.close()
        logger.info("app.shutdown")


def _add_middleware(app: FastAPI, settings: Settings) -> None:
    """Request flow, outermost first (Starlette wraps in reverse order of add_middleware):

    ServerErrorMiddleware (Starlette; last resort, never reached in practice)
      -> CorrelationIdMiddleware   sets request_id contextvar + X-Request-ID on every response
      -> AccessLogMiddleware       one `http.request` line with final status and duration
      -> CORSMiddleware            CORS headers, including on our 500 responses
      -> UnhandledErrorMiddleware  uncaught exception -> logged stack + INTERNAL_ERROR envelope
      -> ExceptionMiddleware       AppError / HTTPException / RequestValidationError handlers
      -> router
    """
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Location"],
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(CorrelationIdMiddleware, header_name=REQUEST_ID_HEADER)


def create_app(settings: Settings | None = None, *, fetcher: PageFetcher | None = None) -> FastAPI:
    """`fetcher` replaces the real HTTP fetcher (tests serve pages from a mock transport)."""
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(title="AI Knowledge Inbox", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.fetcher_override = fetcher
    app.state.rate_limits = _rate_limits(settings)
    register_exception_handlers(app)
    _add_middleware(app, settings)
    app.include_router(health.router)
    app.include_router(ingest.router)
    app.include_router(items.router)
    app.include_router(query.router)
    if settings.frontend_dist is not None:
        mount_frontend(app, settings.frontend_dist)
    return app


def _rate_limits(settings: Settings) -> dict[str, SlidingWindowLimiter]:
    if settings.demo_mode == "off":
        return {}
    return {
        "ingest": SlidingWindowLimiter(settings.demo_ingests_per_hour),
        "query": SlidingWindowLimiter(settings.demo_queries_per_hour),
    }


def _start_seeding(
    settings: Settings, embedder: Embedder, stop: threading.Event
) -> asyncio.Task[int] | None:
    """SEED_ON_EMPTY=on: index the demo items in the background, so startup is not delayed."""
    if settings.seed_on_empty == "off":
        return None
    return asyncio.create_task(asyncio.to_thread(seed_if_empty, settings, embedder, stop))
