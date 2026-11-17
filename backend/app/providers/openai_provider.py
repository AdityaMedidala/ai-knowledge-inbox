"""OpenAI embeddings + Responses API chat. Retries/backoff come from the SDK (max_retries)."""

from collections.abc import Iterator, Sequence
from typing import Any

import httpx2
import openai
import structlog
from openai.types import CreateEmbeddingResponse
from openai.types.responses import ResponseUsage

from app.domain.errors import ProviderError, ProviderErrorKind
from app.providers.base import ChatMessage
from app.providers.batching import plan_batches
from app.providers.error_mapping import map_openai_error
from app.utils.timing import Timer
from app.utils.tokens import count_tokens, truncate_to_tokens

logger = structlog.get_logger(__name__)

PROVIDER = "openai"
MAX_INPUT_TOKENS = 8191  # text-embedding-3 per-input limit
MAX_BATCH_TOKENS = 100_000  # API allows 300k per request; stay well under
MAX_BATCH_INPUTS = 256  # API allows 2048; smaller batches keep latency predictable


def build_client(
    api_key: str,
    *,
    timeout_s: float,
    max_retries: int,
    http_client: httpx2.Client | None = None,
) -> openai.OpenAI:
    """`http_client` is for tests (mock transport); production uses the SDK's default client."""
    return openai.OpenAI(
        api_key=api_key, timeout=timeout_s, max_retries=max_retries, http_client=http_client
    )


class OpenAIEmbedder:
    def __init__(self, client: openai.OpenAI, *, model: str, dim: int) -> None:
        self._client = client
        self._model = model
        self._dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        for ordinal, text in enumerate(texts):
            if not text.strip():
                raise ValueError(f"Cannot embed empty text (input {ordinal}).")
        fitted = [self._fit(ordinal, text) for ordinal, text in enumerate(texts)]
        batches = plan_batches(
            [tokens for _, tokens in fitted],
            max_tokens=MAX_BATCH_TOKENS,
            max_inputs=MAX_BATCH_INPUTS,
        )
        vectors: list[list[float]] = []
        for batch in batches:
            vectors += self._embed_batch([fitted[i][0] for i in batch])
        return vectors

    def _fit(self, ordinal: int, text: str) -> tuple[str, int]:
        tokens = count_tokens(text)
        if tokens <= MAX_INPUT_TOKENS:
            return text, tokens
        logger.warning(
            "provider.embedding_input_truncated",
            ordinal=ordinal,
            tokens=tokens,
            limit=MAX_INPUT_TOKENS,
        )
        return truncate_to_tokens(text, MAX_INPUT_TOKENS), MAX_INPUT_TOKENS

    def _embed_batch(self, inputs: list[str]) -> list[list[float]]:
        with Timer() as timer:
            try:
                response = self._client.embeddings.create(
                    model=self._model, input=inputs, dimensions=self._dim
                )
            except openai.OpenAIError as exc:
                raise map_openai_error(exc) from exc
            except ValueError as exc:  # SDK's own parse failure, e.g. "No embedding data received"
                raise _invalid(f"unparseable embeddings response: {exc}") from exc
        vectors = self._ordered_vectors(response, expected=len(inputs))
        logger.info(
            "provider.embeddings_completed",
            model=self._model,
            inputs=len(inputs),
            input_tokens=response.usage.prompt_tokens if response.usage else None,
            ms=timer.ms,
        )
        return vectors

    def _ordered_vectors(
        self, response: CreateEmbeddingResponse, *, expected: int
    ) -> list[list[float]]:
        by_index = {item.index: item.embedding for item in response.data}
        if sorted(by_index) != list(range(expected)) or len(response.data) != expected:
            raise _invalid(f"expected indexes 0..{expected - 1}, got {sorted(by_index)}")
        for index, vector in by_index.items():
            if len(vector) != self._dim:
                raise _invalid(f"input {index}: returned {len(vector)} dims, expected {self._dim}")
        return [by_index[i] for i in range(expected)]


class OpenAIChatModel:
    def __init__(self, client: openai.OpenAI, *, model: str, temperature: float | None) -> None:
        self._client = client
        self._model = model
        self._temperature = temperature

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        with Timer() as timer:
            try:
                response = self._client.responses.create(**self._request(messages))
            except openai.OpenAIError as exc:
                raise map_openai_error(exc) from exc
        text = response.output_text or ""
        if not text:
            logger.warning("provider.chat_empty_output", model=self._model)
        self._log_completed(response.usage, timer.ms, streamed=False)
        return text

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        usage: ResponseUsage | None = None
        with Timer() as timer:
            try:
                request = self._request(messages)
                with self._client.responses.create(**request, stream=True) as events:
                    for event in events:
                        if event.type == "response.output_text.delta":
                            if event.delta:
                                yield event.delta
                        elif event.type == "response.completed":
                            usage = event.response.usage
                        elif event.type == "response.incomplete":
                            usage = event.response.usage
                            details = event.response.incomplete_details
                            logger.warning(
                                "provider.chat_incomplete",
                                model=self._model,
                                reason=details.reason if details else None,
                            )
                        elif event.type in ("response.failed", "error"):
                            raise ProviderError(
                                ProviderErrorKind.UNAVAILABLE, PROVIDER, f"stream {event.type}"
                            )
            except openai.OpenAIError as exc:
                raise map_openai_error(exc) from exc
        self._log_completed(usage, timer.ms, streamed=True)

    def _request(self, messages: Sequence[ChatMessage]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model,
            "input": [{"role": m.role, "content": m.content} for m in messages],
            "store": False,  # user content is sent as context; don't retain it server-side
        }
        if self._temperature is not None:
            request["temperature"] = self._temperature
        return request

    def _log_completed(self, usage: ResponseUsage | None, ms: float, *, streamed: bool) -> None:
        logger.info(
            "provider.chat_completed",
            model=self._model,
            input_tokens=usage.input_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            ms=ms,
            streamed=streamed,
        )


def _invalid(message: str) -> ProviderError:
    return ProviderError(ProviderErrorKind.INVALID_RESPONSE, PROVIDER, message)
