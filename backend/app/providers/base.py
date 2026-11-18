"""Provider contracts. Services depend on these Protocols, never on a vendor SDK."""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.domain.verification import Claim, VerifierRun


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Literal["system", "user"]
    content: str


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int  # position in the documents passed to rerank()
    score: float


class Embedder(Protocol):
    """Documents and queries are embedded separately: asymmetric models (bge) prefix them."""

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class ChatModel(Protocol):
    def complete(self, messages: Sequence[ChatMessage]) -> str: ...

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]: ...


class Reranker(Protocol):
    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]:
        """Return results best first."""
        ...


class Verifier(Protocol):
    """Judges answer sentences against their cited evidence. One call per batch of claims."""

    name: str

    def verify(self, claims: Sequence[Claim]) -> VerifierRun:
        """Return one judgement per claim, in the same order."""
        ...
