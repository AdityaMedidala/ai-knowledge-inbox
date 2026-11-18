import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.providers.fakes import FakeChatModel, FakeChatScript
from app.services.answering import NOT_FOUND_ANSWER

NOTES = {
    "sourdough": "Sourdough starter\n\nFeed the sourdough starter twice a day with equal parts "
    "flour and water.",
    "bike": "Bike maintenance\n\nOil the bike chain every 300 kilometres and check tyre "
    "pressure weekly.",
    "tax": "Tax deadline\n\nThe quarterly tax payment is due on the fifteenth of January.",
}
BIKE_QUESTION = "When should I oil the bike chain?"
OFF_TOPIC = "What is the capital of Peru?"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    """FakeEmbedder similarities: ~0.58 for the bike question vs the bike note, ~0 otherwise."""
    return settings.model_copy(update={"relevance_min_full": 0.5, "relevance_min_partial": 0.3})


@pytest.fixture
def chat(client: TestClient) -> FakeChatModel:
    return client.app.state.providers.chat  # type: ignore[attr-defined]


@pytest.fixture
def item_ids(client: TestClient) -> dict[str, str]:
    ids = {
        name: client.post("/ingest", json={"type": "note", "content": text}).json()["item"]["id"]
        for name, text in NOTES.items()
    }
    client.portal.call(client.app.state.worker.drain, 10)  # type: ignore[attr-defined,union-attr]
    return ids


def ask(client: TestClient, question: str, **extra: object):
    return client.post("/query", json={"question": question, **extra})


def stream_events(client: TestClient, question: str) -> list[tuple[str, dict]]:
    response = client.post("/query/stream", json={"question": question})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


# --- POST /query ----------------------------------------------------------------------------


def test_query_cites_the_matching_item(
    client: TestClient, item_ids: dict[str, str], chat: FakeChatModel
) -> None:
    response = ask(client, BIKE_QUESTION)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "full"
    assert body["request_id"] == response.headers["x-request-id"]
    assert body["debug"] is None
    assert body["verification"] is None  # VERIFIER=off by default
    assert "[1]" in body["answer"]
    first = body["citations"][0]
    assert (first["ref"], first["item_id"], first["item_type"]) == (1, item_ids["bike"], "note")
    assert first["title"] == "Bike maintenance"
    assert first["snippet"].startswith("Bike maintenance Oil the bike chain")
    assert first["score"] > 0.5
    assert set(body["timings_ms"]) == {"embed", "retrieve", "rerank", "generate", "total"}
    assert len(chat.calls) == 1


def test_debug_lists_candidates_with_score_breakdown(
    client: TestClient, item_ids: dict[str, str]
) -> None:
    candidates = ask(client, BIKE_QUESTION, debug=True).json()["debug"]["candidates"]
    assert candidates
    top = candidates[0]
    assert set(top) == {"chunk_id", "vec_rank", "fts_rank", "rrf", "similarity", "rerank"}
    assert top["vec_rank"] == 1 and top["fts_rank"] == 1


def test_off_topic_question_is_mode_none_without_calling_the_llm(
    client: TestClient, item_ids: dict[str, str], chat: FakeChatModel
) -> None:
    body = ask(client, OFF_TOPIC).json()
    assert (body["mode"], body["answer"], body["citations"]) == ("none", NOT_FOUND_ANSWER, [])
    assert body["timings_ms"]["generate"] == 0
    assert chat.calls == []


def test_empty_inbox_is_mode_none(client: TestClient, chat: FakeChatModel) -> None:
    body = ask(client, BIKE_QUESTION).json()
    assert (body["mode"], body["citations"]) == ("none", [])
    assert chat.calls == []


def test_invalid_citation_ids_are_dropped(
    client: TestClient, item_ids: dict[str, str], chat: FakeChatModel
) -> None:
    chat.script = FakeChatScript.CITE_INVALID
    body = ask(client, BIKE_QUESTION).json()
    assert "[9]" in body["answer"]
    assert body["citations"] == []


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "   "},
        {"question": "ok", "top_k": 0},
        {"question": "ok", "top_k": 11},
        {"question": "ok", "extra": 1},
        {},
    ],
)
def test_invalid_query_body_is_422(client: TestClient, payload: dict) -> None:
    response = client.post("/query", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_question_over_the_limit_is_422_with_field(client: TestClient) -> None:
    for path in ("/query", "/query/stream"):
        response = client.post(path, json={"question": "x" * 1001})
        assert response.status_code == 422
        fields = response.json()["error"]["details"]["fields"]
        assert fields[0]["loc"] == "body.question"


def test_llm_down_is_503_envelope(
    client: TestClient, item_ids: dict[str, str], chat: FakeChatModel
) -> None:
    chat.script = FakeChatScript.FAIL_RETRYABLE
    response = ask(client, BIKE_QUESTION)
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert body["request_id"] == response.headers["x-request-id"]


# --- POST /query/stream ---------------------------------------------------------------------


def test_stream_sends_meta_sources_tokens_done_in_order(
    client: TestClient, item_ids: dict[str, str]
) -> None:
    events = stream_events(client, BIKE_QUESTION)
    names = [name for name, _ in events]

    assert names[:2] == ["meta", "sources"]
    assert names[-1] == "done"
    assert "verification" not in names  # VERIFIER=off by default
    assert set(names[2:-1]) == {"token"}
    assert events[0][1]["request_id"]
    sources = events[1][1]
    assert sources["mode"] == "full"
    assert sources["sources"][0]["ref"] == 1
    assert sources["sources"][0]["item_id"] == item_ids["bike"]
    answer = "".join(data["text"] for name, data in events if name == "token")
    assert "[1]" in answer
    done = events[-1][1]
    assert done["citations"][0]["item_id"] == item_ids["bike"]
    assert set(done["timings_ms"]) == {"embed", "retrieve", "rerank", "generate", "total"}


def test_stream_mode_none_sends_not_found_answer_without_llm(
    client: TestClient, item_ids: dict[str, str], chat: FakeChatModel
) -> None:
    events = stream_events(client, OFF_TOPIC)
    assert [name for name, _ in events] == ["meta", "sources", "token", "done"]
    assert events[1][1] == {"mode": "none", "sources": []}
    assert events[2][1] == {"text": NOT_FOUND_ANSWER}
    assert events[3][1]["citations"] == []
    assert chat.calls == []


def test_stream_failure_mid_answer_emits_error_and_closes(
    client: TestClient, item_ids: dict[str, str], chat: FakeChatModel
) -> None:
    chat.script = FakeChatScript.FAIL_RETRYABLE
    chat.fail_after_tokens = 2
    events = stream_events(client, BIKE_QUESTION)

    assert [name for name, _ in events] == ["meta", "sources", "token", "token", "error"]
    assert events[-1][1]["code"] == "UPSTREAM_UNAVAILABLE"
