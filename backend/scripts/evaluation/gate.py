"""Relevance gate sweep: top cosine similarity per question, then rates at each threshold.

The app answers when the best similarity is >= RELEVANCE_MIN_PARTIAL (full or partial mode), so
that single threshold is what decides answer vs refusal.
"""

from typing import Any

from app.config import Settings
from app.providers.base import Embedder
from app.services.retrieval import RetrievalConfig, RetrievalService
from app.store.repository import Repository
from scripts.evaluation.store import Question

THRESHOLDS = [round(0.50 + 0.025 * i, 3) for i in range(15)]  # 0.50 .. 0.85


def retrieval_without_gate(
    repo: Repository, embedder: Embedder, settings: Settings
) -> RetrievalService:
    config = RetrievalConfig(
        candidates=settings.retrieval_candidates,
        rrf_k=settings.rrf_k,
        max_chunks_per_item=settings.max_chunks_per_item,
        min_full=0.0,
        min_partial=0.0,
    )
    return RetrievalService(repo, embedder, None, config)


def collect(
    service: RetrievalService, keys: dict[str, str], questions: list[Question]
) -> list[dict[str, Any]]:
    """Retrieve with the gate disabled and record the best similarity and its item."""
    rows = []
    for question in questions:
        chunks = service.retrieve(question.question, top_k=5).chunks
        scored = [(c.similarity, keys[c.chunk.item_id]) for c in chunks if c.similarity is not None]
        similarity, item = max(scored, default=(0.0, None))
        rows.append(
            {
                "id": question.id,
                "kind": question.kind,
                "question": question.question,
                "top_similarity": round(similarity, 4),
                "top_item": item,
                "source_items": sorted({keys[c.chunk.item_id] for c in chunks}),
                "expected_items": question.expected_items,
            }
        )
    return rows


def sweep(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """wrong-answer rate = questions answered wrongly (should refuse, or no expected item among
    the top-5 sources the LLM sees) / all questions.
    refusal rate = answerable questions refused / answerable questions."""
    answerable = [r for r in rows if r["expected_items"]]
    table = []
    for threshold in THRESHOLDS:
        wrong = refused = 0
        for row in rows:
            answered = row["top_similarity"] >= threshold
            if not row["expected_items"]:
                wrong += answered
            elif not answered:
                refused += 1
            elif not set(row["expected_items"]) & set(row["source_items"]):
                wrong += 1
        near_miss = sum(
            1 for r in rows if r["kind"] == "near_miss" and r["top_similarity"] >= threshold
        )
        table.append(
            {
                "threshold": threshold,
                "wrong_answer_rate": wrong / len(rows),
                "refusal_rate": refused / len(answerable),
                "near_miss_answered": near_miss,
            }
        )
    return table


def recommend(table: list[dict[str, Any]]) -> dict[str, Any]:
    """Lowest wrong + refusal (equal cost); ties go to the stricter threshold."""
    return min(table, key=lambda r: (r["wrong_answer_rate"] + r["refusal_rate"], -r["threshold"]))
