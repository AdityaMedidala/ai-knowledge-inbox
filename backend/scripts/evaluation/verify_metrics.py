"""Metrics over verify_<backend>_run<n>.json files.

Scored sentences = cited sentences whose gold label is supported/partial/unsupported (uncited
ones are unsupported by rule and never sent to a backend). A sentence whose call failed counts
as a disagreement and is also reported under "failed", so failures never shrink denominators.
"""

import random
import statistics
from typing import Any

from scripts.evaluation.openrouter import GROQ_IN, GROQ_OUT

SCORED = frozenset({"supported", "partial", "unsupported"})
TAGS = ("blatant", "subtle", "real")
BOOTSTRAP_SAMPLES = 2000
SEED = 11
ESCALATE_GRID = [round(0.5 + 0.05 * i, 2) for i in range(10)]  # 0.50 .. 0.95


def scored(run: dict[str, Any], split: str | None = None) -> list[dict[str, Any]]:
    return [
        s
        for s in run["sentences"]
        if s["cited"] and s["gold"] in SCORED and (split is None or s["split"] == split)
    ]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[round(0.95 * (len(ordered) - 1))] if ordered else 0.0


def run_metrics(run: dict[str, Any]) -> dict[str, Any]:
    rows = scored(run)
    unsupported = [s for s in rows if s["gold"] == "unsupported"]
    calls = [c for c in run["calls"] if c["needs_call"]]
    ok_ms = [c["ms"] for c in calls if c["ok"]]
    llm_cost = sum(c["input_tokens"] * GROQ_IN + c["output_tokens"] * GROQ_OUT for c in calls)
    reported_cost = sum(c["cost_usd"] or 0.0 for c in calls)
    by_tag = {}
    for tag in TAGS:
        bad = [s for s in unsupported if s["tag"] == tag]
        by_tag[tag] = {"n": len(bad), "let_through": sum(s["verdict"] == "supported" for s in bad)}
    partial = [s for s in rows if s["gold"] == "partial"]
    return {
        "sentences": len(rows),
        "agreement": sum(s["verdict"] == s["gold"] for s in rows) / len(rows),
        "unsupported": len(unsupported),
        "let_through": sum(s["verdict"] == "supported" for s in unsupported),
        "by_tag": by_tag,
        "partial": len(partial),
        "partial_as_supported": sum(s["verdict"] == "supported" for s in partial),
        "failed_calls": sum(not c["ok"] for c in calls),
        "calls": len(calls),
        "failed_sentences": sum(s["verdict"] is None for s in rows),
        "retries": sum(c["retries"] for c in calls),
        "escalated": sum(c["escalated"] for c in calls),
        "median_ms": statistics.median(ok_ms) if ok_ms else 0.0,
        "p95_ms": _p95(ok_ms),
        "cost_per_100": (llm_cost / 1_000_000 + reported_cost) / max(len(calls), 1) * 100,
    }


def spread(values: list[float]) -> dict[str, float]:
    return {"mean": statistics.mean(values), "min": min(values), "max": max(values)}


def agreement_ci(runs: list[dict[str, Any]]) -> tuple[float, float]:
    """95% CI of the across-run mean agreement, resampling whole answers (sentences of one
    answer are not independent)."""
    answers = sorted({s["answer"] for s in scored(runs[0])})
    per_run = [
        {a: [s["verdict"] == s["gold"] for s in scored(r) if s["answer"] == a] for a in answers}
        for r in runs
    ]
    rng = random.Random(SEED)  # noqa: S311 — reproducible bootstrap, not crypto
    means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = [rng.choice(answers) for _ in answers]
        accs = []
        for table in per_run:
            hits = [h for a in sample for h in table[a]]
            accs.append(sum(hits) / len(hits))
        means.append(statistics.mean(accs))
    means.sort()
    return means[int(0.025 * BOOTSTRAP_SAMPLES)], means[int(0.975 * BOOTSTRAP_SAMPLES) - 1]


def escalation_curve(
    jev_runs: list[dict[str, Any]], llm_runs: list[dict[str, Any]], split: str
) -> list[dict[str, float]]:
    """Replay escalation offline: below threshold t take the LLM verifier's verdict for the same
    sentence (run i paired with run i), else Jev's. Accuracy and escalation rate per t."""
    curve = []
    for t in ESCALATE_GRID:
        accs, rates = [], []
        for jev, llm in zip(jev_runs, llm_runs, strict=True):
            llm_verdict = {s["row"]: s["verdict"] for s in llm["sentences"]}
            rows = scored(jev, split)
            low = {s["row"] for s in rows if s["confidence"] is None or s["confidence"] < t}
            final = [llm_verdict[s["row"]] if s["row"] in low else s["verdict"] for s in rows]
            accs.append(sum(f == s["gold"] for f, s in zip(final, rows, strict=True)) / len(rows))
            rates.append(len(low) / len(rows))
        curve.append(
            {"threshold": t, "accuracy": statistics.mean(accs), "escalated": statistics.mean(rates)}
        )
    return curve


def recommend_escalation(curve: list[dict[str, float]]) -> dict[str, float]:
    """Highest dev accuracy; ties go to the lower threshold (fewer escalations, cheaper)."""
    return max(curve, key=lambda r: (round(r["accuracy"], 6), -r["threshold"]))
