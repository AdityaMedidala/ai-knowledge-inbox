from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.fetcher import Fetcher
from app.store.session import repository_session
from tests.support.dns import FakeResolver
from tests.support.http_pages import page
from tests.support.mock_http import MockRouter

ARTICLE = (Path(__file__).parents[1] / "fixtures" / "article.html").read_bytes()
ARTICLE_URL = "https://blog.example.com/posts/wal"
NOTE = "Groceries\n\nMilk, eggs and the good coffee from the market on Saturday morning."


@pytest.fixture
def drain(client: TestClient) -> Callable[[], None]:
    """Block until the app's worker has nothing queued, running or waiting to retry."""
    return lambda: client.portal.call(client.app.state.worker.drain, 10)  # type: ignore[attr-defined,union-attr]


def ingest(client: TestClient, **body: object):
    return client.post("/ingest", json=body)


def assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert body["error"]["code"] == code
    assert body["request_id"] == response.headers["x-request-id"]
    return body["error"]


# --- accepted -------------------------------------------------------------------------------


def test_note_is_accepted_then_processed_by_the_worker(
    client: TestClient, drain: Callable[[], None]
) -> None:
    response = ingest(client, type="note", content=f"  {NOTE}  ")
    assert response.status_code == 202
    item = response.json()["item"]
    assert response.headers["location"] == f"/items/{item['id']}"
    assert (item["type"], item["status"], item["title"]) == ("note", "pending", "Groceries")
    assert item["preview"].startswith("Groceries Milk, eggs")
    assert "raw_content" not in item

    drain()
    detail = client.get(f"/items/{item['id']}").json()
    assert (detail["status"], detail["chunk_count"], detail["error"]) == ("ready", 1, None)
    assert detail["extracted_text"] == NOTE
    assert "raw_content" not in detail


def test_explicit_note_title_wins(client: TestClient) -> None:
    item = ingest(client, type="note", content=NOTE, title="  Shopping  ").json()["item"]
    assert item["title"] == "Shopping"


def test_url_is_fetched_and_becomes_ready(
    client: TestClient, mock_http: MockRouter, drain: Callable[[], None]
) -> None:
    mock_http.add("GET", ARTICLE_URL, page(body=ARTICLE))
    response = ingest(client, type="url", url=ARTICLE_URL + "?utm_source=feed")
    assert response.status_code == 202
    item = response.json()["item"]
    assert (item["status"], item["preview"], item["title"]) == ("pending", None, None)

    drain()
    detail = client.get(f"/items/{item['id']}").json()
    assert detail["status"] == "ready"
    assert detail["title"] == "Write-Ahead Logging in SQLite"
    assert detail["chunk_count"] == 6
    assert detail["preview"].startswith("# Write-Ahead Logging")
    assert "raw_content" not in detail and "<html" not in str(detail)


def test_worker_side_failure_is_stored_on_the_item(
    settings: Settings, mock_http: MockRouter
) -> None:
    resolver = FakeResolver({"rebind.example": ["10.0.0.8"]})
    fetcher = Fetcher(mock_http.client(), timeout_s=5, max_bytes=10_000, max_redirects=3,
                      resolver=resolver)  # fmt: skip
    with TestClient(create_app(settings, fetcher=fetcher)) as client:
        item = ingest(client, type="url", url="https://rebind.example/x").json()["item"]
        client.portal.call(client.app.state.worker.drain, 10)  # type: ignore[union-attr]
        detail = client.get(f"/items/{item['id']}").json()
    assert detail["status"] == "failed"
    assert detail["error"]["code"] == "FETCH_BLOCKED"
    assert "private" in detail["error"]["message"]


def test_enqueue_failure_leaves_item_pending_for_startup_recovery(
    client: TestClient, settings: Settings
) -> None:
    client.portal.call(client.app.state.worker.stop)  # type: ignore[union-attr]
    response = ingest(client, type="note", content=NOTE)
    assert response.status_code == 202
    item_id = response.json()["item"]["id"]
    assert client.get(f"/items/{item_id}").json()["status"] == "pending"
    with repository_session(settings.db_path, settings.embedding_dim) as repo:
        assert repo.recover_interrupted() == [item_id]


# --- duplicates -----------------------------------------------------------------------------


def test_duplicate_url_returns_409_with_existing_item(
    client: TestClient, mock_http: MockRouter
) -> None:
    mock_http.add("GET", ARTICLE_URL, page(body=ARTICLE))
    first = ingest(client, type="url", url=ARTICLE_URL).json()["item"]
    again = ingest(client, type="url", url="HTTPS://Blog.Example.com/posts/wal/#comments")
    error = assert_error(again, 409, "DUPLICATE_ITEM")
    assert error["message"] == "This URL is already in your inbox."
    assert error["details"]["existing_id"] == first["id"]
    assert error["details"]["existing_status"] in {"pending", "processing", "ready"}


def test_duplicate_note_ignores_whitespace_differences(client: TestClient) -> None:
    first = ingest(client, type="note", content="Call   the dentist\non Tuesday").json()["item"]
    again = ingest(client, type="note", content="Call the dentist on Tuesday")
    error = assert_error(again, 409, "DUPLICATE_ITEM")
    assert error["details"]["existing_id"] == first["id"]
    assert error["message"] == "This note is already in your inbox."


# --- validation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        ({"content": "x"}, "body"),
        ({"type": "pdf", "content": "x"}, "body"),
        ({"type": "note", "content": "   "}, "body.note.content"),
        ({"type": "note", "content": "x", "title": "t" * 201}, "body.note.title"),
        ({"type": "note", "content": "x", "colour": "red"}, "body.note.colour"),
        ({"type": "url"}, "body.url.url"),
        ({"type": "url", "url": "https://e.com/" + "a" * 2048}, "body.url.url"),
    ],
)
def test_invalid_bodies_get_field_errors(client: TestClient, body: dict, loc: str) -> None:
    error = assert_error(client.post("/ingest", json=body), 422, "VALIDATION_ERROR")
    assert loc in [field["loc"] for field in error["details"]["fields"]]


def test_note_longer_than_configured_limit_is_rejected(settings: Settings) -> None:
    small = settings.model_copy(update={"note_max_chars": 10})
    with TestClient(create_app(small)) as client:
        error = assert_error(ingest(client, type="note", content="x" * 11), 422, "VALIDATION_ERROR")
    assert error["details"]["fields"][0]["loc"] == "body.content"


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("ftp://example.com/file", "scheme_not_allowed"),
        ("https://user:pass@example.com/", "credentials_in_url"),
        ("https://example.com:8080/", "port_not_allowed"),
        ("http://127.0.0.1/", "address_not_allowed"),
        ("http://169.254.169.254/latest/meta-data/", "address_not_allowed"),
        ("http://[::ffff:10.0.0.1]/", "address_not_allowed"),
        ("http://localhost:80/", "host_not_allowed"),
        ("http://nas.local/", "host_not_allowed"),
        ("http://metadata.google.internal/", "host_not_allowed"),
        ("http://router.home.arpa/", "host_not_allowed"),
        ("not a url", "scheme_not_allowed"),
    ],
)
def test_disallowed_urls_are_rejected_at_submit_time(
    client: TestClient, url: str, reason: str
) -> None:
    error = assert_error(ingest(client, type="url", url=url), 422, "URL_NOT_ALLOWED")
    assert error["details"] == {"reason": reason}
    assert client.get("/items").json()["items"] == []  # nothing was stored
