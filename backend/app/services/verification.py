"""Check each answer sentence against the sources it cites. A failure never blocks the answer.

Flow: split the answer into sentences → uncited ones are `unsupported` with no backend call →
the verifier judges the rest in one call → for Jev, low-confidence verdicts are re-checked by
the escalation backend (Groq).
"""

import re
from collections.abc import Sequence

import structlog

from app.domain.errors import ProviderError
from app.domain.models import RetrievedChunk
from app.domain.verification import (
    NO_CITATION,
    Claim,
    Judgement,
    SentenceVerdict,
    Verdict,
    VerificationResult,
)
from app.providers.base import Verifier
from app.services.citations import MARKER, parse_refs
from app.utils.timing import Timer

logger = structlog.get_logger(__name__)

ESCALATING_BACKEND = "jev"
_SENTENCE = re.compile(rf".+?(?:[.!?]+(?:\s*{MARKER.pattern})*(?=\s|$)|$)")
_FENCE = "```"
_SKIP_LINE = re.compile(r"^(#|\|?\s*:?-{3,})")
_BOLD_LABEL = re.compile(r"^\*\*[^*]+\*\*:?$")
_LIST_MARK = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_MARKER_WITH_SPACE = re.compile(rf"\s*{MARKER.pattern}")
# "Sources: [1][2]", "**Sources**: [1]", "[1][3]" alone: refs for the sentence above, not a claim.
_REFS_ONLY = re.compile(
    rf"^(?:\**\s*sources?\s*\**\s*:?\s*\**)?(?:\s*{MARKER.pattern}[\s.,;]*)*$", re.I
)
# Dots of these abbreviations never end a sentence; a.m./p.m./etc./vs. only when the text
# continues in lower case or with a digit ("10:30 a.m. on Tuesdays").
_ABBREVIATION = re.compile(
    r"\b(?:[eE]\.g|[iI]\.e|cf)\.|\b(?:a\.m|p\.m|A\.M|P\.M|etc|vs|approx)\.(?=\s+[a-z0-9(])"
)
_HIDDEN_DOT = "\x00"
_MIN_CLAIM_WORDS = 3


def _protect_abbreviations(line: str) -> str:
    return _ABBREVIATION.sub(lambda m: m.group(0).replace(".", _HIDDEN_DOT), line)


def _is_bold_claim(line: str, is_list_item: bool) -> bool:
    """A bold-only list item of 3+ words is a claim ("1. **Standard library imports**");
    short ones and those ending in ':' are sub-headings ("- **`asyncio.Queue`**")."""
    is_label = line.rstrip("*").endswith(":")
    return is_list_item and not is_label and len(line.split()) >= _MIN_CLAIM_WORDS


def split_sentences(answer: str) -> list[tuple[str, list[int]]]:
    """(display text, refs) per sentence. Headings, fenced code, table rules and bold-only
    label lines (**Overview**, short bold list items) are not claims and are skipped. A line
    holding only citations ("[1][3]", "Sources: [1]") adds its refs to the sentence before it."""
    sentences: list[tuple[str, list[int]]] = []
    in_fence = False
    for raw_line in answer.splitlines():
        stripped = raw_line.strip()
        line = _LIST_MARK.sub("", stripped)
        is_list_item = line != stripped
        if line.startswith(_FENCE):
            in_fence = not in_fence
            continue
        if in_fence or not line or _SKIP_LINE.match(line):
            continue
        if _REFS_ONLY.match(line):
            if sentences:
                text, refs = sentences[-1]
                sentences[-1] = (text, list(dict.fromkeys([*refs, *parse_refs(line)])))
            continue
        if _BOLD_LABEL.match(line) and not _is_bold_claim(line, is_list_item):
            continue
        for match in _SENTENCE.finditer(_protect_abbreviations(line)):
            piece = match.group(0).strip().replace(_HIDDEN_DOT, ".")
            text = " ".join(_MARKER_WITH_SPACE.sub("", piece).replace("**", "").split())
            if text:
                sentences.append((text, parse_refs(piece)))
    return sentences


def build_claims(answer: str, sources: Sequence[RetrievedChunk]) -> list[Claim]:
    """Refs that don't name a real source are dropped, so such sentences count as uncited."""
    claims = []
    for index, (text, refs) in enumerate(split_sentences(answer)):
        valid = tuple(ref for ref in refs if 1 <= ref <= len(sources))
        evidence = tuple(sources[ref - 1].chunk.text for ref in valid)
        claims.append(Claim(index=index, sentence=text, refs=valid, evidence=evidence))
    return claims


class VerificationService:
    def __init__(
        self, verifier: Verifier, escalation: Verifier | None, *, escalate_below: float
    ) -> None:
        self._verifier = verifier
        self._escalation = escalation
        self._escalate_below = escalate_below

    def verify(self, answer: str, sources: Sequence[RetrievedChunk]) -> VerificationResult | None:
        """None when the verifier failed (logged); the caller returns the answer unverified."""
        claims = build_claims(answer, sources)
        cited = [claim for claim in claims if claim.refs]
        with Timer() as timer:
            try:
                judgements, cost, escalated = self._judge(cited)
            except Exception as exc:  # verification must never break the answer
                self._log_failure("query.verify_failed", exc)
                return None
        result = VerificationResult(
            backend=self._verifier.name,
            sentences=_assemble(claims, judgements),
            ms=timer.ms,
            cost_usd=cost,
            escalated=escalated,
        )
        logger.info(
            "query.verified",
            backend=result.backend,
            n_sentences=len(result.sentences),
            supported=result.count(Verdict.SUPPORTED),
            partial=result.count(Verdict.PARTIAL),
            unsupported=result.count(Verdict.UNSUPPORTED),
            escalated=escalated,
            ms=result.ms,
        )
        return result

    def _judge(self, cited: list[Claim]) -> tuple[dict[int, Judgement], float | None, int]:
        if not cited:
            return {}, None, 0
        run = self._verifier.verify(cited)
        if len(run.judgements) != len(cited):
            raise ValueError(f"{len(run.judgements)} judgements for {len(cited)} claims")
        judgements = {c.index: j for c, j in zip(cited, run.judgements, strict=True)}
        cost = run.cost_usd
        low = [c for c in cited if judgements[c.index].confidence < self._escalate_below]
        if self._escalation is None or self._verifier.name != ESCALATING_BACKEND or not low:
            return judgements, cost, 0
        try:
            second = self._escalation.verify(low)
            judgements.update({c.index: j for c, j in zip(low, second.judgements, strict=True)})
        except Exception as exc:  # keep the first backend's verdicts
            self._log_failure("query.verify_escalation_failed", exc)
            return judgements, cost, 0
        if second.cost_usd is not None:
            cost = (cost or 0.0) + second.cost_usd
        return judgements, cost, len(low)

    def _log_failure(self, event: str, exc: Exception) -> None:
        if isinstance(exc, ProviderError):
            logger.warning(event, provider=exc.provider, kind=exc.kind, reason=exc.message)
        else:
            logger.exception(event)


def _assemble(claims: Sequence[Claim], judgements: dict[int, Judgement]) -> list[SentenceVerdict]:
    uncited = Judgement(Verdict.UNSUPPORTED, 1.0, NO_CITATION)
    verdicts = []
    for claim in claims:
        judgement = judgements.get(claim.index, uncited)
        verdicts.append(
            SentenceVerdict(
                index=claim.index,
                sentence=claim.sentence,
                refs=claim.refs,
                verdict=judgement.verdict,
                confidence=judgement.confidence,
                decided_by=judgement.decided_by,
            )
        )
    return verdicts
