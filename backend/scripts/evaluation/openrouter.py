"""Eval-only LLM route: the app's chat model (same model id) called through OpenRouter.

Used when Groq's free-tier daily cap blocks a run. OpenRouter is pinned to its Groq provider
with fallbacks disabled, so a call fails rather than silently running on another provider; the
provider that served each call is still recorded and checked. The app never uses this.
"""

from collections.abc import Sequence
from typing import Any

import openai
import tiktoken

from app.config import Settings
from app.providers.base import ChatMessage
from app.providers.error_mapping import map_openai_error
from app.providers.openai_compatible import OpenAICompatibleChatModel
from app.providers.openai_provider import build_client
from app.utils.timing import Timer

PINNED_PROVIDER = "groq"
# Third-party price listings for openai/gpt-oss-120b on Groq, USD per 1M tokens (not verified).
GROQ_IN, GROQ_OUT = 0.15, 0.60
BUDGET_USD = 2.0
_ENCODING = tiktoken.get_encoding("o200k_base")


class OpenRouterChat(OpenAICompatibleChatModel):
    """Remembers the serving provider and token usage of the last call."""

    last_provider: str | None = None
    last_usage: tuple[int, int] | None = None
    last_ms: float | None = None

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        with Timer() as timer:
            try:
                response = self._client.chat.completions.create(**self._request(messages))
            except openai.OpenAIError as exc:
                raise map_openai_error(exc, "openrouter") from exc
        extra = response.model_extra or {}
        self.last_provider = extra.get("provider")
        if (self.last_provider or "").lower() != PINNED_PROVIDER:
            raise SystemExit(f"OpenRouter served {self.last_provider!r}, not {PINNED_PROVIDER}")
        usage = response.usage
        self.last_usage = (usage.prompt_tokens, usage.completion_tokens) if usage else None
        self.last_ms = timer.ms
        self._log_completed(usage, timer.ms, streamed=False)
        choice = response.choices[0] if response.choices else None
        return (choice.message.content if choice else None) or ""

    def _request(self, messages: Sequence[ChatMessage]) -> dict[str, Any]:
        request = super()._request(messages)
        request["extra_body"] = {
            "provider": {
                "order": [PINNED_PROVIDER],
                "only": [PINNED_PROVIDER],
                "allow_fallbacks": False,
            }
        }
        return request


def build_openrouter_chat(settings: Settings) -> tuple[OpenRouterChat, openai.OpenAI]:
    if settings.openrouter_api_key is None or settings.llm_model is None:
        raise SystemExit("OPENROUTER_API_KEY and LLM_MODEL must be set in .env")
    client = build_client(
        settings.openrouter_api_key.get_secret_value(),
        base_url=settings.openrouter_base_url.rstrip("/") + "/api/v1",
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.openai_max_retries,
    )
    chat = OpenRouterChat(
        client,
        model=settings.llm_model,
        provider="openrouter",
        temperature=0.0,
        reasoning_effort=settings.llm_reasoning_effort,
    )
    return chat, client


def estimate_and_gate(prompts: list[str], output_tokens_each: int, label: str) -> None:
    """Print the estimated cost of a paid run; refuse to continue at or above the budget."""
    tokens_in = sum(len(_ENCODING.encode(p)) for p in prompts)
    tokens_out = output_tokens_each * len(prompts)
    cost = (tokens_in * GROQ_IN + tokens_out * GROQ_OUT) / 1_000_000
    print(
        f"{label}: {len(prompts)} calls, ~{tokens_in:,} input + ~{tokens_out:,} output tokens "
        f"(output assumed {output_tokens_each}/call), estimated ${cost:.4f} "
        f"at ${GROQ_IN}/${GROQ_OUT} per 1M (third-party listing)"
    )
    if cost >= BUDGET_USD:
        raise SystemExit(f"estimate ${cost:.2f} is not under the ${BUDGET_USD:.2f} budget; stopped")
