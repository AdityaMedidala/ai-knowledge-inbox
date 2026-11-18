"""Deterministic offline providers for tests and `*_PROVIDER=fake`."""

import math
import re
from collections.abc import Iterator, Sequence
from enum import StrEnum
from hashlib import blake2b

from app.domain.errors import ProviderError, ProviderErrorKind
from app.domain.verification import Claim, Judgement, Verdict, VerifierRun
from app.providers.base import ChatMessage
from app.utils.text import STOP_WORDS, word_tokens

PROVIDER = "fake"


class FakeEmbedder:
    """Hashing-trick bag of words → L2-normalized vector, so shared words mean high cosine."""

    def __init__(self, dim: int) -> None:
        self._dim = dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self._dim
        for token in word_tokens(text):
            if token in STOP_WORDS:
                continue
            digest = blake2b(token.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self._dim
            vector[bucket] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            return [1.0] + [0.0] * (self._dim - 1)  # fixed unit vector for empty text
        return [v / norm for v in vector]


class FakeChatScript(StrEnum):
    CITE_VALID = "cite_valid"
    CITE_INVALID = "cite_invalid"
    CITE_NONE = "cite_none"
    FAIL_RETRYABLE = "fail_retryable"
    FAIL_PERMANENT = "fail_permanent"


_SOURCE_ID = re.compile(r'<source id="(\d+)"')
_PIECE = re.compile(r"\S+\s*")
_FAILING = {FakeChatScript.FAIL_RETRYABLE, FakeChatScript.FAIL_PERMANENT}


class FakeChatModel:
    """Scriptable chat model. Records every call in `calls` so tests can assert it wasn't used."""

    def __init__(
        self, script: FakeChatScript = FakeChatScript.CITE_VALID, *, fail_after_tokens: int = 0
    ) -> None:
        self.script = script
        self.fail_after_tokens = fail_after_tokens
        self.calls: list[list[ChatMessage]] = []

    def complete(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        if self.script in _FAILING:
            raise self._error()
        return self._answer(messages)

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        self.calls.append(list(messages))
        pieces = _PIECE.findall(self._answer(messages))
        for position, piece in enumerate(pieces):
            if self.script in _FAILING and position == self.fail_after_tokens:
                raise self._error()
            yield piece
        if self.script in _FAILING:
            raise self._error()

    def _answer(self, messages: Sequence[ChatMessage]) -> str:
        if self.script is FakeChatScript.CITE_INVALID:
            return "Fake answer citing a source that does not exist [9]."
        if self.script is FakeChatScript.CITE_NONE:
            return "Fake answer without any citations."
        ids = dict.fromkeys(_SOURCE_ID.findall("\n".join(m.content for m in messages)))
        if not ids:
            return "Fake answer: the sources do not cover this."
        return "Fake answer drawn from the sources " + "".join(f"[{i}]" for i in ids) + "."

    def _error(self) -> ProviderError:
        if self.script is FakeChatScript.FAIL_RETRYABLE:
            return ProviderError(ProviderErrorKind.UNAVAILABLE, PROVIDER, "scripted outage")
        return ProviderError(ProviderErrorKind.BAD_REQUEST, PROVIDER, "scripted rejection")


class FakeVerifier:
    """Word overlap between sentence and evidence decides the verdict. Records every call.

    `confidence` is fixed so tests can push claims above or below the escalation threshold.
    """

    def __init__(self, name: str = PROVIDER, *, confidence: float = 0.9, fail: bool = False):
        self.name = name
        self.confidence = confidence
        self.fail = fail
        self.calls: list[list[Claim]] = []

    def verify(self, claims: Sequence[Claim]) -> VerifierRun:
        self.calls.append(list(claims))
        if self.fail:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, self.name, "scripted outage")
        return VerifierRun([self._judge(claim) for claim in claims], cost_usd=0.0)

    def _judge(self, claim: Claim) -> Judgement:
        words = {w for w in word_tokens(claim.sentence) if w not in STOP_WORDS}
        evidence = set(word_tokens(" ".join(claim.evidence)))
        overlap = len(words & evidence) / len(words) if words else 0.0
        if overlap >= 0.8:
            verdict = Verdict.SUPPORTED
        elif overlap >= 0.4:
            verdict = Verdict.PARTIAL
        else:
            verdict = Verdict.UNSUPPORTED
        return Judgement(verdict, self.confidence, self.name)
