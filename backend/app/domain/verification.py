"""Answer verification types: each answer sentence checked against the sources it cites."""

from dataclasses import dataclass
from enum import StrEnum


class Verdict(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


NO_CITATION = "no_citation"  # `decided_by` for sentences judged without calling a backend


@dataclass(frozen=True, slots=True)
class Claim:
    """One answer sentence plus the text of the sources it cites."""

    index: int  # position among the answer's sentences
    sentence: str
    refs: tuple[int, ...]  # valid [n] refs only
    evidence: tuple[str, ...]  # chunk text of each cited source, same order as refs


@dataclass(frozen=True, slots=True)
class Judgement:
    verdict: Verdict
    confidence: float  # 0..1; for Jev, the top choice probability
    decided_by: str  # backend name, or NO_CITATION


@dataclass(frozen=True, slots=True)
class VerifierRun:
    """One backend call's judgements (same order as its claims) and what it cost."""

    judgements: list[Judgement]
    cost_usd: float | None = None  # None when the backend doesn't report it


@dataclass(frozen=True, slots=True)
class SentenceVerdict:
    index: int
    sentence: str
    refs: tuple[int, ...]
    verdict: Verdict
    confidence: float
    decided_by: str


@dataclass(frozen=True, slots=True)
class VerificationResult:
    backend: str  # the configured verifier (escalations show per sentence in decided_by)
    sentences: list[SentenceVerdict]
    ms: float
    cost_usd: float | None
    escalated: int  # sentences re-checked by the escalation backend

    def count(self, verdict: Verdict) -> int:
        return sum(1 for s in self.sentences if s.verdict is verdict)
