"""Evaluation harness. Real network calls (except where noted); not part of pytest.

    make eval ARGS=snapshot      # fetch the URL items once into eval/corpus/ (network, free)
    make eval ARGS=split         # assign the stratified dev/test split (offline)
    make eval ARGS=check         # ingest the corpus, check every evidence string (offline)
    make eval ARGS=gate          # cosine gate sweep (embeddings only, free)
    make eval ARGS=generate      # cache answers at temperature 0 (LLM calls)
    make eval ARGS=review        # write eval/REVIEW.md from cached answers + labels (offline)

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
from scripts.evaluation import answers, dataset, gate, review
from scripts.evaluation.corpus import snapshot
from scripts.evaluation.openrouter import build_openrouter_chat
from scripts.evaluation.store import RESULTS_DIR, build_store, load_eval_set

OFFLINE = ("snapshot", "split", "review")
COMMANDS = (*OFFLINE, "check", "gate", "generate")


def _save(name: str, data: Any) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    print(f"wrote eval/results/{name}")


def _offline(command: str, settings: Settings) -> None:
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
    else:
        print(review.write_review())


def _limits(settings: Settings) -> ChunkLimits:
    return ChunkLimits(
        max_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        max_block_tokens=settings.chunk_max_block_tokens,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--pause", type=float, default=2.0, help="seconds between LLM calls")
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
        if args.command in OFFLINE:
            _offline(args.command, settings)
            return
        providers = build_providers(settings)
        closers = [providers.close]
        try:
            items, questions = load_eval_set()
            repo, keys = build_store(settings, providers.embedder, items)
            if args.command == "check":
                problems = dataset.check_evidence(repo, keys, questions, _limits(settings))
                print("\n".join(problems) or f"evidence ok for {len(questions)} questions")
            elif args.command == "gate":
                retrieval = gate.retrieval_without_gate(repo, providers.embedder, settings)
                _save("gate.json", gate.collect(retrieval, keys, questions))
            else:
                retrieval = answers.answering_retrieval(repo, providers.embedder, settings)
                to_answer = [q for q in questions if q.kind != "out_of_scope"]
                chat = providers.chat
                if args.llm == "openrouter":
                    chat, client = build_openrouter_chat(settings)
                    closers.append(client.close)
                n = answers.generate(retrieval, chat, keys, to_answer, args.pause, args.llm)
                print(f"generated {n} answers; cache: eval/results/answers.json")
        finally:
            for close in closers:
                close()


if __name__ == "__main__":
    main()
