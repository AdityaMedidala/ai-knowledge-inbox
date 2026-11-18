"""Evaluation harness. Real network calls (except where noted); not part of pytest.

    make eval ARGS=snapshot      # fetch the URL items once into eval/corpus/ (network, free)
    make eval ARGS=split         # assign the stratified dev/test split (offline)
    make eval ARGS=check         # ingest the corpus, check every evidence string (offline)
    make eval ARGS=ablation      # vector vs BM25 vs RRF hybrid, chunk-level (free)
    make eval ARGS=gate          # cosine gate sweep (embeddings only, free)
    make eval ARGS=generate      # cache answers at temperature 0 (LLM calls)
    make eval ARGS="verify llm --run 1"   # or jev, jev+esc; paid: prints cost estimate first
    make eval ARGS=report        # detailed tables: eval/results/TABLES.md (offline)
    make eval ARGS=review        # write eval/REVIEW.md from cached answers + labels (offline)
    make eval ARGS=blind         # blind parts for labeller B in eval/blind/ (offline)
    make eval ARGS="import-labels --model gemini-…"   # read eval/blind/returned/*.md (offline)
    make eval ARGS=disagreements # A vs B: eval/DISAGREEMENTS.md + agreement table (offline)
    make eval ARGS="adjudicate a16.2=unsupported --reason adjudicated"   # set finals (offline)
    make eval ARGS="tune --kind conflicting"   # dev-only prompt check (LLM calls)

Items are ingested into a fresh temp DB on every run, through the app's real ingestion path.
Full outputs go to eval/results/; the console gets summaries only.
"""

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from app.config import Settings
from app.logging import configure_logging
from app.providers.factory import build_providers
from app.services.chunker import ChunkLimits
from scripts.evaluation import (
    ablation,
    adjudication,
    answers,
    blind,
    dataset,
    gate,
    labels,
    report,
    review,
    tuning,
    verify_runs,
)
from scripts.evaluation.corpus import snapshot
from scripts.evaluation.openrouter import build_openrouter_chat, estimate_and_gate
from scripts.evaluation.store import RESULTS_DIR, build_store, load_eval_set

OFFLINE = (
    "report",
    "snapshot",
    "split",
    "review",
    "blind",
    "import-labels",
    "disagreements",
    "adjudicate",
)
COMMANDS = (*OFFLINE, "check", "ablation", "gate", "generate", "tune", "plan", "verify")
PLAN = RESULTS_DIR / "regen_plan.json"


def _save(name: str, data: Any) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    print(f"wrote eval/results/{name}")


def _offline(command: str, settings: Settings, model: str, extra: list[str], reason: str) -> None:
    if command == "snapshot":
        items, _ = load_eval_set()
        snapshot(
            items,
            timeout_s=settings.fetch_timeout_s,
            max_bytes=settings.fetch_max_bytes,
            redirects=settings.fetch_max_redirects,
        )
    elif command == "split":
        for (kind, split), n in sorted(dataset.assign_splits().items()):
            print(f"{kind:13} {split:4} {n}")
    elif command == "report":
        print(f"wrote {report.write_tables().name}")
    elif command == "blind":
        print(blind.write_parts())
    elif command == "import-labels":
        print(blind.import_labels(model))
    elif command == "disagreements":
        print("\n".join(adjudication.write_disagreements()))
    elif command == "adjudicate":
        updates = {}
        for pair in extra:
            row, _, label = pair.partition("=")
            updates[row] = (reason, label)
        print("\n".join(adjudication.write_disagreements(updates)))
    else:
        print(review.write_review())


def _plan(retrieval: Any, questions: list[Any]) -> None:
    """Stale answers + cost estimate. Old split = sentence rows labelled before the change."""
    old_split: dict[str, int] = {}
    for row in labels.load_proposed()["sentences"]:
        qid = row.split(".")[0]
        old_split[qid] = old_split.get(qid, 0) + 1
    plan = answers.plan_regeneration(retrieval, questions, old_split)
    by_reason: dict[str, list[str]] = {}
    for qid, reasons in plan["stale"].items():
        by_reason.setdefault("+".join(reasons), []).append(qid)
    for reason, ids in sorted(by_reason.items()):
        print(f"{reason:13} {len(ids):3}  {' '.join(ids)}")
    PLAN.write_text(json.dumps({"stale": plan["stale"]}, indent=2), "utf-8")
    estimate_and_gate(plan["prompts"], answers.ASSUMED_OUTPUT_TOKENS, "regenerate stale")


def _limits(settings: Settings) -> ChunkLimits:
    return ChunkLimits(
        max_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        max_block_tokens=settings.chunk_max_block_tokens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("pairs", nargs="*", help="adjudicate: row=label ...")
    parser.add_argument("--reason", default="adjudicated", help="adjudicate: reason column")
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between LLM calls")
    parser.add_argument("--split", default="dev", help="tune: dev or test")
    parser.add_argument("--tag", default="", help="tune: suffix for the output file name")
    parser.add_argument("--run", type=int, default=1, help="verify: run number (1..3)")
    parser.add_argument(
        "--oos", action="store_true", help="generate: out-of-scope answers, gate off (backstop)"
    )
    parser.add_argument(
        "--stale", action="store_true", help="generate: redo the answers in regen_plan.json"
    )
    parser.add_argument(
        "--model", default="gemini (version not recorded)", help="import-labels: B's model id"
    )
    parser.add_argument("--kind", default="conflicting", help="question kind for `tune`")
    parser.add_argument(
        "--llm",
        choices=["groq", "openrouter"],
        default="groq",
        help="eval only: call LLM_MODEL directly on Groq (app default) or through OpenRouter",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            db_path=Path(tmp) / "eval.db", verifier="off", log_level="WARNING", llm_temperature=0
        )
        configure_logging(settings.log_level, settings.log_json)
        if args.command == "verify":
            backend = args.pairs[0] if args.pairs else ""
            if backend not in verify_runs.BACKENDS:
                raise SystemExit(f"verify needs a backend: {', '.join(verify_runs.BACKENDS)}")
            print(verify_runs.run(backend, args.run, settings, args.pause))
            return
        if args.command in OFFLINE:
            _offline(args.command, settings, args.model, args.pairs, args.reason)
            return
        providers = build_providers(settings)
        closers = [providers.close]
        try:
            items, questions = load_eval_set()
            repo, keys = build_store(settings, providers.embedder, items)
            if args.command == "check":
                problems = dataset.check_evidence(repo, keys, questions, _limits(settings))
                print("\n".join(problems) or f"evidence ok for {len(questions)} questions")
            elif args.command == "ablation":
                rows = ablation.collect(repo, providers.embedder, settings, keys, questions)
                table = ablation.summarize(rows)
                _save("ablation.json", {"questions": rows, "summary": table})
                print("set           n  arm     hit@1 hit@5  MRR   (95% CI)       all@5")
                for t in table:
                    low, high = t["mrr_ci"]
                    print(
                        f"{t['set']:12} {t['n']:2}  {t['arm']:7} {t['hit@1']:.2f}  "
                        f"{t['hit@5']:.2f}  {t['mrr']:.2f} ({low:.2f}-{high:.2f})  {t['all@5']:.2f}"
                    )
                print("hybrid misses @5:", " ".join(ablation.misses(rows)) or "none")
            elif args.command == "gate":
                retrieval = gate.retrieval_without_gate(repo, providers.embedder, settings)
                _save("gate.json", gate.collect(retrieval, keys, questions))
            else:
                retrieval = answers.answering_retrieval(repo, providers.embedder, settings)
                chat = providers.chat
                if args.llm == "openrouter":
                    chat, client = build_openrouter_chat(settings)
                    closers.append(client.close)
                if args.command == "plan":
                    _plan(retrieval, questions)
                    return
                if args.command == "tune":
                    tuned = tuning.tune(retrieval, chat, questions, args.kind, args.split)
                    _save(f"tune_{args.kind}_{args.split}{args.tag}.json", tuned)
                    return
                if args.oos:
                    oos = [q for q in questions if q.kind == "out_of_scope"]
                    n = answers.generate(
                        retrieval, chat, keys, oos, args.pause, args.llm, path=answers.OOS_ANSWERS
                    )
                    print(f"generated {n} out-of-scope answers: eval/results/oos_answers.json")
                    return
                to_answer = [q for q in questions if q.kind != "out_of_scope"]
                redo = (
                    frozenset(json.loads(PLAN.read_text())["stale"]) if args.stale else frozenset()
                )
                n = answers.generate(
                    retrieval, chat, keys, to_answer, args.pause, args.llm, redo=redo
                )
                print(f"generated {n} answers; cache: eval/results/answers.json")
        finally:
            for close in closers:
                close()


if __name__ == "__main__":
    main()
