import math
from collections.abc import Sequence
from dataclasses import replace

import pytest

from app.domain.models import (
    ChunkRecord,
    ItemType,
    KeywordHit,
    RetrievalMode,
    RetrievedChunk,
    VectorHit,
)
from app.providers.base import RerankResult
from app.services.retrieval import (
    RetrievalConfig,
    RetrievalService,
    cap_per_item,
    decide_mode,
    drop_duplicate_text,
    fuse_rrf,
)
from app.store.repository import Repository
from tests.conftest import make_ready

CONFIG = RetrievalConfig(
    candidates=20, rrf_k=60, max_chunks_per_item=2, min_full=0.8, min_partial=0.5
)


class StubEmbedder:
    def __init__(self, query_vector: list[float]) -> None:
        self.query_vector = query_vector

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise AssertionError("not used by retrieval")

    def embed_query(self, text: str) -> list[float]:
        return self.query_vector


class ReverseReranker:
    """Scores the last candidate best, so a rerank visibly changes the order."""

    def rerank(self, query: str, documents: Sequence[str]) -> list[RerankResult]:
        n = len(documents)
        return [RerankResult(index=i, score=(i + 1) / n) for i in reversed(range(n))]


def candidate(
    chunk_id: int, item_id: str, similarity: float | None = 0.9, text: str | None = None
) -> RetrievedChunk:
    record = ChunkRecord(
        id=chunk_id,
        item_id=item_id,
        ordinal=0,
        section=None,
        context_header="",
        text=text if text is not None else f"chunk {chunk_id}",
        token_count=2,
        item_title=None,
        item_type=ItemType.NOTE,
        source_url=None,
    )
    return RetrievedChunk(record, vec_rank=1, fts_rank=None, rrf=0.0, similarity=similarity)


# --- pure functions -------------------------------------------------------------------------


def test_rrf_sums_reciprocal_ranks_across_arms() -> None:
    vector = [VectorHit(1, 1, 0.9), VectorHit(2, 2, 0.8)]
    keyword = [KeywordHit(2, 1, -5.0), KeywordHit(3, 2, -4.0)]
    fused = fuse_rrf(vector, keyword, k=60)
    by_id = {hit.chunk_id: hit for hit in fused}

    assert [hit.chunk_id for hit in fused] == [2, 1, 3]
    assert math.isclose(by_id[2].rrf, 1 / 62 + 1 / 61)
    assert math.isclose(by_id[1].rrf, 1 / 61)
    assert math.isclose(by_id[3].rrf, 1 / 62)
    assert (by_id[2].vec_rank, by_id[2].fts_rank, by_id[2].similarity) == (2, 1, 0.8)
    assert (by_id[3].vec_rank, by_id[3].similarity) == (None, None)


def test_cap_per_item_keeps_order_and_limits_each_item() -> None:
    chunks = [candidate(1, "a"), candidate(2, "a"), candidate(3, "a"), candidate(4, "b")]
    assert [c.chunk.id for c in cap_per_item(chunks, 2)] == [1, 2, 4]


@pytest.mark.parametrize(
    ("similarities", "mode"),
    [
        ([0.85, 0.3], RetrievalMode.FULL),
        ([0.6], RetrievalMode.PARTIAL),
        ([0.49], RetrievalMode.NONE),
        ([None], RetrievalMode.NONE),
        ([], RetrievalMode.NONE),
    ],
)
def test_relevance_gate_uses_best_score(
    similarities: list[float | None], mode: RetrievalMode
) -> None:
    chunks = [candidate(i, "a", s) for i, s in enumerate(similarities)]
    assert decide_mode(chunks, CONFIG) is mode


def test_rerank_score_overrides_similarity_for_the_gate() -> None:
    chunk = replace(candidate(1, "a", similarity=0.1), rerank=0.9)
    assert chunk.score == 0.9
    assert decide_mode([chunk], CONFIG) is RetrievalMode.FULL


# --- service over a real store --------------------------------------------------------------


def test_retrieve_ranks_nearest_first_and_caps_per_item(repo: Repository) -> None:
    near = make_ready(
        repo,
        [
            ("alpha one", [1, 0, 0, 0]),
            ("alpha two", [0.9, 0.1, 0, 0]),
            ("alpha three", [0.8, 0.2, 0, 0]),
        ],
    )
    far = make_ready(repo, [("beta", [0, 1, 0, 0])], content_hash="other")
    service = RetrievalService(repo, StubEmbedder([1, 0, 0, 0]), None, CONFIG)

    result = service.retrieve("alpha", top_k=5)

    assert result.mode is RetrievalMode.FULL
    assert [c.chunk.item_id for c in result.chunks] == [near.id, near.id, far.id]
    assert result.chunks[0].vec_rank == 1
    assert result.chunks[0].fts_rank is not None
    assert len(result.candidates) == 4


def test_retrieve_on_empty_inbox_is_mode_none(repo: Repository) -> None:
    service = RetrievalService(repo, StubEmbedder([1, 0, 0, 0]), None, CONFIG)
    result = service.retrieve("anything at all", top_k=5)
    assert (result.mode, result.chunks, result.candidates) == (RetrievalMode.NONE, [], [])


def test_retrieve_below_threshold_returns_no_chunks(repo: Repository) -> None:
    make_ready(repo, [("unrelated", [0, 1, 0, 0])])
    service = RetrievalService(repo, StubEmbedder([1, 0, 0, 0]), None, CONFIG)
    result = service.retrieve("question", top_k=5)
    assert result.mode is RetrievalMode.NONE
    assert result.chunks == []
    assert len(result.candidates) == 1  # still reported for debug


def test_reranker_reorders_candidates(repo: Repository) -> None:
    make_ready(repo, [("first", [1, 0, 0, 0]), ("second", [0.5, 0.5, 0, 0])])
    service = RetrievalService(repo, StubEmbedder([1, 0, 0, 0]), ReverseReranker(), CONFIG)
    result = service.retrieve("question", top_k=5)
    assert [c.chunk.text for c in result.chunks] == ["second", "first"]
    assert [c.rerank for c in result.chunks] == [1.0, 0.5]


def test_drop_duplicate_text_keeps_the_highest_ranked_copy() -> None:
    ranked = [
        candidate(1, "a", text="Lucia and Jason."),
        candidate(2, "b", text="Something else."),
        candidate(3, "a", text="  lucia AND\njason. "),
        candidate(4, "c", text="Lucia and Jason."),
    ]
    assert [c.chunk.id for c in drop_duplicate_text(ranked)] == [1, 2]


def test_retrieve_never_returns_two_chunks_with_the_same_text(repo: Repository) -> None:
    make_ready(repo, [("Lucia is the protagonist.", [1, 0, 0, 0])])
    make_ready(repo, [("Lucia is the protagonist.", [0.99, 0.01, 0, 0])], content_hash="copy")
    service = RetrievalService(repo, StubEmbedder([1, 0, 0, 0]), None, CONFIG)

    result = service.retrieve("Who is Lucia?", top_k=5)

    assert [c.chunk.text for c in result.chunks] == ["Lucia is the protagonist."]


def test_drop_duplicate_text_collapses_near_copies_that_would_show_the_same_card() -> None:
    shared = "Lucia fights for her family and lands in the Leonida Penitentiary. " * 6
    ranked = [
        candidate(1, "a", text=shared + "A life with Jason could be her way out."),
        candidate(2, "a", text=shared + "Home to the neon-soaked streets of Vice City."),
        candidate(3, "a", text="Jason grew up around grifters and crooks."),
    ]
    assert [c.chunk.id for c in drop_duplicate_text(ranked)] == [1, 3]
