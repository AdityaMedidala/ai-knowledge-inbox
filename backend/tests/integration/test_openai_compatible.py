"""Chat Completions against an OpenAI-compatible base URL (Groq), via the MockRouter transport."""

import json
from collections.abc import Iterator

import httpx2
import pytest
from structlog.testing import capture_logs

from app.config import Settings
from app.domain.errors import ProviderError, ProviderErrorKind
from app.providers.base import ChatMessage
from app.providers.factory import build_chat_model
from app.providers.openai_compatible import OpenAICompatibleChatModel
from app.providers.openai_provider import build_client
from tests.support.mock_http import MockRouter, mock_router_fixture

GROQ = "https://api.groq.com/openai/v1"
MESSAGES = [ChatMessage("system", "rules"), ChatMessage("user", "question")]


@pytest.fixture
def api() -> Iterator[MockRouter]:
    yield from mock_router_fixture(GROQ)


def model(api: MockRouter, *, max_retries: int = 0, **options: object) -> OpenAICompatibleChatModel:
    client = build_client(
        "gsk-test", base_url=GROQ, timeout_s=5, max_retries=max_retries, http_client=api.client()
    )
    return OpenAICompatibleChatModel(
        client,
        model="openai/gpt-oss-120b",
        provider="api.groq.com",
        temperature=options.get("temperature"),  # type: ignore[arg-type]
        reasoning_effort=options.get("reasoning_effort"),  # type: ignore[arg-type]
    )


def completion(text: str, finish_reason: str = "stop") -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "openai/gpt-oss-120b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 3, "total_tokens": 12},
        },
    )


def chunk(content: str | None, *, usage: dict | None = None, choices: bool = True) -> dict:
    body: dict = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "m"}
    body["choices"] = (
        [{"index": 0, "delta": {"content": content}, "finish_reason": None}] if choices else []
    )
    if usage:
        body["usage"] = usage
    return body


def sse(*chunks: dict) -> httpx2.Response:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(200, text=body, headers={"content-type": "text/event-stream"})


def error(status: int, code: str, **headers: str) -> httpx2.Response:
    return httpx2.Response(status, headers=headers, json={"error": {"message": "x", "code": code}})


def sent(route) -> dict:
    return json.loads(route.last_request.content)


def test_request_targets_the_configured_host_with_llm_api_key(api: MockRouter) -> None:
    route = api.add("POST", "/chat/completions", completion("Hi [1]."))

    assert model(api).complete(MESSAGES) == "Hi [1]."

    request = route.last_request
    assert (request.url.host, request.url.path) == ("api.groq.com", "/openai/v1/chat/completions")
    assert request.headers["authorization"] == "Bearer gsk-test"
    body = sent(route)
    assert body["messages"][1] == {"role": "user", "content": "question"}
    assert not {"store", "temperature", "reasoning_effort"} & body.keys()


def test_factory_builds_client_for_llm_base_url_not_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    settings = Settings(
        _env_file=None,
        embedding_provider="fake",
        llm_provider="openai_compatible",
        llm_base_url=GROQ,
        llm_api_key="gsk-from-settings",
        openai_api_key="sk-must-not-be-used",
        llm_model="openai/gpt-oss-120b",
    )
    closers: list = []
    chat = build_chat_model(settings, closers)

    client = chat._client
    assert (client.base_url.host, client.base_url.path) == ("api.groq.com", "/openai/v1/")
    assert client.api_key == "gsk-from-settings"
    for close in closers:
        close()


def test_optional_options_are_sent_only_when_configured(api: MockRouter) -> None:
    route = api.add("POST", "/chat/completions", completion("ok"))
    model(api, temperature=0.3, reasoning_effort="low").complete(MESSAGES)
    assert (sent(route)["temperature"], sent(route)["reasoning_effort"]) == (0.3, "low")


def test_complete_logs_usage(api: MockRouter) -> None:
    api.add("POST", "/chat/completions", completion("ok"))
    with capture_logs() as logs:
        model(api).complete(MESSAGES)
    done = next(e for e in logs if e["event"] == "provider.chat_completed")
    assert (done["model"], done["input_tokens"], done["output_tokens"], done["streamed"]) == (
        "openai/gpt-oss-120b",
        9,
        3,
        False,
    )


def test_truncated_completion_logs_incomplete(api: MockRouter) -> None:
    api.add("POST", "/chat/completions", completion("partial", finish_reason="length"))
    with capture_logs() as logs:
        model(api).complete(MESSAGES)
    assert any(e["event"] == "provider.chat_incomplete" for e in logs)


def test_stream_skips_empty_and_usage_only_chunks(api: MockRouter) -> None:
    usage = {"prompt_tokens": 9, "completion_tokens": 2, "total_tokens": 11}
    route = api.add(
        "POST",
        "/chat/completions",
        sse(
            chunk("Hel"),
            chunk(None),
            chunk(""),
            chunk("lo"),
            chunk(None, usage=usage, choices=False),
        ),
    )

    with capture_logs() as logs:
        assert list(model(api).stream(MESSAGES)) == ["Hel", "lo"]

    body = sent(route)
    assert (body["stream"], body["stream_options"]) == (True, {"include_usage": True})
    done = next(e for e in logs if e["event"] == "provider.chat_completed")
    assert (done["input_tokens"], done["output_tokens"], done["streamed"]) == (9, 2, True)


def test_groq_rate_limit_is_retryable_and_retried(api: MockRouter) -> None:
    route = api.add(
        "POST",
        "/chat/completions",
        [error(429, "rate_limit_exceeded", **{"retry-after-ms": "1"}), completion("ok")],
    )
    assert model(api, max_retries=1).complete(MESSAGES) == "ok"
    assert route.call_count == 2


def test_groq_rate_limit_maps_to_retryable_rate_limited(api: MockRouter) -> None:
    api.add("POST", "/chat/completions", error(429, "rate_limit_exceeded"))
    with pytest.raises(ProviderError) as excinfo:
        model(api).complete(MESSAGES)
    error_ = excinfo.value
    assert (error_.kind, error_.retryable, error_.provider) == (
        ProviderErrorKind.RATE_LIMITED,
        True,
        "api.groq.com",
    )


def test_rejected_option_maps_to_bad_request(api: MockRouter) -> None:
    api.add("POST", "/chat/completions", error(400, "invalid_request_error"))
    with pytest.raises(ProviderError) as excinfo:
        model(api, reasoning_effort="high").complete(MESSAGES)
    assert (excinfo.value.kind, excinfo.value.retryable) == (ProviderErrorKind.BAD_REQUEST, False)
