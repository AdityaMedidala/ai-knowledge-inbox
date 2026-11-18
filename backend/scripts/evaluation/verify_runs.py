"""`make eval ARGS="verify <backend> --run N"`: one paid verifier run over the frozen answers,
after printing its estimated cost (stops unless it is under the budget).

Backends:
  llm      the app's Groq verifier prompt on LLM_MODEL, called through OpenRouter pinned to the
           Groq provider (eval-only route). Its latency is OpenRouter's, not Groq's.
  jev      TypeSafe Jev via OpenRouter's Decisions API.
  jev+esc  Jev; verdicts below VERIFY_ESCALATE_BELOW are re-checked by `llm`.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.verification import Claim
from app.providers.base import Verifier
from app.providers.groq_verifier import GroqVerifier, build_prompt
from app.providers.jev_verifier import JevVerifier, build_jev_client
from app.services.verification import build_claims
from scripts.evaluation import verify, verify_metrics
from scripts.evaluation.adjudication import gold
from scripts.evaluation.answers import load_answers
from scripts.evaluation.labels import labelled_text, load_synthetic
from scripts.evaluation.openrouter import BUDGET_USD, build_openrouter_chat, estimate_and_gate
from scripts.evaluation.store import RESULTS_DIR, load_eval_set

BACKENDS = ("llm", "jev", "jev+esc")
LLM_OUTPUT_TOKENS = 600  # per call, generous (reasoning model)
# Jev's per-call price isn't published with the model: 10x the largest per-call cost it
# reported in the v1 runs (archive_v1/verify_jev.json, $0.0000589), so the estimate errs high.
JEV_COST_PER_CALL_USD = 0.0006


def result_path(backend: str, run: int) -> Path:
    return RESULTS_DIR / f"verify_{backend}_run{run}.json"


def _cited_claims(answers: list[dict[str, Any]], synthetic: Any) -> list[list[Claim]]:
    claims = []
    for answer in answers:
        chunks = [verify.as_source(s) for s in answer["sources"]]
        cited = [c for c in build_claims(labelled_text(answer, synthetic), chunks) if c.refs]
        if cited:
            claims.append(cited)
    return claims


def _estimate(backend: str, claims: list[list[Claim]]) -> None:
    prompts = ["\n".join(m.content for m in build_prompt(c)) for c in claims]
    if backend == "llm":
        estimate_and_gate(prompts, LLM_OUTPUT_TOKENS, "verify llm")
        return
    jev_cost = JEV_COST_PER_CALL_USD * len(claims)
    print(f"verify {backend}: {len(claims)} Jev calls, estimated at most ${jev_cost:.4f}")
    if jev_cost >= BUDGET_USD:
        raise SystemExit(f"Jev estimate ${jev_cost:.2f} is not under ${BUDGET_USD:.2f}; stopped")
    if backend == "jev+esc":  # worst case: every call escalates
        estimate_and_gate(prompts, LLM_OUTPUT_TOKENS, "  + escalation, worst case")


def _jev(settings: Settings, closers: list[Callable[[], None]]) -> JevVerifier:
    if settings.openrouter_api_key is None:
        raise SystemExit("OPENROUTER_API_KEY is not set in .env; Jev can't run.")
    client = build_jev_client(settings.verify_timeout_s)
    closers.append(client.close)
    return JevVerifier(
        client,
        api_key=settings.openrouter_api_key.get_secret_value(),
        model=settings.jev_model,
        base_url=settings.openrouter_base_url,
    )


def _llm(settings: Settings, closers: list[Callable[[], None]]) -> GroqVerifier:
    chat, client = build_openrouter_chat(settings)
    closers.append(client.close)
    return GroqVerifier(chat)


def run(backend: str, run_no: int, settings: Settings, pause_s: float) -> str:
    answers, synthetic = load_answers(), load_synthetic()
    sentences, _, unresolved = gold()
    if unresolved:
        raise SystemExit(f"{len(unresolved)} unresolved gold rows; adjudicate first")
    splits = {q.id: q.split or "?" for q in load_eval_set()[1]}
    _estimate(backend, _cited_claims(answers, synthetic))
    closers: list[Callable[[], None]] = []
    try:
        verifier: Verifier = (
            _llm(settings, closers) if backend == "llm" else _jev(settings, closers)
        )
        escalation = _llm(settings, closers) if backend == "jev+esc" else None
        service = verify.make_service(verifier, escalation, settings.verify_escalate_below)
        result = verify.run_backend(
            backend, service, answers, synthetic, sentences, splits, pause_s
        )
    finally:
        for close in closers:
            close()
    result.update(run=run_no, escalate_below=settings.verify_escalate_below)
    result_path(backend, run_no).write_text(json.dumps(result, indent=1), "utf-8")
    m = verify_metrics.run_metrics(result)
    return (
        f"{backend} run {run_no}: agreement {m['agreement']:.1%} on {m['sentences']} sentences; "
        f"unsupported let through {m['let_through']}/{m['unsupported']}; failed calls "
        f"{m['failed_calls']}/{m['calls']} (retries {m['retries']}); escalated {m['escalated']}; "
        f"median {m['median_ms']:.0f} ms"
    )
