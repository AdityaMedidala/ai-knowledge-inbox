import math

import pytest

from app.domain.errors import ProviderError, ProviderErrorKind
from app.providers.base import ChatMessage
from app.providers.fakes import FakeChatModel, FakeChatScript, FakeEmbedder

DIM = 256
PROMPT = [
    ChatMessage("system", "rules"),
    ChatMessage("user", '<sources><source id="1">a</source><source id="2">b</source></sources>'),
]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def test_fake_embedder_is_deterministic_and_unit_norm() -> None:
    first = FakeEmbedder(DIM).embed_documents(["Sourdough bread recipe"])[0]
    again = FakeEmbedder(DIM).embed_documents(["sourdough BREAD recipe!"])[0]
    assert first == again
    assert len(first) == DIM
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0)


def test_fake_embedder_similar_texts_score_higher() -> None:
    query, related, unrelated = FakeEmbedder(DIM).embed_documents(
        [
            "how do I bake sourdough bread",
            "baking sourdough bread at home",
            "kubernetes cluster networking",
        ]
    )
    assert cosine(query, related) > cosine(query, unrelated)


@pytest.mark.parametrize("text", ["", "   ", "what is the", "?!"])
def test_fake_embedder_returns_fixed_unit_vector_for_empty_text(text: str) -> None:
    (vector,) = FakeEmbedder(DIM).embed_documents([text])
    assert vector == [1.0] + [0.0] * (DIM - 1)


def test_fake_chat_cites_every_source_by_default_and_records_calls() -> None:
    chat = FakeChatModel()
    assert chat.complete(PROMPT).endswith("[1][2].")
    assert "".join(chat.stream(PROMPT)) == chat.complete(PROMPT)
    assert len(chat.calls) == 3


def test_fake_chat_scripted_citations() -> None:
    assert "[9]" in FakeChatModel(FakeChatScript.CITE_INVALID).complete(PROMPT)
    assert "[" not in FakeChatModel(FakeChatScript.CITE_NONE).complete(PROMPT)


@pytest.mark.parametrize(
    ("script", "retryable"),
    [(FakeChatScript.FAIL_RETRYABLE, True), (FakeChatScript.FAIL_PERMANENT, False)],
)
def test_fake_chat_failures(script: FakeChatScript, retryable: bool) -> None:
    with pytest.raises(ProviderError) as excinfo:
        FakeChatModel(script).complete(PROMPT)
    assert excinfo.value.retryable is retryable


def test_fake_chat_can_fail_mid_stream() -> None:
    received: list[str] = []
    with pytest.raises(ProviderError) as excinfo:
        received.extend(
            FakeChatModel(FakeChatScript.FAIL_RETRYABLE, fail_after_tokens=2).stream(PROMPT)
        )
    assert len(received) == 2
    assert excinfo.value.kind is ProviderErrorKind.UNAVAILABLE


def test_fake_embedder_query_matches_document_embedding() -> None:
    embedder = FakeEmbedder(DIM)
    assert (
        embedder.embed_query("sourdough bread") == embedder.embed_documents(["sourdough bread"])[0]
    )
