import sqlite3

import structlog
from fastapi import APIRouter, Response, status

from app.deps import SettingsDep
from app.schemas.health import HealthResponse
from app.store.db import connect, sqlite_vec_version

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unavailable"}},
)
def health(settings: SettingsDep, response: Response) -> HealthResponse:
    vec_version: str | None = None
    try:
        conn = connect(settings.db_path)
        try:
            vec_version = sqlite_vec_version(conn)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning("health.db_unavailable", error=str(exc))

    db_ok = vec_version is not None
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db="ok" if db_ok else "error",
        sqlite_vec_version=vec_version,
        embedding_provider=settings.embedding_provider,
        llm_provider=settings.llm_provider,
        demo_mode=settings.demo_mode == "on",
    )
