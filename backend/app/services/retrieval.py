"""Hybrid retrieval: vector + BM25 arms fused with RRF, optional rerank, diversity cap, gate.

Ported from Nova's final_retreval.py / retrieval_core.py. Unlike Nova, a chunk missing from an
arm contributes nothing for that arm (standard RRF) instead of a synthetic last-place rank.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.domain.models import KeywordHit, RetrievalMode, RetrievedChunk, VectorHit
from app.providers.base import Embedder, Reranker
from app.services.chunker import build_embed_text
from app.services.citations import make_snippet
from app.store.repository import Repository
from app.utils.text import match_key
from app.utils.timing import Timer


@dataclass(frozen=True, slots=True)
class RetrievalConfig:
    candidates: int  # per arm
    rrf_k: int
    max_chunks_per_item: int
    min_full: float
    min_partial: float


@dataclass(frozen=True, slots=True)
class FusedHit:
    chunk_id: int
    rrf: float
    vec_rank: int | None
    fts_rank: int | None
    similarity: float | None


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    mode: RetrievalMode
    chunks: list[RetrievedChunk]  # what the LLM sees, numbered [1..n] in this order
    candidates: list[RetrievedChunk]  # every fused candidate, for debug output
    embed_ms: float
    retrieve_ms: float
    rerank_ms: float


def fuse_rrf(
    vector_hits: Sequence[VectorHit], keyword_hits: Sequence[KeywordHit], k: int
) -> list[FusedHit]:
    """score = Σ 1 / (k + rank) over the arms that found the chunk; best first, ties by id."""
    vec = {hit.chunk_id: hit for hit in vector_hits}
    fts = {hit.chunk_id: hit for hit in keyword_hits}
    fused = []
    for chunk_id in dict.fromkeys([*vec, *fts]):
        v, f = vec.get(chunk_id), fts.get(chunk_id)
        score = (1 / (k + v.position) if v else 0.0) + (1 / (k + f.position) if f else 0.0)
        fused.append(
            FusedHit(
                chunk_id=chunk_id,
                rrf=score,
                vec_rank=v.position if v else None,
                fts_rank=f.position if f else None,
                similarity=v.similarity if v else None,
            )
        )
    return sorted(fused, key=lambda hit: (-hit.rrf, hit.chunk_id))


def drop_duplicate_text(chunks: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    """Keep order; drop a candidate whose text, or whose source-card snippet, matches a
    higher-ranked one from any item. Identical text gives an identical snippet, so keying on the
    snippet also catches near-copies that would show as two identical source cards."""
    seen: set[str] = set()
    kept = []
    for candidate in chunks:
        key = match_key(make_snippet(candidate.chunk.text))
        if key not in seen:
            seen.add(key)
            kept.append(candidate)
    return kept


def cap_per_item(chunks: Sequence[RetrievedChunk], max_per_item: int) -> list[RetrievedChunk]:
    """Keep order; drop chunks once their item already has `max_per_item` earlier ones."""
    kept: list[RetrievedChunk] = []
    per_item: dict[str, int] = {}
    for candidate in chunks:
        seen = per_item.get(candidate.chunk.item_id, 0)
        if seen < max_per_item:
            kept.append(candidate)
            per_item[candidate.chunk.item_id] = seen + 1
    return kept


def decide_mode(chunks: Sequence[RetrievedChunk], config: RetrievalConfig) -> RetrievalMode:
    scores = [c.score for c in chunks if c.score is not None]
    best = max(scores, default=None)
    if best is None or best < config.min_partial:
        return RetrievalMode.NONE
    return RetrievalMode.FULL if best >= config.min_full else RetrievalMode.PARTIAL


class RetrievalService:
    def __init__(
        self,
        repo: Repository,
        embedder: Embedder,
        reranker: Reranker | None,
        config: RetrievalConfig,
    ) -> None:
        self._repo = repo
        self._embedder = embedder
        self._reranker = reranker
        self._config = config

    def retrieve(self, question: str, top_k: int) -> RetrievalResult:
        with Timer() as embed_timer:
            query_embedding = self._embedder.embed_query(question)
        with Timer() as retrieve_timer:
            candidates = self._search(question, query_embedding)
        with Timer() as rerank_timer:
            ranked = self._rerank(question, candidates)
        unique = drop_duplicate_text(ranked)
        chunks = cap_per_item(unique, self._config.max_chunks_per_item)[:top_k]
        mode = decide_mode(chunks, self._config)
        return RetrievalResult(
            mode=mode,
            chunks=chunks if mode is not RetrievalMode.NONE else [],
            candidates=ranked,
            embed_ms=embed_timer.ms,
            retrieve_ms=retrieve_timer.ms,
            rerank_ms=rerank_timer.ms,
        )

    def _search(self, question: str, query_embedding: list[float]) -> list[RetrievedChunk]:
        n = self._config.candidates
        fused = fuse_rrf(
            self._repo.vector_search(query_embedding, n),
            self._repo.keyword_search(question, n),
            self._config.rrf_k,
        )
        records = self._repo.get_chunks_by_ids(hit.chunk_id for hit in fused)
        return [
            RetrievedChunk(
                chunk=records[hit.chunk_id],
                vec_rank=hit.vec_rank,
                fts_rank=hit.fts_rank,
                rrf=hit.rrf,
                similarity=hit.similarity,
            )
            for hit in fused
            if hit.chunk_id in records  # deleted between search and load
        ]

    def _rerank(self, question: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if self._reranker is None or not candidates:
            return candidates
        documents = [build_embed_text(c.chunk) for c in candidates]
        results = self._reranker.rerank(question, documents)
        return [replace(candidates[r.index], rerank=r.score) for r in results]
