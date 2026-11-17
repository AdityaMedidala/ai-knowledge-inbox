"""Cohere rerank. `cohere` is an optional extra, imported only when RERANKER=cohere."""

from collections.abc import Sequence
from typing import Any

from app.domain.errors import ProviderError, ProviderErrorKind
from app.providers.base import RerankResult
from app.providers.error_mapping import kind_for_status, provider_error

PROVIDER = "cohere"


class CohereReranker:
    """The error classes are injected because they come from the optional SDK's own HTTP stack."""

    def __init__(
        self,
        client: Any,
        *,
        model: str,
        api_error: type[Exception],
        timeout_error: type[Exception],
        transport_error: type[Exception],
    ) -> None:
        self._client = client
        self._model = model
        self._api_error = api_error
        self._timeout_error = timeout_error
        self._transport_error = transport_error

    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]:
        if not documents:
            return []
        try:
            response = self._client.rerank(
                model=self._model, query=query, documents=list(documents), top_n=len(documents)
            )
        except (self._api_error, self._transport_error) as exc:
            raise self._map_error(exc) from exc
        return [RerankResult(index=r.index, score=r.relevance_score) for r in response.results]

    def _map_error(self, exc: Exception) -> ProviderError:
        if isinstance(exc, self._api_error):
            status = getattr(exc, "status_code", None) or 500
            return provider_error(kind_for_status(status), PROVIDER, f"HTTP {status}")
        if isinstance(exc, self._timeout_error):
            return provider_error(ProviderErrorKind.TIMEOUT, PROVIDER, "request timed out")
        return provider_error(ProviderErrorKind.UNAVAILABLE, PROVIDER, "connection failed")


def build_cohere_reranker(api_key: str, *, model: str, timeout_s: float) -> CohereReranker:
    try:  # optional extra: import only when configured
        import cohere
        import httpx  # cohere's own HTTP dependency, present whenever cohere is
        from cohere.core.api_error import ApiError
    except ImportError as exc:
        raise RuntimeError("RERANKER=cohere needs the extra: `uv sync --extra cohere`.") from exc
    return CohereReranker(
        cohere.ClientV2(api_key=api_key, timeout=timeout_s),
        model=model,
        api_error=ApiError,
        timeout_error=httpx.TimeoutException,
        transport_error=httpx.HTTPError,
    )
