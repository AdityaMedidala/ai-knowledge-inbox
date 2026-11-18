"""Verification part of the /query contract (and the `verification` SSE event)."""

from pydantic import BaseModel, Field

from app.domain import verification
from app.domain.verification import Verdict


class SentenceVerdict(BaseModel):
    index: int = Field(description="Position among the answer's sentences.")
    sentence: str = Field(description="The sentence text, without [n] markers.")
    refs: list[int] = Field(description="Valid [n] refs the sentence cites; empty if uncited.")
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    decided_by: str = Field(description="groq, jev, fake, or no_citation (no backend call).")


class VerificationSummary(BaseModel):
    supported: int
    partial: int
    unsupported: int
    total: int


class Verification(BaseModel):
    backend: str = Field(description="The configured verifier (VERIFIER).")
    summary: VerificationSummary
    sentences: list[SentenceVerdict]
    escalated: int = Field(description="Sentences Jev was unsure about and Groq re-checked.")
    ms: float

    @classmethod
    def from_domain(cls, result: verification.VerificationResult) -> "Verification":
        return cls(
            backend=result.backend,
            summary=VerificationSummary(
                supported=result.count(Verdict.SUPPORTED),
                partial=result.count(Verdict.PARTIAL),
                unsupported=result.count(Verdict.UNSUPPORTED),
                total=len(result.sentences),
            ),
            sentences=[
                SentenceVerdict(
                    index=s.index,
                    sentence=s.sentence,
                    refs=list(s.refs),
                    verdict=s.verdict,
                    confidence=s.confidence,
                    decided_by=s.decided_by,
                )
                for s in result.sentences
            ],
            escalated=result.escalated,
            ms=result.ms,
        )
