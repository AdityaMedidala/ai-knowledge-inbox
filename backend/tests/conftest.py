import io
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.stdlib import ProcessorFormatter

from app.config import Settings
from app.main import create_app

ALLOWED_ORIGIN = "http://localhost:5173"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        embedding_provider="fake",
        llm_provider="fake",
        db_path=tmp_path / "data" / "inbox.db",
        cors_origins=[ALLOWED_ORIGIN],
        log_json=True,
        log_level="INFO",
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def log_lines(app: FastAPI) -> Iterator[Callable[[], list[dict]]]:
    """Capture log output rendered by the app's own formatter; yield a JSON-lines reader."""
    root = logging.getLogger()
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    app_formatter = next(
        h.formatter for h in root.handlers if isinstance(h.formatter, ProcessorFormatter)
    )
    handler.setFormatter(app_formatter)
    root.addHandler(handler)

    def read() -> list[dict]:
        return [json.loads(line) for line in buffer.getvalue().splitlines()]

    yield read
    root.removeHandler(handler)
