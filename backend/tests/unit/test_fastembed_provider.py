"""FastEmbedEmbedder logic with a stand-in model; the real ONNX model is never loaded in tests."""

from pathlib import Path

import numpy as np
import pytest

from app.domain.errors import ProviderError, ProviderErrorKind
from app.providers.fastembed_provider import FastEmbedEmbedder, build_fastembed_embedder


class StubModel:
    def __init__(self, dim: int = 3) -> None:
        self.dim = dim
        self.calls: list[tuple[str, object]] = []

    def passage_embed(self, texts: list[str]):
        self.calls.append(("passage", texts))
        return (np.ones(self.dim, dtype=np.float32) for _ in texts)

    def query_embed(self, text: str):
        self.calls.append(("query", text))
        return iter([np.zeros(self.dim, dtype=np.float32)])


def test_documents_and_queries_use_the_asymmetric_methods() -> None:
    model = StubModel()
    embedder = FastEmbedEmbedder(model, model_name="BAAI/bge-small-en-v1.5", dim=3)

    assert embedder.embed_documents(["a", "b"]) == [[1.0, 1.0, 1.0], [1.0, 1.0, 1.0]]
    assert embedder.embed_query("q") == [0.0, 0.0, 0.0]
    assert embedder.embed_documents([]) == []
    assert model.calls == [("passage", ["a", "b"]), ("query", "q")]


def test_wrong_dimension_is_invalid_response() -> None:
    embedder = FastEmbedEmbedder(StubModel(dim=5), model_name="m", dim=3)
    with pytest.raises(ProviderError) as excinfo:
        embedder.embed_documents(["a"])
    assert (excinfo.value.kind, excinfo.value.retryable) == (
        ProviderErrorKind.INVALID_RESPONSE,
        False,
    )


def test_config_dim_must_match_the_model(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="set EMBEDDING_DIM=384"):
        build_fastembed_embedder(
            "BAAI/bge-small-en-v1.5", dim=1536, cache_dir=tmp_path, threads=None
        )


def test_unknown_model_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="not a fastembed text model"):
        build_fastembed_embedder("no/such-model", dim=384, cache_dir=tmp_path, threads=None)


def test_missing_cache_fails_offline_with_install_hint(tmp_path: Path) -> None:
    # local_files_only: must not try to download (the autouse network guard would fail the test).
    with pytest.raises(RuntimeError, match="run `make install`"):
        build_fastembed_embedder(
            "BAAI/bge-small-en-v1.5", dim=384, cache_dir=tmp_path, threads=None
        )
