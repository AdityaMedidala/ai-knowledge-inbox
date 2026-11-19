import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.domain.models import ItemStatus
from app.store.session import repository_session


def add_notes(client: TestClient, count: int) -> list[str]:
    ids = []
    for n in range(count):
        response = client.post("/ingest", json={"type": "note", "content": f"Note number {n}."})
        assert response.status_code == 202
        ids.append(response.json()["item"]["id"])
    return ids


def test_list_is_newest_first_with_keyset_pagination(client: TestClient) -> None:
    ids = add_notes(client, 5)
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = client.get("/items", params=params).json()
        seen += [item["id"] for item in body["items"]]
        pages += 1
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == list(reversed(ids))
    assert pages == 3


def test_list_items_shape_has_no_raw_content(client: TestClient) -> None:
    add_notes(client, 1)
    [item] = client.get("/items").json()["items"]
    assert set(item) == {
        "id", "type", "title", "source_url", "status", "error", "chunk_count",
        "created_at", "updated_at", "preview", "deletable",
    }  # fmt: skip


def test_filters_by_type_and_status(client: TestClient, settings: Settings) -> None:
    [first, second] = add_notes(client, 2)
    client.portal.call(client.app.state.worker.drain, 10)  # type: ignore[union-attr]
    assert {i["id"] for i in client.get("/items", params={"type": "note"}).json()["items"]} == {
        first,
        second,
    }
    assert client.get("/items", params={"type": "url"}).json()["items"] == []
    ready = client.get("/items", params={"status": "ready"}).json()["items"]
    assert {item["id"] for item in ready} == {first, second}
    assert client.get("/items", params={"status": "failed"}).json()["items"] == []


@pytest.mark.parametrize(
    ("params", "loc"),
    [
        ({"limit": 0}, "query.limit"),
        ({"limit": 101}, "query.limit"),
        ({"limit": "ten"}, "query.limit"),
        ({"status": "done"}, "query.status"),
        ({"type": "pdf"}, "query.type"),
        ({"cursor": "not-a-cursor"}, "query.cursor"),
        ({"cursor": "eyJ4IjoxfQ"}, "query.cursor"),  # valid base64 JSON, wrong shape
        ({"cursor": "a" * 300}, "query.cursor"),
    ],
)
def test_invalid_query_params_are_422(client: TestClient, params: dict, loc: str) -> None:
    response = client.get("/items", params=params)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert loc in [field["loc"] for field in error["details"]["fields"]]


def test_get_unknown_item_is_404(client: TestClient) -> None:
    response = client.get("/items/" + "0" * 32)
    assert response.status_code == 404
    assert response.json()["error"] == {
        "code": "NOT_FOUND",
        "message": "Item not found.",
        "details": None,
    }


def test_delete_returns_204_then_404(client: TestClient) -> None:
    [item_id] = add_notes(client, 1)
    response = client.delete(f"/items/{item_id}")
    assert (response.status_code, response.content) == (204, b"")
    assert client.get(f"/items/{item_id}").status_code == 404
    assert client.delete(f"/items/{item_id}").status_code == 404


def test_delete_works_while_processing(client: TestClient, settings: Settings) -> None:
    client.portal.call(client.app.state.worker.stop)  # type: ignore[union-attr]
    [item_id] = add_notes(client, 1)
    with repository_session(settings.db_path, settings.embedding_dim) as repo:
        repo.set_status(item_id, ItemStatus.PROCESSING)
    assert client.delete(f"/items/{item_id}").status_code == 204
    assert client.get(f"/items/{item_id}").status_code == 404


def test_stats_counts_all_items_and_ready_chunks(client: TestClient) -> None:
    assert client.get("/items/stats").json() == {"items": 0, "chunks": 0}
    add_notes(client, 2)
    client.portal.call(client.app.state.worker.drain, 10)  # type: ignore[union-attr]
    assert client.get("/items/stats").json() == {"items": 2, "chunks": 2}
