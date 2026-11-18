"""Run one verifier backend over the cached answers (+ synthetic sentences) and record, per
answer, latency/cost/failures and, per sentence, the verdict next to the gold label.

Answers are frozen in results/answers.json, so every backend and every run judges exactly the
same sentences. Gold labels come from adjudication.gold(). A failed call is recorded as failed
(its cited sentences get verdict None); it never silently shrinks the denominator.
"""

import time
from typing import Any

from structlog.testing import capture_logs

from app.domain.models import ChunkRecord, ItemType, RetrievedChunk
from app.providers.base import Verifier
from app.services.verification import VerificationService
from app.utils.timing import Timer
from scripts.evaluation.adjudication import GoldRow
from scripts.evaluation.labels import labelled_text

CHAT_COMPLETED = "provider.chat_completed"
VERIFY_FAILED = "query.verify_failed"
VERIFY_RETRY = "query.verify_retry"


def as_source(saved: dict[str, Any]) -> RetrievedChunk:
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


def make_service(
    verifier: Verifier, escalation: Verifier | None, escalate_below: float
) -> VerificationService:
    return VerificationService(verifier, escalation, escalate_below=escalate_below)


def _sentence(g: GoldRow, answer_id: str, split: str, verdict: Any) -> dict[str, Any]:
    return {
        "row": g.row.row,
        "answer": answer_id,
        "split": split,
        "tag": g.row.tag,
        "error": g.error,
        "cited": bool(g.row.refs),
        "gold": g.label,
        "verdict": verdict.verdict.value if verdict else None,
        "confidence": verdict.confidence if verdict else None,
        "decided_by": verdict.decided_by if verdict else None,
    }


def run_backend(
    name: str,
    service: VerificationService,
    answers: list[dict[str, Any]],
    synthetic: dict[str, list[dict[str, str]]],
    gold: dict[str, GoldRow],
    splits: dict[str, str],
    pause_s: float,
) -> dict[str, Any]:
    calls, sentences = [], []
    for answer in answers:
        rows = sorted(
            (g for g in gold.values() if g.row.answer_id == answer["id"]),
            key=lambda g: g.row.index,
        )
        with capture_logs() as logs, Timer() as timer:
            result = service.verify(
                labelled_text(answer, synthetic), [as_source(s) for s in answer["sources"]]
            )
        events = [log["event"] for log in logs]
        failure = next((log for log in logs if log["event"] == VERIFY_FAILED), None)
        chat_logs = [log for log in logs if log["event"] == CHAT_COMPLETED]
        needs_call = any(g.row.refs for g in rows)
        calls.append(
            {
                "id": answer["id"],
                "split": splits[answer["id"]],
                "ms": timer.ms,
                "needs_call": needs_call,
                "ok": result is not None,
                "retries": events.count(VERIFY_RETRY),
                "error": f"{failure.get('kind')}: {failure.get('reason')}" if failure else None,
                "cost_usd": result.cost_usd if result else None,
                "escalated": result.escalated if result else 0,
                "input_tokens": sum(log.get("input_tokens") or 0 for log in chat_logs),
                "output_tokens": sum(log.get("output_tokens") or 0 for log in chat_logs),
            }
        )
        verdicts = {v.index: v for v in result.sentences} if result else {}
        sentences += [
            _sentence(g, answer["id"], splits[answer["id"]], verdicts.get(g.row.index))
            for g in rows
        ]
        if needs_call:
            time.sleep(pause_s)
    return {"backend": name, "calls": calls, "sentences": sentences}
