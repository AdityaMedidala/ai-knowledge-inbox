from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import ALLOWED_ORIGIN


def test_health_reports_db_and_providers(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["sqlite_vec_version"].startswith("v")
    assert body["embedding_provider"] == "fake"
    assert body["llm_provider"] == "fake"


def test_health_degrades_with_503_when_db_cannot_open(tmp_path: Path) -> None:
    unopenable = tmp_path / "is-a-directory.db"
    unopenable.mkdir()
    settings = Settings(
        _env_file=None, embedding_provider="fake", llm_provider="fake", db_path=unopenable
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 503
    assert response.json()["db"] == "error"
    assert response.json()["sqlite_vec_version"] is None


def test_lifespan_creates_db_parent_dir(app: FastAPI, settings: Settings) -> None:
    assert not settings.db_path.parent.exists()
    with TestClient(app):
        assert settings.db_path.parent.is_dir()


def test_request_id_generated_when_absent(client: TestClient) -> None:
    response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert int(request_id, 16) >= 0


def test_valid_incoming_request_id_is_echoed(client: TestClient) -> None:
    incoming = uuid4().hex

    response = client.get("/health", headers={"X-Request-ID": incoming})

    assert response.headers["X-Request-ID"] == incoming


def test_invalid_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "not-a-uuid; injected"})

    assert response.headers["X-Request-ID"] != "not-a-uuid; injected"


def test_access_log_line_carries_request_id(
    client: TestClient, log_lines: Callable[[], list[dict]]
) -> None:
    response = client.get("/health")

    access = [line for line in log_lines() if line["event"] == "http.request"]
    assert access[-1]["request_id"] == response.headers["X-Request-ID"]
    assert access[-1]["status"] == 200
    assert access[-1]["path"] == "/health"
    assert "duration_ms" in access[-1]


@pytest.mark.parametrize(
    ("origin", "allowed"), [(ALLOWED_ORIGIN, True), ("https://evil.example", False)]
)
def test_cors_allows_only_configured_origins(
    client: TestClient, origin: str, allowed: bool
) -> None:
    response = client.get("/health", headers={"Origin": origin})

    assert ("access-control-allow-origin" in response.headers) is allowed
    if allowed:
        assert "X-Request-ID" in response.headers["access-control-expose-headers"]
