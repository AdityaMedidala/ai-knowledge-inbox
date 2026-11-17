"""Manual smoke test of the configured providers using .env: one embed + one streamed chat.

Run with `make smoke`. Real network calls; not collected by pytest.
"""

import sys

from pydantic import ValidationError

from app.config import Settings
from app.domain.errors import ProviderError, ProviderErrorKind
from app.logging import configure_logging
from app.providers.base import ChatMessage
from app.providers.factory import build_providers
from app.utils.timing import Timer

HOSTS = {"openai": "api.openai.com"}


def explain(error: ProviderError) -> str:
    host = HOSTS.get(error.provider, error.provider)
    if error.kind is ProviderErrorKind.RATE_LIMITED and not error.retryable:
        return f"Account has no credits — add billing ({host})."
    if error.kind is ProviderErrorKind.RATE_LIMITED:
        return (
            f"Rate limited by {host} (free tiers are ~30 req/min, 8k tokens/min) — "
            "wait a minute and retry."
        )
    if error.kind is ProviderErrorKind.AUTH:
        return f"{host} rejected the API key — check LLM_API_KEY / OPENAI_API_KEY in .env."
    if error.kind in (ProviderErrorKind.UNAVAILABLE, ProviderErrorKind.TIMEOUT):
        return f"Could not reach {host} (network/DNS) — check your connection and retry."
    if error.kind is ProviderErrorKind.BAD_REQUEST:
        return f"{host} rejected the request ({error.message}) — check LLM_MODEL and options."
    return f"{host} call failed: {error.kind} ({error.message})."


def main() -> None:
    try:
        settings = Settings()
    except ValidationError as exc:
        sys.exit(f"smoke: invalid configuration in .env:\n{exc}")
    configure_logging(settings.log_level, json_logs=False)
    providers = build_providers(settings)
    try:
        with Timer() as timer:
            (document,) = providers.embedder.embed_documents(["smoke test for the knowledge inbox"])
            query = providers.embedder.embed_query("what is the knowledge inbox?")
        print(
            f"embed  ok  provider={settings.embedding_provider} model={settings.embedding_model} "
            f"dims={len(document)}/{len(query)} ms={timer.ms}"
        )
        if settings.llm_provider == "fake":
            print("chat   skipped (LLM_PROVIDER=fake)")
            return
        messages = [
            ChatMessage("system", "Reply with one short sentence."),
            ChatMessage("user", "Say hello to the knowledge inbox."),
        ]
        with Timer() as timer:
            reply = "".join(providers.chat.stream(messages))
        print(
            f"chat   ok  provider={settings.llm_provider} model={settings.llm_model} "
            f"ms={timer.ms} reply={reply[:80]!r}"
        )
    finally:
        providers.close()


if __name__ == "__main__":
    try:
        main()
    except ProviderError as exc:
        sys.exit(f"smoke: {explain(exc)}")
