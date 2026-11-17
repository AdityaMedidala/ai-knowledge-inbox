"""Provider contracts. Services depend on these Protocols, never on a vendor SDK."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int  # position in the documents passed to rerank()
    score: float


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class ChatModel(Protocol):
    def complete(self, messages: Sequence[ChatMessage]) -> str: ...

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]:
        """Return results best first."""
        ...
