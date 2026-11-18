"""Freeze generated answers once, then run each verifier backend over them against hand labels.

Answers are frozen (results/answers.json) so labels stay valid across runs. Labels may append
`inject` sentences — deliberately wrong or overreaching claims with citations — so every backend
is tested on unsupported sentences, which real answers rarely contain.
"""

import json
import time
from typing import Any

from structlog.testing import capture_logs

from app.domain.models import ChunkRecord, ItemType, RetrievedChunk
from app.providers.base import Verifier
from app.services.verification import VerificationService, split_sentences
from app.utils.timing import Timer
from scripts.evaluation.corpus import EVAL_DIR

LABELS = EVAL_DIR / "labels.json"

CHAT_COMPLETED = "provider.chat_completed"
VERIFY_FAILED = "query.verify_failed"


def labelled_text(answer: dict[str, Any], labels: dict[str, Any]) -> str:
    inject = labels.get(answer["id"], {}).get("inject", [])
    return "\n".join([answer["answer"], *inject])


def print_sentences(answers: list[dict[str, Any]], labels: dict[str, Any]) -> None:
    """Helper for hand-labelling: every sentence, numbered, with its refs."""
    for answer in answers:
        print(f"\n## {answer['id']} ({answer['kind']}) {answer['question']}")
        for source in answer["sources"]:
            print(f"  [{source['ref']}] {source['item']}: {source['text'][:160]}…")
        for index, (text, refs) in enumerate(split_sentences(labelled_text(answer, labels))):
            print(f"  {index}. {refs} {text}")


def _source(saved: dict[str, Any]) -> RetrievedChunk:
    record = ChunkRecord(
        id=saved["ref"],
        item_id=saved["item"],
        ordinal=0,
        section=None,
        context_header="",
        text=saved["text"],
        token_count=0,
        item_title=saved["item"],
        item_type=ItemType.NOTE,
        source_url=None,
    )
    return RetrievedChunk(record, vec_rank=None, fts_rank=None, rrf=0.0, similarity=None)


def run_backend(
    name: str,
    service: VerificationService,
    answers: list[dict[str, Any]],
    pause_s: float,
) -> dict[str, Any]:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))
    runs, sentences = [], []
    for answer in answers:
        if answer["id"] not in labels:
            continue
        expected = labels[answer["id"]]["verdicts"]
        sources = [_source(s) for s in answer["sources"]]
        with capture_logs() as logs, Timer() as timer:
            result = service.verify(labelled_text(answer, labels), sources)
        chat_logs = [log for log in logs if log["event"] == CHAT_COMPLETED]
        failure = next((log for log in logs if log["event"] == VERIFY_FAILED), None)
        runs.append(
            {
                "id": answer["id"],
                "ms": timer.ms,
                "ok": result is not None,
                "called": result is not None and any(v.refs for v in result.sentences),
                "error": f"{failure.get('kind')}: {failure.get('reason')}" if failure else None,
                "cost_usd": result.cost_usd if result else None,
                "escalated": result.escalated if result else 0,
                "input_tokens": sum(log.get("input_tokens") or 0 for log in chat_logs),
                "output_tokens": sum(log.get("output_tokens") or 0 for log in chat_logs),
            }
        )
        for verdict in result.sentences if result else []:
            sentences.append(
                {
                    "id": answer["id"],
                    "index": verdict.index,
                    "sentence": verdict.sentence,
                    "cited": bool(verdict.refs),
                    "label": expected[verdict.index],
                    "verdict": verdict.verdict.value,
                    "decided_by": verdict.decided_by,
                    "confidence": verdict.confidence,
                }
            )
        print(f"{name}: verified {answer['id']} in {timer.ms:.0f} ms", flush=True)
        time.sleep(pause_s)
    return {"backend": name, "runs": runs, "sentences": sentences}


def make_service(
    verifier: Verifier, escalation: Verifier | None, escalate_below: float
) -> VerificationService:
    return VerificationService(verifier, escalation, escalate_below=escalate_below)
