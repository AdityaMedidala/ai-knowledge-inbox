"""Retrieval ablation (no LLM, free): vector-only vs BM25-only vs RRF hybrid.

Scored at chunk level: a retrieved chunk is relevant when it contains the question's evidence
string for that item (eval_set.json `evidence`, matched after normalize()). Every arm gets the
same per-item diversity cap the app applies, so only the ranking differs.
"""

import random
from typing import Any

from app.config import Settings
from app.providers.base import Embedder
from app.services.retrieval import fuse_rrf
from app.store.repository import Repository
from scripts.evaluation.store import Question, normalize

ARMS = ("vector", "bm25", "hybrid")
KINDS = ("answerable", "multi_source")
BOOTSTRAP_SAMPLES = 2000
BOOTSTRAP_SEED = 7


def _rankings(
    repo: Repository, embedder: Embedder, settings: Settings, text: str
) -> dict[str, list[int]]:
    n = settings.retrieval_candidates
    vector = repo.vector_search(embedder.embed_query(text), n)
    keyword = repo.keyword_search(text, n)
    return {
        "vector": [h.chunk_id for h in vector],
        "bm25": [h.chunk_id for h in keyword],
        "hybrid": [h.chunk_id for h in fuse_rrf(vector, keyword, settings.rrf_k)],
    }


def _capped(ids: list[int], item_of: dict[int, str], cap: int) -> list[int]:
    kept: list[int] = []
    seen: dict[str, int] = {}
    for chunk_id in ids:
        item = item_of[chunk_id]
        if seen.get(item, 0) < cap:
            kept.append(chunk_id)
            seen[item] = seen.get(item, 0) + 1
    return kept


def collect(
    repo: Repository,
    embedder: Embedder,
    settings: Settings,
    keys: dict[str, str],
    questions: list[Question],
) -> list[dict[str, Any]]:
    """Per question and arm: the 1-based rank of the first chunk holding each evidence item."""
    rows = []
    for question in (q for q in questions if q.kind in KINDS and q.evidence):
        ranked = _rankings(repo, embedder, settings, question.question)
        records = repo.get_chunks_by_ids({c for ids in ranked.values() for c in ids})
        item_of = {chunk_id: record.item_id for chunk_id, record in records.items()}
        needles = {item: normalize(text) for item, text in question.evidence.items()}
        row: dict[str, Any] = {"id": question.id, "kind": question.kind, "split": question.split}
        for arm, ids in ranked.items():
            top = _capped(ids, item_of, settings.max_chunks_per_item)
            ranks = {}
            for item, needle in needles.items():
                for rank, chunk_id in enumerate(top, start=1):
                    record = records[chunk_id]
                    if keys[record.item_id] == item and needle in normalize(record.text):
                        ranks[item] = rank
                        break
            row[arm] = ranks
        row["n_evidence"] = len(needles)
        rows.append(row)
    return rows


def scores(row: dict[str, Any], arm: str) -> dict[str, float]:
    ranks = list(row[arm].values())
    first = min(ranks, default=None)
    return {
        "hit@1": float(first == 1),
        "hit@5": float(first is not None and first <= 5),
        "mrr": 1 / first if first else 0.0,
        "all@5": float(len(ranks) == row["n_evidence"] and max(ranks) <= 5),
    }


def bootstrap_ci(values: list[float]) -> tuple[float, float]:
    rng = random.Random(BOOTSTRAP_SEED)  # noqa: S311 — reproducible bootstrap, not crypto
    means = sorted(
        sum(rng.choice(values) for _ in values) / len(values) for _ in range(BOOTSTRAP_SAMPLES)
    )
    return means[int(0.025 * BOOTSTRAP_SAMPLES)], means[int(0.975 * BOOTSTRAP_SAMPLES) - 1]


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per (question set, arm): mean metrics and a bootstrap 95% CI for MRR."""
    sets = {
        "answerable": [r for r in rows if r["kind"] == "answerable"],
        "multi_source": [r for r in rows if r["kind"] == "multi_source"],
        "all": rows,
    }
    table = []
    for name, subset in sets.items():
        for arm in ARMS:
            per_q = [scores(r, arm) for r in subset]
            mean = {m: sum(s[m] for s in per_q) / len(per_q) for m in per_q[0]}
            low, high = bootstrap_ci([s["mrr"] for s in per_q])
            table.append({"set": name, "n": len(subset), "arm": arm, **mean, "mrr_ci": [low, high]})
    return table


def misses(rows: list[dict[str, Any]], arm: str = "hybrid") -> list[str]:
    """Questions whose evidence is not in the arm's top 5 (for the report)."""
    return [r["id"] for r in rows if not scores(r, arm)["hit@5"]]
