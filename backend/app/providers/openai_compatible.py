"""Chat Completions against any OpenAI-compatible API (Groq, etc.) selected by base URL."""

from collections.abc import Iterator, Sequence
from typing import Any

import openai
import structlog
from openai.types import CompletionUsage

from app.providers.base import ChatMessage
from app.providers.error_mapping import map_openai_error
from app.providers.usage import log_chat_completed
from app.utils.timing import Timer

logger = structlog.get_logger(__name__)


class OpenAICompatibleChatModel:
    """`provider` is the API host (e.g. api.groq.com); it labels logs and errors.

    No `store` parameter: it is OpenAI-specific and compatible APIs may reject it.
    """

    def __init__(
        self,
        client: openai.OpenAI,
        *,
        model: str,
        provider: str,
        temperature: float | None,
        reasoning_effort: str | None,
    ) -> None:
        self._client = client
        self._model = model
        self._provider = provider
        self._temperature = temperature
        self._reasoning_effort = reasoning_effort

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        with Timer() as timer:
            try:
                response = self._client.chat.completions.create(**self._request(messages))
            except openai.OpenAIError as exc:
                raise map_openai_error(exc, self._provider) from exc
        choice = response.choices[0] if response.choices else None
        if choice is not None and choice.finish_reason == "length":
            self._warn_incomplete("length")
        text = (choice.message.content if choice else None) or ""
        if not text:
            logger.warning("provider.chat_empty_output", model=self._model)
        self._log_completed(response.usage, timer.ms, streamed=False)
        return text

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        usage: CompletionUsage | None = None
        request = {**self._request(messages), "stream_options": {"include_usage": True}}
        with Timer() as timer:
            try:
                with self._client.chat.completions.create(**request, stream=True) as chunks:
                    for chunk in chunks:
                        usage = chunk.usage or usage  # final chunk: usage only, no choices
                        if not chunk.choices:
                            continue
                        choice = chunk.choices[0]
                        if choice.delta and choice.delta.content:
                            yield choice.delta.content
                        if choice.finish_reason == "length":
                            self._warn_incomplete("length")
            except openai.OpenAIError as exc:
                raise map_openai_error(exc, self._provider) from exc
        self._log_completed(usage, timer.ms, streamed=True)

    def _request(self, messages: Sequence[ChatMessage]) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if self._temperature is not None:
            request["temperature"] = self._temperature
        if self._reasoning_effort is not None:
            request["reasoning_effort"] = self._reasoning_effort
        return request

    def _warn_incomplete(self, reason: str) -> None:
        logger.warning("provider.chat_incomplete", model=self._model, reason=reason)

    def _log_completed(self, usage: CompletionUsage | None, ms: float, *, streamed: bool) -> None:
        log_chat_completed(
            self._model,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            ms=ms,
            streamed=streamed,
        )
