"""Single-container features: serving the frontend, the demo seed, and demo-mode limits."""

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.rate_limit import SlidingWindowLimiter
from app.seeding import SEED_NOTE_KEYS, seed_if_empty
from app.store.db import connect
from app.store.session import repository_session

DEMO_ITEMS = len(SEED_NOTE_KEYS) + 4  # the notes plus the 4 eval web pages


def note(n: int) -> dict:
    return {"type": "note", "content": f"Demo note number {n}."}


# --- frontend -------------------------------------------------------------------------------


def test_built_frontend_and_api_share_one_origin(settings: Settings, tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Inbox</title>")
    app = create_app(settings.model_copy(update={"frontend_dist": dist}))

    with TestClient(app) as client:
        assert "<title>Inbox</title>" in client.get("/").text
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/health").status_code == 200  # still served at the root
        assert client.post("/api/ingest", json=note(1)).status_code == 202
        assert client.get("/api/items").json()["items"]


def test_missing_frontend_build_fails_at_startup(settings: Settings, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match=r"no index\.html"):
        create_app(settings.model_copy(update={"frontend_dist": tmp_path / "nope"}))


# --- seed -----------------------------------------------------------------------------------


def test_seed_fills_an_empty_inbox_once(client: TestClient, settings: Settings) -> None:
    embedder = client.app.state.providers.embedder  # type: ignore[union-attr]

    assert seed_if_empty(settings, embedder, threading.Event()) == DEMO_ITEMS
    items = client.get("/items", params={"limit": 50}).json()["items"]
    assert len(items) == DEMO_ITEMS
    assert {item["status"] for item in items} == {"ready"}
    assert sum(item["type"] == "url" for item in items) == 4

    assert seed_if_empty(settings, embedder, threading.Event()) == 0


def test_seed_stops_between_items_when_asked(client: TestClient, settings: Settings) -> None:
    stop = threading.Event()
    stop.set()
    embedder = client.app.state.providers.embedder  # type: ignore[union-attr]

    assert seed_if_empty(settings, embedder, stop) == 0


def test_seed_on_empty_runs_in_the_background_at_startup(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"seed_on_empty": "on"}))
    with TestClient(app) as client:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            items = client.get("/items", params={"limit": 50}).json()["items"]
            if len(items) == DEMO_ITEMS and all(i["status"] == "ready" for i in items):
                break
            time.sleep(0.1)
        assert client.get("/items/stats").json()["items"] == DEMO_ITEMS


# --- demo mode ------------------------------------------------------------------------------


def no_demo_items(settings: Settings) -> Path:
    """A seed directory with an empty demo set, so limit tests start from an empty inbox."""
    seed_dir = settings.data_dir.parent / "empty-seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "eval_set.json").write_text('{"items": [], "questions": []}')
    return seed_dir


def demo(settings: Settings, **limits: int) -> TestClient:
    update = {"demo_mode": "on", "seed_dir": no_demo_items(settings), **limits}
    return TestClient(create_app(settings.model_copy(update=update)))


def test_sliding_window_frees_a_slot_once_the_oldest_hit_expires() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(2, window_s=60, clock=lambda: now[0])
    assert limiter.acquire("a") is None
    assert limiter.acquire("a") is None
    assert limiter.acquire("a") == 60
    assert limiter.acquire("b") is None  # per client
    now[0] = 60.0
    assert limiter.acquire("a") is None


def test_demo_rate_limits_saves_with_a_clear_429(settings: Settings) -> None:
    with demo(settings, demo_ingests_per_hour=2) as client:
        assert [client.post("/ingest", json=note(n)).status_code for n in range(2)] == [202, 202]
        response = client.post("/ingest", json=note(3))

    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "2 saves per hour" in body["error"]["message"]
    assert int(response.headers["Retry-After"]) > 0


def test_demo_rate_limits_questions(settings: Settings) -> None:
    with demo(settings, demo_queries_per_hour=1) as client:
        assert client.post("/query", json={"question": "anything?"}).status_code == 200
        response = client.post("/query/stream", json={"question": "anything?"})

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_demo_item_cap_is_a_clear_409(settings: Settings) -> None:
    with demo(settings, demo_max_items=1) as client:
        assert client.post("/ingest", json=note(1)).status_code == 202
        duplicate = client.post("/ingest", json=note(1))
        full = client.post("/ingest", json=note(2))

    assert duplicate.json()["error"]["code"] == "DUPLICATE_ITEM"  # the more useful answer
    assert full.status_code == 409
    assert full.json()["error"]["code"] == "INBOX_FULL"
    assert "full (1 items)" in full.json()["error"]["message"]


def test_health_reports_demo_mode(settings: Settings) -> None:
    with demo(settings) as client:
        assert client.get("/health").json()["demo_mode"] is True


def test_without_demo_mode_there_are_no_limits(client: TestClient) -> None:
    codes = {client.post("/ingest", json=note(n)).status_code for n in range(15)}
    assert codes == {202}
    assert client.get("/health").json()["demo_mode"] is False


def test_rate_limit_keys_on_the_proxy_appended_address(settings: Settings) -> None:
    with demo(settings, demo_ingests_per_hour=1) as client:
        first = client.post(
            "/ingest", json=note(1), headers={"X-Forwarded-For": "6.6.6.6, 1.2.3.4"}
        )
        # Spoofing a new left-most address does not reset the limit for 1.2.3.4.
        spoofed = client.post(
            "/ingest", json=note(2), headers={"X-Forwarded-For": "7.7.7.7, 1.2.3.4"}
        )
        other = client.post("/ingest", json=note(3), headers={"X-Forwarded-For": "5.6.7.8"})

    assert (first.status_code, spoofed.status_code, other.status_code) == (202, 429, 202)


# --- protected demo items -------------------------------------------------------------------


def wait_for_demo_items(client: TestClient) -> list[dict]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        items = client.get("/items", params={"limit": 50}).json()["items"]
        seeded = [i for i in items if not i["deletable"]]
        if len(seeded) == DEMO_ITEMS and all(i["status"] == "ready" for i in seeded):
            return items
        time.sleep(0.1)
    raise AssertionError("demo items were not seeded in time")


def test_demo_items_cannot_be_deleted_but_your_own_can(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"demo_mode": "on"}))
    with TestClient(app) as client:
        demo_item = wait_for_demo_items(client)[0]
        own = client.post("/ingest", json=note(1)).json()["item"]

        refused = client.delete(f"/items/{demo_item['id']}")
        assert own["deletable"] is True
        assert client.delete(f"/items/{own['id']}").status_code == 204

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "ITEM_PROTECTED"
    assert "can't be deleted" in refused.json()["error"]["message"]


def test_demo_mode_restores_missing_demo_items_on_startup(settings: Settings) -> None:
    on = settings.model_copy(update={"demo_mode": "on"})
    with TestClient(create_app(on)) as client:
        gone = wait_for_demo_items(client)[0]
    with repository_session(on.db_path, on.embedding_dim) as repo:  # deleted before protection
        repo.delete_item(gone["id"])

    with TestClient(create_app(on)) as client:
        items = wait_for_demo_items(client)

    assert gone["title"] in {i["title"] for i in items}
    assert len(items) == DEMO_ITEMS


def test_demo_items_seeded_before_protection_are_marked(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        seed_if_empty(settings, client.app.state.providers.embedder, threading.Event())  # type: ignore[union-attr]
    conn = connect(settings.db_path)  # an older deploy: the seeded column did not exist yet
    conn.execute("UPDATE items SET seeded = 0")
    conn.close()

    with TestClient(create_app(settings.model_copy(update={"demo_mode": "on"}))) as client:
        items = wait_for_demo_items(client)

    assert len(items) == DEMO_ITEMS
