import io
import json
import logging
import os
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.stdlib import ProcessorFormatter

from app.config import Settings
from app.domain.models import Item, ItemStatus, ItemType, NewChunk, NewItem
from app.main import create_app
from app.store.db import connect
from app.store.migrations import apply_migrations
from app.store.repository import Repository
from tests.support.mock_http import MockRouter, mock_router_fixture
from tests.support.network_guard import NetworkGuard

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


# --- store fixtures -------------------------------------------------------------------------

TEST_DIM = 4
TEST_MODEL = "fake-embedding"


class FakeClock:
    """Deterministic clock: each call returns the current time, then advances by `step`."""

    def __init__(self, start: datetime | None = None, step: timedelta = timedelta(seconds=1)):
        self.now = start or datetime(2026, 1, 1, tzinfo=UTC)
        self.step = step

    def __call__(self) -> datetime:
        current = self.now
        self.now += self.step
        return current


@pytest.fixture
def db_conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(tmp_path / "store.db")
    apply_migrations(conn, embedding_model=TEST_MODEL, embedding_dim=TEST_DIM, db_label="test")
    yield conn
    conn.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repo(db_conn: sqlite3.Connection, clock: FakeClock) -> Repository:
    return Repository(db_conn, embedding_dim=TEST_DIM, clock=clock)


def make_note(repo: Repository, text: str = "a note", **overrides: object) -> Item:
    fields = {"type": ItemType.NOTE, "content_hash": f"hash-{text}", "raw_content": text}
    fields.update(overrides)
    return repo.create_item(NewItem(**fields))  # type: ignore[arg-type]


def make_chunk(ordinal: int, text: str, header: str = "Title: t\nSection: s") -> NewChunk:
    return NewChunk(
        ordinal=ordinal, section="s", context_header=header, text=text, token_count=len(text)
    )


def make_ready(
    repo: Repository, texts_and_vectors: list[tuple[str, list[float]]], **item_fields: object
) -> Item:
    item = make_note(repo, texts_and_vectors[0][0], **item_fields)
    repo.set_status(item.id, ItemStatus.PROCESSING)
    chunks = [make_chunk(i, text) for i, (text, _) in enumerate(texts_and_vectors)]
    repo.replace_chunks(item.id, chunks, [vec for _, vec in texts_and_vectors])
    ready = repo.get_item(item.id)
    assert ready is not None
    return ready


def pytest_configure() -> None:
    # Same persistent cache `make install` warms, so tiktoken never hits the network in tests.
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(__file__).parents[1] / ".cache/tiktoken"))


@pytest.fixture(autouse=True)
def network_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[NetworkGuard]:
    """No real network in tests. Fails at teardown too, in case an SDK swallowed the error."""
    guard = NetworkGuard()
    guard.install(monkeypatch)
    yield guard
    if guard.blocked:
        pytest.fail(f"Test attempted network access: {guard.blocked}")


@pytest.fixture
def mock_http() -> Iterator[MockRouter]:
    yield from mock_router_fixture()
