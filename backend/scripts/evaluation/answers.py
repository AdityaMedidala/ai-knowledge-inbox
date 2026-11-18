"""Generate answers once (temperature 0) and cache them in results/answers.json.

Every verifier is then judged on exactly these sentences, and the labels in REVIEW.md stay
valid. The relevance gate is off (min_partial = 0) so near-misses get answers too, which is how
we see whether the LLM refuses on its own; min_full stays at the configured value, so the
partial-mode hint reaches the prompt exactly as in production.
"""

import hashlib
import json
import time
from typing import Any

from app.config import Settings
from app.domain.errors import ProviderError
from app.providers.base import ChatMessage, ChatModel, Embedder
from app.services.answering import NOT_FOUND_ANSWER, AnsweringService, PreparedQuery
from app.services.prompting import SYSTEM_PROMPT
from app.services.retrieval import RetrievalConfig, RetrievalService
from app.services.verification import split_sentences
from app.store.repository import Repository
from scripts.evaluation.openrouter import estimate_and_gate
from scripts.evaluation.store import RESULTS_DIR, Question

ANSWERS = RESULTS_DIR / "answers.json"
TOP_K = 5
ASSUMED_OUTPUT_TOKENS = 1000  # reasoning model: generous, so the estimate errs high
RATE_LIMIT_WAIT_S = 30.0
RATE_LIMIT_TRIES = 6


def answering_retrieval(
    repo: Repository, embedder: Embedder, settings: Settings
) -> RetrievalService:
    config = RetrievalConfig(
        candidates=settings.retrieval_candidates,
        rrf_k=settings.rrf_k,
        max_chunks_per_item=settings.max_chunks_per_item,
        min_full=settings.relevance_min_full,
        min_partial=0.0,
    )
    return RetrievalService(repo, embedder, None, config)


def _complete(chat: ChatModel, messages: list[ChatMessage]) -> str:
    """Free-tier pacing: on a 429 wait and try again (the app itself never does this)."""
    for attempt in range(1, RATE_LIMIT_TRIES + 1):
        try:
            return chat.complete(messages)
        except ProviderError as exc:
            if exc.kind != "rate_limited" or attempt == RATE_LIMIT_TRIES:
                raise
            print(f"  rate limited, waiting {RATE_LIMIT_WAIT_S:.0f}s", flush=True)
            time.sleep(RATE_LIMIT_WAIT_S)
    raise AssertionError("unreachable")


def _llm_info(chat: ChatModel, route: str) -> dict[str, Any]:
    """Which route, upstream provider and system prompt produced the answer (OpenRouter
    reports its own provider)."""
    prompt_sha = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()[:8]
    if route == "groq":
        return {"route": "groq", "provider": "Groq", "prompt_sha": prompt_sha}
    usage = getattr(chat, "last_usage", None)
    return {
        "route": route,
        "prompt_sha": prompt_sha,
        "provider": getattr(chat, "last_provider", None),
        "input_tokens": usage[0] if usage else None,
        "output_tokens": usage[1] if usage else None,
    }


def _record(
    question: Question,
    prepared: PreparedQuery,
    text: str,
    keys: dict[str, str],
    llm: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": question.id,
        "kind": question.kind,
        "question": question.question,
        "mode": prepared.mode.value,
        "answer": text,
        "llm": llm,
        "sources": [
            {
                "ref": ref,
                "item": keys[s.chunk.item_id],
                "chunk_id": s.chunk.id,
                "section": s.chunk.section,
                "similarity": s.similarity,
                "text": s.chunk.text,
            }
            for ref, s in enumerate(prepared.sources, start=1)
        ],
    }


def generate(
    retrieval: RetrievalService,
    chat: ChatModel,
    keys: dict[str, str],
    questions: list[Question],
    pause_s: float,
    route: str,
    redo: frozenset[str] = frozenset(),
) -> int:
    """Answers questions not yet in answers.json, saving after each one (safe to resume).
    Prints a cost estimate first and stops if it is over budget. Returns how many were
    generated in this run."""
    answering = AnsweringService(retrieval, chat, question_max_chars=10_000)
    done = {a["id"]: a for a in load_answers()} if ANSWERS.exists() else {}
    done = {qid: a for qid, a in done.items() if qid not in redo}
    order = [q.id for q in questions]
    todo = [q for q in questions if q.id not in done]
    prepared_all = {q.id: answering.prepare(q.question, top_k=TOP_K) for q in todo}
    prompts = [
        "\n".join(m.content for m in p.messages) for p in prepared_all.values() if p.messages
    ]
    estimate_and_gate(prompts, ASSUMED_OUTPUT_TOKENS, f"generate via {route}")
    generated = 0
    for question in todo:
        prepared = prepared_all[question.id]
        text = _complete(chat, prepared.messages) if prepared.messages else NOT_FOUND_ANSWER
        done[question.id] = _record(question, prepared, text, keys, _llm_info(chat, route))
        ANSWERS.parent.mkdir(parents=True, exist_ok=True)
        rows = [done[qid] for qid in order if qid in done]
        ANSWERS.write_text(json.dumps(rows, indent=2, ensure_ascii=False), "utf-8")
        generated += 1
        time.sleep(pause_s)
    return generated


def load_answers() -> list[dict[str, Any]]:
    if not ANSWERS.exists():
        raise SystemExit("no cached answers; run: make eval ARGS=generate")
    return json.loads(ANSWERS.read_text(encoding="utf-8"))


def plan_regeneration(
    retrieval: RetrievalService, questions: list[Question], old_split: dict[str, int]
) -> dict[str, Any]:
    """Which cached answers are stale: retrieved chunks changed (re-ingestion) or the answer
    now splits into a different number of sentences. Prints nothing; returns the plan."""
    answering = AnsweringService(retrieval, _NoChat(), question_max_chars=10_000)
    cached = {a["id"]: a for a in load_answers()}
    stale: dict[str, list[str]] = {}
    prompts = []
    for question in questions:
        answer = cached.get(question.id)
        if answer is None:
            continue
        prepared = answering.prepare(question.question, top_k=TOP_K)
        now = [" ".join(s.chunk.text.split()) for s in prepared.sources]
        before = [" ".join(s["text"].split()) for s in answer["sources"]]
        reasons = []
        if now != before:
            reasons.append("chunks")
        if len(split_sentences(answer["answer"])) != old_split.get(question.id, 0):
            reasons.append("split")
        if reasons:
            stale[question.id] = reasons
            prompts.append("\n".join(m.content for m in prepared.messages or []))
    return {"stale": stale, "prompts": prompts}


class _NoChat:
    """prepare() never calls the model; this makes that explicit."""

    def complete(self, messages: list[ChatMessage]) -> str:
        raise AssertionError("planning must not call the LLM")

    def stream(self, messages: list[ChatMessage]) -> Any:
        raise AssertionError("planning must not call the LLM")
