"""POST /query and /query/stream contract."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.domain.models import ItemType, RetrievalMode, RetrievedChunk
from app.schemas.verification import Verification
from app.services import answering, citations

TOP_K_DEFAULT = 5
TOP_K_MAX = 10

# Length beyond min_length=1 is checked against QUESTION_MAX_CHARS by the answering service.
QuestionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: QuestionText
    top_k: int = Field(default=TOP_K_DEFAULT, ge=1, le=TOP_K_MAX)
    debug: bool = Field(default=False, description="Include every fused candidate's scores.")


class Citation(BaseModel):
    """A numbered source. In `citations`, only the ones the answer actually cites."""

    ref: int = Field(description="The n in the answer's [n] markers.")
    item_id: str
    chunk_id: int
    title: str | None
    source_url: str | None
    item_type: ItemType
    section: str | None
    snippet: str = Field(description=f"≤{citations.SNIPPET_MAX_CHARS} characters of the chunk.")
    score: float | None = Field(
        description="Rerank score if a reranker is on, else cosine similarity; null when only "
        "keyword search found the chunk."
    )

    @classmethod
    def from_source(cls, ref: int, source: RetrievedChunk, snippet: str) -> "Citation":
        chunk = source.chunk
        return cls(
            ref=ref,
            item_id=chunk.item_id,
            chunk_id=chunk.id,
            title=chunk.item_title,
            source_url=chunk.source_url,
            item_type=chunk.item_type,
            section=chunk.section,
            snippet=snippet,
            score=source.score,
        )

    @classmethod
    def from_domain(cls, citation: citations.Citation) -> "Citation":
        return cls.from_source(citation.ref, citation.source, citation.snippet)


class QueryTimings(BaseModel):
    embed: float
    retrieve: float
    rerank: float
    generate: float
    total: float

    @classmethod
    def from_domain(cls, timings: answering.QueryTimings) -> "QueryTimings":
        return cls(**timings.as_dict())


class DebugCandidate(BaseModel):
    chunk_id: int
    vec_rank: int | None
    fts_rank: int | None
    rrf: float
    similarity: float | None
    rerank: float | None


class QueryDebug(BaseModel):
    candidates: list[DebugCandidate]


class QueryResponse(BaseModel):
    answer: str = Field(description="Markdown with inline [n] markers.")
    mode: RetrievalMode = Field(description="`none` means the LLM was not called.")
    citations: list[Citation]
    timings_ms: QueryTimings
    request_id: str | None
    verification: Verification | None = Field(
        default=None,
        description="Per-sentence check against the cited sources. Null when VERIFIER=off, "
        "in mode none, or when the verifier failed (the answer is still returned).",
    )
    debug: QueryDebug | None = Field(default=None, description="Only when debug=true.")


def numbered_sources(sources: list[RetrievedChunk]) -> list[Citation]:
    return [
        Citation.from_source(ref, source, citations.make_snippet(source.chunk.text))
        for ref, source in enumerate(sources, start=1)
    ]


def debug_info(candidates: list[RetrievedChunk]) -> QueryDebug:
    return QueryDebug(
        candidates=[
            DebugCandidate(
                chunk_id=c.chunk.id,
                vec_rank=c.vec_rank,
                fts_rank=c.fts_rank,
                rrf=c.rrf,
                similarity=c.similarity,
                rerank=c.rerank,
            )
            for c in candidates
        ]
    )
