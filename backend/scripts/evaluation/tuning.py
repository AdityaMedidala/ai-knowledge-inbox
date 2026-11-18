"""Dev-only prompt tuning: answer the dev questions of one kind with the current prompt and save
them next to the cached answers, without touching answers.json (which stays the test record)."""

from typing import Any

from app.providers.base import ChatModel
from app.services.answering import AnsweringService
from app.services.retrieval import RetrievalService
from scripts.evaluation.answers import TOP_K
from scripts.evaluation.openrouter import estimate_and_gate
from scripts.evaluation.store import Question


def tune(
    retrieval: RetrievalService, chat: ChatModel, questions: list[Question], kind: str
) -> list[dict[str, Any]]:
    answering = AnsweringService(retrieval, chat, question_max_chars=10_000)
    dev = [q for q in questions if q.kind == kind and q.split == "dev"]
    prepared = [(q, answering.prepare(q.question, top_k=TOP_K)) for q in dev]
    prompts = ["\n".join(m.content for m in p.messages or []) for _, p in prepared]
    estimate_and_gate(prompts, 1000, f"tune {kind} (dev only)")
    return [
        {"id": q.id, "question": q.question, "answer": chat.complete(p.messages)}
        for q, p in prepared
        if p.messages
    ]
