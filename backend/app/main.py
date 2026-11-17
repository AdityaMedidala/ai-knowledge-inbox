"""App factory. Run with: uvicorn app.main:create_app --factory"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.config import Settings
from app.errors import register_exception_handlers
from app.logging import configure_logging
from app.middleware import AccessLogMiddleware, UnhandledErrorMiddleware
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
    yield
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(title="AI Knowledge Inbox", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    register_exception_handlers(app)
    _add_middleware(app, settings)
    app.include_router(health.router)
    return app
