import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.providers.fakes import FakeVerifier

NOTE = "Bike maintenance\n\nOil the bike chain every 300 kilometres and check tyre pressure weekly."
QUESTION = "When should I oil the bike chain?"


@pytest.fixture
def settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"relevance_min_full": 0.5, "relevance_min_partial": 0.3, "verifier": "fake"}
    )


@pytest.fixture
def verifier(client: TestClient) -> FakeVerifier:
    return client.app.state.providers.verifier  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def bike_note(client: TestClient) -> None:
    client.post("/ingest", json={"type": "note", "content": NOTE})
    client.portal.call(client.app.state.worker.drain, 10)  # type: ignore[attr-defined,union-attr]


def events(client: TestClient) -> list[tuple[str, dict]]:
    response = client.post("/query/stream", json={"question": QUESTION})
    parsed = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n")
        parsed.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return parsed


def test_query_includes_per_sentence_verdicts(client: TestClient, verifier: FakeVerifier) -> None:
    body = client.post("/query", json={"question": QUESTION}).json()

    verification = body["verification"]
    assert verification["backend"] == "fake"
    assert verification["summary"]["total"] == len(verification["sentences"]) == 1
    sentence = verification["sentences"][0]
    assert sentence["refs"] == [1]
    assert sentence["verdict"] in {"supported", "partial", "unsupported"}
    assert sentence["decided_by"] == "fake"
    assert len(verifier.calls) == 1


def test_stream_sends_verification_after_tokens_and_before_done(client: TestClient) -> None:
    names = [name for name, _ in events(client)]
    assert names[-2:] == ["verification", "done"]
    assert names.index("verification") > max(i for i, n in enumerate(names) if n == "token")


def test_verifier_failure_still_returns_the_answer(
    client: TestClient, verifier: FakeVerifier
) -> None:
    verifier.fail = True
    body = client.post("/query", json={"question": QUESTION}).json()
    assert body["citations"] and body["verification"] is None
    assert "verification" not in [name for name, _ in events(client)]


def test_mode_none_skips_verification(client: TestClient, verifier: FakeVerifier) -> None:
    body = client.post("/query", json={"question": "What is the capital of Peru?"}).json()
    assert (body["mode"], body["verification"]) == ("none", None)
    assert verifier.calls == []
