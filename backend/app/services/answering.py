"""Question → retrieval → prompt → LLM → validated citations.

Split into prepare / stream / finish so the JSON endpoint and the SSE endpoint share one path:
the stream sends `prepared.sources` before any token, then calls `finish` with the full text.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from time import perf_counter

import structlog

from app.domain.errors import field_validation_error
from app.domain.models import RetrievalMode, RetrievedChunk
from app.domain.verification import VerificationResult
from app.providers.base import ChatMessage, ChatModel
from app.services.citations import Citation, build_citations
from app.services.prompting import build_messages
from app.services.retrieval import RetrievalResult, RetrievalService
from app.services.verification import VerificationService

logger = structlog.get_logger(__name__)

NOT_FOUND_ANSWER = "I couldn't find this in your saved items."


@dataclass(frozen=True, slots=True)
class QueryTimings:
    embed: float
    retrieve: float
    rerank: float
    generate: float
    total: float

    def as_dict(self) -> dict[str, float]:
        return {
            "embed": self.embed,
            "retrieve": self.retrieve,
            "rerank": self.rerank,
            "generate": self.generate,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True)
class PreparedQuery:
    retrieval: RetrievalResult
    messages: list[ChatMessage] | None  # None in mode none: the LLM must not be called
    started_at: float
    retrieved_at: float

    @property
    def mode(self) -> RetrievalMode:
        return self.retrieval.mode

    @property
    def sources(self) -> list[RetrievedChunk]:
        """Numbered sources: sources[n-1] is what the model cites as [n]."""
        return self.retrieval.chunks


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    mode: RetrievalMode
    citations: list[Citation]
    timings: QueryTimings
    candidates: list[RetrievedChunk]
    verification: VerificationResult | None = None  # None: off, mode none, or verifier failed


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


class AnsweringService:
    def __init__(
        self,
        retrieval: RetrievalService,
        chat: ChatModel,
        *,
        question_max_chars: int,
        verification: VerificationService | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._chat = chat
        self._question_max_chars = question_max_chars
        self._verification = verification

    def answer(self, question: str, top_k: int) -> Answer:
        prepared = self.prepare(question, top_k)
        if prepared.messages is None:
            return self.finish(prepared, NOT_FOUND_ANSWER)
        return self.finish(prepared, self._chat.complete(prepared.messages))

    def validate_question(self, question: str) -> None:
        """Raise VALIDATION_ERROR past QUESTION_MAX_CHARS (the schema only checks non-empty)."""
        if len(question) > self._question_max_chars:
            raise field_validation_error(
                "body.question",
                f"Question is too long ({len(question)} characters; the limit is "
                f"{self._question_max_chars}).",
                "string_too_long",
            )

    def prepare(self, question: str, top_k: int) -> PreparedQuery:
        self.validate_question(question)
        started_at = perf_counter()
        retrieval = self._retrieval.retrieve(question, top_k)
        messages = None
        if retrieval.mode is not RetrievalMode.NONE:
            messages = build_messages(question, retrieval.chunks, retrieval.mode)
        return PreparedQuery(retrieval, messages, started_at, perf_counter())

    def stream(self, prepared: PreparedQuery) -> Iterator[str]:
        """Answer tokens. In mode none, the fixed not-found answer as a single token."""
        if prepared.messages is None:
            yield NOT_FOUND_ANSWER
            return
        yield from self._chat.stream(prepared.messages)

    def finish(self, prepared: PreparedQuery, text: str) -> Answer:
        now = perf_counter()
        retrieval = prepared.retrieval
        citations = [] if prepared.messages is None else build_citations(text, prepared.sources)
        verification = None
        if prepared.messages is not None and self._verification is not None:
            verification = self._verification.verify(text, prepared.sources)
        timings = QueryTimings(
            embed=retrieval.embed_ms,
            retrieve=retrieval.retrieve_ms,
            rerank=retrieval.rerank_ms,
            generate=0.0 if prepared.messages is None else _ms(now - prepared.retrieved_at),
            total=_ms(perf_counter() - prepared.started_at),  # includes verification
        )
        logger.info(
            "query.answered",
            mode=retrieval.mode,
            n_candidates=len(retrieval.candidates),
            n_cited=len(citations),
            timings_ms=timings.as_dict(),
        )
        return Answer(text, retrieval.mode, citations, timings, retrieval.candidates, verification)
