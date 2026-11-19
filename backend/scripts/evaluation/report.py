"""Detailed tables from eval/results/*.json into eval/results/TABLES.md (eval/README.md is
the one-page summary and links here). Offline: `make eval ARGS=report`."""

import json
from pathlib import Path
from typing import Any

from scripts.evaluation import verify_metrics as vm
from scripts.evaluation.adjudication import gold
from scripts.evaluation.gate import choose_on_dev, sweep
from scripts.evaluation.store import RESULTS_DIR

TABLES = RESULTS_DIR / "TABLES.md"
BACKENDS = {
    "llm": "LLM verifier (openai/gpt-oss-120b via OpenRouter → Groq)",
    "jev": "Jev",
    "jev+esc": "Jev + escalation to the LLM verifier",
}
INJECTED = ("a16.2", "m02.1", "a22.0", "i03.2")  # real sentences repeating an injected claim
PLANTED = "c01.2"  # "500 pages" cited to the planted note: faithful, so gold = supported


def _load(name: str) -> Any | None:
    path = RESULTS_DIR / name
    return json.loads(path.read_text("utf-8")) if path.exists() else None


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _ablation(data: dict[str, Any]) -> list[str]:
    lines = [
        "## Retrieval ablation (chunk-level, same per-item cap for every arm)",
        "",
        "| set | n | arm | hit@1 | hit@5 | MRR (95% CI) | all evidence in top 5 |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in data["summary"]:
        low, high = t["mrr_ci"]
        lines.append(
            f"| {t['set']} | {t['n']} | {t['arm']} | {t['hit@1']:.2f} | {t['hit@5']:.2f} | "
            f"{t['mrr']:.2f} ({low:.2f}-{high:.2f}) | {t['all@5']:.2f} |"
        )
    return [*lines, ""]


def _gate(rows: list[dict[str, Any]]) -> list[str]:
    chosen = choose_on_dev(rows)["threshold"]
    lines = [
        f"## Relevance gate (bge-small cosine), chosen on dev: {chosen:.2f}",
        "",
        "Cost = out-of-scope answered + answerable refused (one per question).",
        "",
        "| threshold | dev OOS answered | dev refused | test OOS answered | test refused | "
        "near-misses answered (all) |",
        "|---|---|---|---|---|---|",
    ]
    dev = sweep([r for r in rows if r["split"] == "dev"])
    test = sweep([r for r in rows if r["split"] == "test"])
    for d, t, f in zip(dev, test, sweep(rows), strict=True):
        if 0.55 <= d["threshold"] <= 0.75:
            mark = " ←" if d["threshold"] == chosen else ""
            lines.append(
                f"| {d['threshold']:.2f}{mark} | {d['oos_answered_n']} | {d['refused_n']} | "
                f"{t['oos_answered_n']} | {t['refused_n']} | {f['near_miss_answered']} |"
            )
    lines += ["", "| question | kind | split | top similarity |", "|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["top_similarity"])[:16]:
        lines.append(f"| {r['id']} | {r['kind']} | {r['split']} | {r['top_similarity']:.3f} |")
    return [*lines, ""]


def _verifier_row(name: str, run: dict[str, Any]) -> str:
    m = vm.run_metrics(run)
    low, high = vm.agreement_ci([run])
    tags = " / ".join(f"{m['by_tag'][t]['let_through']} of {m['by_tag'][t]['n']}" for t in vm.TAGS)
    return (
        f"| {BACKENDS[name]} | {_pct(m['agreement'])} ({_pct(low)}-{_pct(high)}) | "
        f"{m['let_through']} of {m['unsupported']} / {tags} | "
        f"{m['partial_as_supported']} of {m['partial']} | {m['failed_calls']} of {m['calls']} | "
        f"{m['retries']} | {m['escalated']} | {m['median_ms']:.0f} / {m['p95_ms']:.0f} ms | "
        f"${m['cost_per_100']:.4f} |"
    )


def _verifiers(runs: dict[str, dict[str, Any]]) -> list[str]:
    n = vm.run_metrics(next(iter(runs.values())))["sentences"]
    lines = [
        f"## Verifiers (one run each; {n} cited sentences with gold labels)",
        "",
        "| backend | agreement (95% CI) | unsupported let through: all / blatant / subtle / "
        "real | partial passed as supported | failed calls | retries | escalated | "
        "median / p95 latency | cost per 100 answers |",
        "|---|---|---|---|---|---|---|---|---|",
        *(_verifier_row(name, run) for name, run in runs.items()),
        "",
        "Missed unsupported sentences (verdict `supported`, gold `unsupported`):",
        "",
    ]
    for name, run in runs.items():
        missed = [
            f"{s['row']} ({s['tag']}{', ' + s['error'] if s['error'] else ''})"
            for s in vm.scored(run)
            if s["gold"] == "unsupported" and s["verdict"] == "supported"
        ]
        lines.append(f"- {name}: {', '.join(missed) or 'none'}")
    lines += [
        "",
        "Injected-claim and planted-fact sentences:",
        "",
        "| row | gold | " + " | ".join(runs) + " |",
        "|---|---|" + "---|" * len(runs),
    ]
    by_row = {name: {s["row"]: s for s in run["sentences"]} for name, run in runs.items()}
    for row in (*INJECTED, PLANTED):
        cells = [by_row[name].get(row) for name in runs]
        if cells[0] is None:
            continue
        shown = [str(s["verdict"]) if s and s["cited"] else "uncited (rule)" for s in cells]
        lines.append(f"| {row} | {cells[0]['gold']} | " + " | ".join(shown) + " |")
    return [*lines, ""]


def _escalation(runs: dict[str, dict[str, Any]]) -> list[str]:
    if "jev" not in runs or "llm" not in runs:
        return []
    dev = vm.escalation_curve([runs["jev"]], [runs["llm"]], "dev")
    test = vm.escalation_curve([runs["jev"]], [runs["llm"]], "test")
    best = vm.recommend_escalation(dev)
    lines = [
        f"## VERIFY_ESCALATE_BELOW, replayed offline; chosen on dev: {best['threshold']:.2f}",
        "",
        "| threshold | dev accuracy | dev escalated | test accuracy | test escalated |",
        "|---|---|---|---|---|",
    ]
    for d, t in zip(dev, test, strict=True):
        mark = " ←" if d["threshold"] == best["threshold"] else ""
        lines.append(
            f"| {d['threshold']:.2f}{mark} | {_pct(d['accuracy'])} | {_pct(d['escalated'])} | "
            f"{_pct(t['accuracy'])} | {_pct(t['escalated'])} |"
        )
    return [*lines, ""]


def write_tables() -> Path:
    lines = [
        "# Evaluation tables",
        "",
        "Generated by `make eval ARGS=report`. Summary: [../README.md](../README.md).",
        "",
    ]
    if (ablation := _load("ablation.json")) is not None:
        lines += _ablation(ablation)
    if (gate_rows := _load("gate.json")) is not None:
        lines += _gate(gate_rows)
    runs = {name: r for name in BACKENDS if (r := _load(f"verify_{name}_run1.json"))}
    if runs:
        lines += _verifiers(runs) + _escalation(runs)
    sentences, questions, unresolved = gold()
    lines.append(
        f"Gold labels: {len(sentences)} sentences, {len(questions)} questions, "
        f"{len(unresolved)} unresolved."
    )
    TABLES.write_text("\n".join(lines) + "\n", "utf-8")
    return TABLES
