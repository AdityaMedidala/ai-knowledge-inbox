"""Manual smoke test: one real embedding call and one real streamed chat call using .env.

Run with `make smoke-openai`. Not collected by pytest; costs a fraction of a cent.
"""

import sys

from pydantic import SecretStr, ValidationError

from app.config import Settings
from app.domain.errors import ProviderError, ProviderErrorKind
from app.logging import configure_logging
from app.providers.base import ChatMessage
from app.providers.openai_provider import OpenAIChatModel, OpenAIEmbedder, build_client
from app.utils.timing import Timer

OPENAI_HOST = "api.openai.com"


def _require(value: SecretStr | str | None, name: str) -> str:
    if not value:
        sys.exit(f"smoke-openai: {name} must be set in .env")
    return value.get_secret_value() if isinstance(value, SecretStr) else value


def main() -> None:
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.exit(f"smoke-openai: invalid configuration in .env:\n{exc}")
    configure_logging(settings.log_level, json_logs=False)
    api_key = _require(settings.openai_api_key, "OPENAI_API_KEY")
    model = _require(settings.llm_model, "LLM_MODEL")
    client = build_client(api_key, timeout_s=30, max_retries=settings.openai_max_retries)

    embedder = OpenAIEmbedder(client, model=settings.embedding_model, dim=settings.embedding_dim)
    with Timer() as embed_timer:
        (vector,) = embedder.embed(["smoke test for the knowledge inbox"])
    print(f"embed  ok  model={settings.embedding_model} dims={len(vector)} ms={embed_timer.ms}")

    chat = OpenAIChatModel(client, model=model, temperature=settings.llm_temperature)
    messages = [
        ChatMessage("system", "Reply with one short sentence."),
        ChatMessage("user", "Say hello to the knowledge inbox."),
    ]
    with Timer() as chat_timer:
        reply = "".join(chat.stream(messages))
    print(f"chat   ok  model={model} ms={chat_timer.ms} reply={reply[:80]!r}")
    client.close()


def explain(error: ProviderError, host: str) -> str:
    if error.kind is ProviderErrorKind.RATE_LIMITED and not error.retryable:
        return f"Account has no credits — add billing ({error.provider})."
    if error.kind is ProviderErrorKind.RATE_LIMITED:
        return f"Rate limited by {error.provider} — wait a minute and retry."
    if error.kind is ProviderErrorKind.AUTH:
        return f"{error.provider} rejected the API key — check it in .env."
    if error.kind in (ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.TIMEOUT):
        return f"Could not reach {host} (network/DNS) — check your connection and retry."
    return f"{error.provider} call failed: {error.kind} ({error.message})."


if __name__ == "__main__":
    try:
        main()
    except ProviderError as exc:
        sys.exit(f"smoke-openai: {explain(exc, host=OPENAI_HOST)}")
