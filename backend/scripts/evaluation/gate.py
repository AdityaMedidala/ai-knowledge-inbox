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

THRESHOLDS = [round(0.50 + 0.01 * i, 3) for i in range(36)]  # 0.50 .. 0.85


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
                "split": question.split,
                "question": question.question,
                "top_similarity": round(similarity, 4),
                "top_item": item,
                "source_items": sorted({keys[c.chunk.item_id] for c in chunks}),
                "expected_items": question.expected_items,
            }
        )
    return rows


def sweep(rows: list[dict[str, Any]], thresholds: list[float] = THRESHOLDS) -> list[dict[str, Any]]:
    """Per threshold (answer when best similarity >= threshold):
    out-of-scope answered = out-of-scope questions let through / out-of-scope questions;
    refusal rate = questions with expected items refused / those questions;
    near-misses answered is reported, not optimised: they score inside the answerable range,
    so refusing them is the LLM's job (see the near-miss behaviour table);
    wrong source = answered, but no expected item among the top-5 sources."""
    oos = [r for r in rows if r["kind"] == "out_of_scope"]
    answerable = [r for r in rows if r["expected_items"]]
    table = []
    for threshold in thresholds:
        passed = [r for r in rows if r["top_similarity"] >= threshold]
        oos_answered = sum(r["kind"] == "out_of_scope" for r in passed)
        refused = len(answerable) - sum(bool(r["expected_items"]) for r in passed)
        table.append(
            {
                "threshold": threshold,
                "oos_answered_n": oos_answered,
                "refused_n": refused,
                "oos_answered": oos_answered / len(oos),
                "refusal_rate": refused / len(answerable),
                "near_miss_answered": sum(r["kind"] == "near_miss" for r in passed),
                "wrong_source": sum(
                    bool(r["expected_items"])
                    and not set(r["expected_items"]) & set(r["source_items"])
                    for r in passed
                ),
            }
        )
    return table


def recommend(table: list[dict[str, Any]]) -> dict[str, Any]:
    """Fewest wrong gate decisions, each question costing the same: out-of-scope questions let
    through + answerable questions refused. Ties take the middle of the tied range."""
    cost = [r["oos_answered_n"] + r["refused_n"] for r in table]
    best = min(cost)
    tied = [r for r, c in zip(table, cost, strict=True) if abs(c - best) < 1e-9]
    return tied[len(tied) // 2]


def choose_on_dev(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the threshold on dev only; report dev and test at that value."""
    dev = [r for r in rows if r["split"] == "dev"]
    test = [r for r in rows if r["split"] == "test"]
    best = recommend(sweep(dev))
    return {
        "threshold": best["threshold"],
        "dev": best,
        "test": sweep(test, [best["threshold"]])[0],
    }
