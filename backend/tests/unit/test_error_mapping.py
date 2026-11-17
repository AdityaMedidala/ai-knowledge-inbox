import sys
from types import SimpleNamespace

import httpx2
import openai
import pytest
from structlog.testing import capture_logs

from app.domain.errors import ProviderErrorKind
from app.providers.cohere_reranker import CohereReranker, build_cohere_reranker
from app.providers.error_mapping import kind_for_status, map_openai_error

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/embeddings")


def status_error(cls: type[openai.APIStatusError], status: int, code: str | None = None):
    body = {"error": {"message": "x", "code": code}}
    response = httpx2.Response(status, request=REQUEST, json=body)
    return cls("x", response=response, body=body["error"])


@pytest.mark.parametrize(
    ("exc", "kind", "retryable"),
    [
        (openai.APITimeoutError(REQUEST), ProviderErrorKind.TIMEOUT, True),
        (openai.APIConnectionError(request=REQUEST), ProviderErrorKind.UNAVAILABLE, True),
        (status_error(openai.RateLimitError, 429), ProviderErrorKind.RATE_LIMITED, True),
        (
            status_error(openai.RateLimitError, 429, "insufficient_quota"),
            ProviderErrorKind.RATE_LIMITED,
            False,
        ),
        (status_error(openai.InternalServerError, 503), ProviderErrorKind.UNAVAILABLE, True),
        (status_error(openai.AuthenticationError, 401), ProviderErrorKind.AUTH, False),
        (status_error(openai.PermissionDeniedError, 403), ProviderErrorKind.AUTH, False),
        (status_error(openai.BadRequestError, 400), ProviderErrorKind.BAD_REQUEST, False),
        (status_error(openai.NotFoundError, 404), ProviderErrorKind.BAD_REQUEST, False),
    ],
)
def test_openai_errors_map_to_provider_error(
    exc: openai.OpenAIError, kind: ProviderErrorKind, retryable: bool
) -> None:
    error = map_openai_error(exc)
    assert (error.kind, error.retryable, error.provider) == (kind, retryable, "openai")


def test_auth_failure_is_logged_distinctly() -> None:
    with capture_logs() as logs:
        map_openai_error(status_error(openai.AuthenticationError, 401))
    assert {"event": "provider.auth_failed", "provider": "openai", "log_level": "error"} in logs


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, "rate_limited"),
        (401, "auth"),
        (504, "timeout"),
        (502, "unavailable"),
        (422, "bad_request"),
    ],
)
def test_kind_for_status(status: int, kind: str) -> None:
    assert kind_for_status(status) == kind


class FakeCohereApiError(Exception):
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeTransportError(Exception):
    pass


class FakeTimeoutError(FakeTransportError):  # mirrors httpx: TimeoutException ⊂ HTTPError
    pass


class FakeCohereClient:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def rerank(self, **kwargs: object) -> SimpleNamespace:
        if self.error:
            raise self.error
        return SimpleNamespace(
            results=[
                SimpleNamespace(index=1, relevance_score=0.9),
                SimpleNamespace(index=0, relevance_score=0.2),
            ]
        )


def reranker(error: Exception | None = None) -> CohereReranker:
    return CohereReranker(
        FakeCohereClient(error),
        model="rerank-x",
        api_error=FakeCohereApiError,
        timeout_error=FakeTimeoutError,
        transport_error=FakeTransportError,
    )


def test_cohere_rerank_returns_best_first_and_skips_empty() -> None:
    results = reranker().rerank("q", ["a", "b"])
    assert [(r.index, r.score) for r in results] == [(1, 0.9), (0, 0.2)]
    assert reranker().rerank("q", []) == []


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (FakeCohereApiError(429), ProviderErrorKind.RATE_LIMITED),
        (FakeCohereApiError(401), ProviderErrorKind.AUTH),
        (FakeTimeoutError("slow"), ProviderErrorKind.TIMEOUT),
        (FakeTransportError("down"), ProviderErrorKind.UNAVAILABLE),
    ],
)
def test_cohere_errors_map_to_provider_error(error: Exception, kind: ProviderErrorKind) -> None:
    with pytest.raises(Exception) as excinfo:
        reranker(error).rerank("q", ["a"])
    assert excinfo.value.kind is kind  # type: ignore[attr-defined]


def test_cohere_programming_errors_are_not_masked() -> None:
    with pytest.raises(KeyError):
        reranker(KeyError("bug")).rerank("q", ["a"])


def test_missing_cohere_extra_fails_with_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "cohere", None)
    with pytest.raises(RuntimeError, match="uv sync --extra cohere"):
        build_cohere_reranker("key", model="m", timeout_s=1)
