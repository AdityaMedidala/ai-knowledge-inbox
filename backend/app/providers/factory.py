"""Build providers once from settings (called in lifespan) and close them on shutdown."""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import SecretStr

from app.config import Settings
from app.providers.base import ChatModel, Embedder, Reranker, Verifier
from app.providers.cohere_reranker import build_cohere_reranker
from app.providers.fakes import FakeChatModel, FakeEmbedder, FakeVerifier
from app.providers.fastembed_provider import build_fastembed_embedder
from app.providers.groq_verifier import GroqVerifier
from app.providers.jev_verifier import JevVerifier, build_jev_client
from app.providers.openai_compatible import OpenAICompatibleChatModel
from app.providers.openai_provider import OpenAIChatModel, OpenAIEmbedder, build_client


@dataclass(slots=True)
class Providers:
    embedder: Embedder
    chat: ChatModel
    reranker: Reranker | None
    verifier: Verifier | None = None
    escalation: Verifier | None = None  # re-checks low-confidence Jev verdicts
    closers: list[Callable[[], None]] = field(default_factory=list)

    def close(self) -> None:
        for close in self.closers:
            close()


def build_providers(settings: Settings) -> Providers:
    closers: list[Callable[[], None]] = []
    chat = build_chat_model(settings, closers)
    verifier, escalation = build_verifiers(settings, chat, closers)
    return Providers(
        embedder=build_embedder(settings, closers),
        chat=chat,
        reranker=build_reranker(settings),
        verifier=verifier,
        escalation=escalation,
        closers=closers,
    )


def build_embedder(settings: Settings, closers: list[Callable[[], None]]) -> Embedder:
    if settings.embedding_provider == "fake":
        return FakeEmbedder(settings.embedding_dim)
    if settings.embedding_provider == "fastembed":
        return build_fastembed_embedder(
            settings.embedding_model,
            dim=settings.embedding_dim,
            cache_dir=settings.fastembed_cache_dir,
            threads=settings.embedding_threads,
        )
    client = build_client(
        _secret(settings.openai_api_key),
        timeout_s=settings.embedding_timeout_s,
        max_retries=settings.openai_max_retries,
    )
    closers.append(client.close)
    return OpenAIEmbedder(client, model=settings.embedding_model, dim=settings.embedding_dim)


def build_chat_model(settings: Settings, closers: list[Callable[[], None]]) -> ChatModel:
    if settings.llm_provider == "fake":
        return FakeChatModel()
    assert settings.llm_model is not None  # noqa: S101 — guaranteed by Settings validation
    if settings.llm_provider == "openai_compatible":
        assert settings.llm_base_url is not None  # noqa: S101 — guaranteed by Settings validation
        base_url = str(settings.llm_base_url)
        client = build_client(
            _secret(settings.llm_api_key),
            base_url=base_url,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.openai_max_retries,
        )
        closers.append(client.close)
        return OpenAICompatibleChatModel(
            client,
            model=settings.llm_model,
            provider=settings.llm_base_url.host or base_url,
            temperature=settings.llm_temperature,
            reasoning_effort=settings.llm_reasoning_effort,
        )
    client = build_client(
        _secret(settings.openai_api_key),
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.openai_max_retries,
    )
    closers.append(client.close)
    return OpenAIChatModel(client, model=settings.llm_model, temperature=settings.llm_temperature)


def build_reranker(settings: Settings) -> Reranker | None:
    if settings.reranker == "none":
        return None
    return build_cohere_reranker(
        _secret(settings.cohere_api_key),
        model=settings.rerank_model,
        timeout_s=settings.rerank_timeout_s,
    )


def build_verifiers(
    settings: Settings, chat: ChatModel, closers: list[Callable[[], None]]
) -> tuple[Verifier | None, Verifier | None]:
    """(verifier, escalation). Escalation exists only for Jev, and only when Groq is set up."""
    if settings.verifier == "off":
        return None, None
    if settings.verifier == "fake":
        return FakeVerifier(), None
    if settings.verifier == "groq":
        return GroqVerifier(chat), None
    client = build_jev_client(settings.verify_timeout_s)
    closers.append(client.close)
    jev = JevVerifier(
        client,
        api_key=_secret(settings.openrouter_api_key),
        model=settings.jev_model,
        base_url=settings.openrouter_base_url,
    )
    return jev, GroqVerifier(chat) if settings.groq_configured else None


def _secret(value: SecretStr | None) -> str:
    assert value is not None  # noqa: S101 — guaranteed by Settings validation
    return value.get_secret_value()
