"""Real OpenAI SDK, fake HTTP: a MockRouter is injected as the SDK's httpx2 transport."""

import json
from collections.abc import Iterator

import httpx2
import pytest
from structlog.testing import capture_logs

from app.domain.errors import ProviderError, ProviderErrorKind
from app.providers.base import ChatMessage
from app.providers.openai_provider import OpenAIChatModel, OpenAIEmbedder, build_client
from tests.support.mock_http import MockRouter, UnmatchedRequestError, mock_router_fixture

BASE = "https://api.openai.com/v1"
DIM = 3
MESSAGES = [ChatMessage("system", "rules"), ChatMessage("user", "question")]
USAGE = {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16}


@pytest.fixture
def api() -> Iterator[MockRouter]:
    yield from mock_router_fixture(BASE)


def embedder(api: MockRouter, max_retries: int = 0) -> OpenAIEmbedder:
    client = build_client("sk-test", timeout_s=5, max_retries=max_retries, http_client=api.client())
    return OpenAIEmbedder(client, model="text-embedding-3-small", dim=DIM)


def chat(api: MockRouter, temperature: float | None = None) -> OpenAIChatModel:
    client = build_client("sk-test", timeout_s=5, max_retries=0, http_client=api.client())
    return OpenAIChatModel(client, model="test-model", temperature=temperature)


def ok(body: dict) -> httpx2.Response:
    return httpx2.Response(200, json=body)


def error(status: int, code: str | None = None, **headers: str) -> httpx2.Response:
    return httpx2.Response(status, headers=headers, json={"error": {"message": "x", "code": code}})


def embeddings_body(vectors: list[list[float]], order: list[int] | None = None) -> dict:
    order = order if order is not None else list(range(len(vectors)))
    return {
        "object": "list",
        "model": "text-embedding-3-small",
        "data": [{"object": "embedding", "index": i, "embedding": vectors[i]} for i in order],
        "usage": {"prompt_tokens": 7, "total_tokens": 7},
    }


def response_body(text: str) -> dict:
    message = {
        "type": "message",
        "id": "msg_1",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "test-model",
        "status": "completed",
        "output": [message],
        "usage": USAGE,
    }


def sse(*events: dict) -> httpx2.Response:
    body = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events)
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


def delta(text: str, seq: int) -> dict:
    return {
        "type": "response.output_text.delta",
        "delta": text,
        "item_id": "msg_1",
        "output_index": 0,
        "content_index": 0,
        "sequence_number": seq,
    }


def sent_json(route) -> dict:
    return json.loads(route.last_request.content)


# --- embeddings --------------------------------------------------------------------------------


def test_embeddings_success_sends_dimensions_and_reorders_by_index(api: MockRouter) -> None:
    vectors = [[1.0, 0, 0], [0, 1.0, 0]]
    route = api.add("POST", "/embeddings", ok(embeddings_body(vectors, order=[1, 0])))

    with capture_logs() as logs:
        result = embedder(api).embed(["first", "second"])

    assert result == vectors
    sent = sent_json(route)
    assert (sent["model"], sent["input"], sent["dimensions"]) == (
        "text-embedding-3-small",
        ["first", "second"],
        DIM,
    )
    done = next(e for e in logs if e["event"] == "provider.embeddings_completed")
    assert (done["model"], done["inputs"], done["input_tokens"]) == ("text-embedding-3-small", 2, 7)
    assert isinstance(done["ms"], float)


def test_429_then_success_is_retried_by_the_sdk(api: MockRouter) -> None:
    route = api.add(
        "POST",
        "/embeddings",
        [error(429, **{"retry-after-ms": "1"}), ok(embeddings_body([[1.0, 0, 0]]))],
    )

    assert embedder(api, max_retries=2).embed(["text"]) == [[1.0, 0, 0]]
    assert route.call_count == 2


def test_auth_failure_maps_to_auth_kind_and_is_logged(api: MockRouter) -> None:
    api.add("POST", "/embeddings", error(401, "invalid_api_key"))

    with pytest.raises(ProviderError) as excinfo, capture_logs() as logs:
        embedder(api).embed(["text"])

    assert (excinfo.value.kind, excinfo.value.retryable) == (ProviderErrorKind.AUTH, False)
    assert any(entry["event"] == "provider.auth_failed" for entry in logs)


def test_timeout_maps_to_retryable_timeout(api: MockRouter) -> None:
    api.add("POST", "/embeddings", httpx2.ReadTimeout("slow"))

    with pytest.raises(ProviderError) as excinfo:
        embedder(api).embed(["text"])

    assert (excinfo.value.kind, excinfo.value.retryable) == (ProviderErrorKind.TIMEOUT, True)


def test_server_error_maps_to_unavailable(api: MockRouter) -> None:
    api.add("POST", "/embeddings", error(503))
    with pytest.raises(ProviderError) as excinfo:
        embedder(api).embed(["text"])
    assert excinfo.value.kind is ProviderErrorKind.UNAVAILABLE


@pytest.mark.parametrize(
    ("body", "inputs"),
    [
        (embeddings_body([[1.0, 0]]), ["a"]),  # wrong dimension
        (embeddings_body([[1.0, 0, 0], [0, 1.0, 0]], order=[0, 0]), ["a", "b"]),  # dup index
        (embeddings_body([[1.0, 0, 0]], order=[]), ["a"]),  # empty data (SDK ValueError)
        (embeddings_body([[1.0, 0, 0], [0, 1.0, 0]], order=[0]), ["a", "b"]),  # missing item
    ],
)
def test_malformed_embedding_responses_are_invalid_response(
    api: MockRouter, body: dict, inputs: list[str]
) -> None:
    api.add("POST", "/embeddings", ok(body))
    with pytest.raises(ProviderError) as excinfo:
        embedder(api).embed(inputs)
    assert (excinfo.value.kind, excinfo.value.retryable) == (
        ProviderErrorKind.INVALID_RESPONSE,
        False,
    )


def test_large_input_sets_are_split_into_batches(
    api: MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.providers.openai_provider.MAX_BATCH_INPUTS", 2)

    def respond(request: httpx2.Request) -> httpx2.Response:
        count = len(json.loads(request.content)["input"])
        return ok(embeddings_body([[1.0, 0, 0]] * count))

    route = api.add("POST", "/embeddings", handler=respond)
    assert len(embedder(api).embed(["a", "b", "c", "d", "e"])) == 5
    assert route.call_count == 3


def test_over_long_input_is_truncated_with_a_text_free_warning(
    api: MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.providers.openai_provider.MAX_INPUT_TOKENS", 3)
    route = api.add("POST", "/embeddings", ok(embeddings_body([[1.0, 0, 0]])))

    with capture_logs() as logs:
        embedder(api).embed(["one two three four five"])

    assert sent_json(route)["input"] == ["one two three"]
    warning = next(e for e in logs if e["event"] == "provider.embedding_input_truncated")
    assert warning == {
        "event": "provider.embedding_input_truncated",
        "ordinal": 0,
        "tokens": 5,
        "limit": 3,
        "log_level": "warning",
    }


def test_empty_text_is_rejected_before_any_call(api: MockRouter) -> None:
    route = api.add("POST", "/embeddings", error(500))
    with pytest.raises(ValueError, match="input 1"):
        embedder(api).embed(["ok", "  "])
    assert route.call_count == 0


# --- chat --------------------------------------------------------------------------------------


def test_chat_complete_sends_store_false_and_no_temperature_by_default(api: MockRouter) -> None:
    route = api.add("POST", "/responses", ok(response_body("Answer [1].")))

    with capture_logs() as logs:
        assert chat(api).complete(MESSAGES) == "Answer [1]."

    sent = sent_json(route)
    assert sent["store"] is False
    assert "temperature" not in sent
    assert sent["input"] == [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
    ]
    done = next(e for e in logs if e["event"] == "provider.chat_completed")
    assert {k: done[k] for k in ("model", "input_tokens", "output_tokens", "streamed")} == {
        "model": "test-model",
        "input_tokens": 12,
        "output_tokens": 4,
        "streamed": False,
    }
    assert isinstance(done["ms"], float)


def test_chat_sends_temperature_only_when_configured(api: MockRouter) -> None:
    route = api.add("POST", "/responses", ok(response_body("ok")))
    chat(api, temperature=0.2).complete(MESSAGES)
    assert sent_json(route)["temperature"] == 0.2


def test_chat_stream_yields_deltas_skips_empty_and_logs_final_usage(api: MockRouter) -> None:
    completed = {"type": "response.completed", "sequence_number": 4, "response": response_body("")}
    route = api.add(
        "POST", "/responses", sse(delta("Hel", 1), delta("", 2), delta("lo [1]", 3), completed)
    )

    with capture_logs() as logs:
        assert list(chat(api).stream(MESSAGES)) == ["Hel", "lo [1]"]

    sent = sent_json(route)
    assert (sent["stream"], sent["store"]) == (True, False)
    done = next(e for e in logs if e["event"] == "provider.chat_completed")
    assert (done["input_tokens"], done["output_tokens"], done["streamed"]) == (12, 4, True)


def test_chat_stream_without_usage_logs_nulls(api: MockRouter) -> None:
    api.add("POST", "/responses", sse(delta("hi", 1)))
    with capture_logs() as logs:
        assert list(chat(api).stream(MESSAGES)) == ["hi"]
    done = next(e for e in logs if e["event"] == "provider.chat_completed")
    assert (done["input_tokens"], done["output_tokens"]) == (None, None)


def test_chat_stream_failed_event_raises_provider_error(api: MockRouter) -> None:
    failed = {"type": "response.failed", "sequence_number": 2, "response": response_body("")}
    api.add("POST", "/responses", sse(delta("partial", 1), failed))

    received: list[str] = []
    with pytest.raises(ProviderError) as excinfo:
        received.extend(chat(api).stream(MESSAGES))
    assert received == ["partial"]
    assert excinfo.value.kind is ProviderErrorKind.UNAVAILABLE


def test_chat_http_error_maps_to_provider_error(api: MockRouter) -> None:
    api.add("POST", "/responses", error(400, "model_not_found"))
    with pytest.raises(ProviderError) as excinfo:
        chat(api).complete(MESSAGES)
    assert excinfo.value.kind is ProviderErrorKind.BAD_REQUEST


# --- the mock router itself ----------------------------------------------------------------------


def test_router_records_unmatched_requests_and_idle_routes() -> None:
    router = MockRouter(BASE)
    router.add("GET", "/never", ok({}))
    with pytest.raises(UnmatchedRequestError), router.client() as client:
        client.get(f"{BASE}/other")
    assert router.unmatched == [f"GET {BASE}/other"]
    with pytest.raises(AssertionError, match="never called"):
        router.assert_all_called()
