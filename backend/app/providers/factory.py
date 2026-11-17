"""Build providers once from settings (called in lifespan) and close them on shutdown."""

from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import SecretStr

from app.config import Settings
from app.providers.base import ChatModel, Embedder, Reranker
from app.providers.cohere_reranker import build_cohere_reranker
from app.providers.fakes import FakeChatModel, FakeEmbedder
from app.providers.openai_provider import OpenAIChatModel, OpenAIEmbedder, build_client


@dataclass(slots=True)
class Providers:
    embedder: Embedder
    chat: ChatModel
    reranker: Reranker | None
    closers: list[Callable[[], None]] = field(default_factory=list)

    def close(self) -> None:
        for close in self.closers:
            close()


def build_providers(settings: Settings) -> Providers:
    closers: list[Callable[[], None]] = []
    return Providers(
        embedder=build_embedder(settings, closers),
        chat=build_chat_model(settings, closers),
        reranker=build_reranker(settings),
        closers=closers,
    )


def build_embedder(settings: Settings, closers: list[Callable[[], None]]) -> Embedder:
    if settings.embedding_provider == "fake":
        return FakeEmbedder(settings.embedding_dim)
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
    client = build_client(
        _secret(settings.openai_api_key),
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.openai_max_retries,
    )
    closers.append(client.close)
    assert settings.llm_model is not None  # noqa: S101 — guaranteed by Settings validation
    return OpenAIChatModel(client, model=settings.llm_model, temperature=settings.llm_temperature)


def build_reranker(settings: Settings) -> Reranker | None:
    if settings.reranker == "none":
        return None
    return build_cohere_reranker(
        _secret(settings.cohere_api_key),
        model=settings.rerank_model,
        timeout_s=settings.rerank_timeout_s,
    )


def _secret(value: SecretStr | None) -> str:
    assert value is not None  # noqa: S101 — guaranteed by Settings validation
    return value.get_secret_value()
