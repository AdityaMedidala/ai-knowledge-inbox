"""Local CPU embeddings via fastembed (ONNX). Imported lazily: tests never load onnxruntime."""

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import structlog

from app.domain.errors import ProviderError, ProviderErrorKind
from app.utils.timing import Timer

logger = structlog.get_logger(__name__)

PROVIDER = "fastembed"


class FastEmbedEmbedder:
    """bge is asymmetric: passages and queries get different prefixes, hence two methods.

    fastembed truncates inputs past the model's max_length (512 for bge) silently; CHUNK_TOKENS
    keeps chunks well below that.
    """

    def __init__(self, model: Any, *, model_name: str, dim: int) -> None:
        self._model = model
        self._model_name = model_name
        self._dim = dim

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        with Timer() as timer:
            vectors = self._to_lists(self._model.passage_embed(list(texts)), expected=len(texts))
        logger.info(
            "provider.embeddings_completed",
            model=self._model_name,
            inputs=len(texts),
            input_tokens=None,
            ms=timer.ms,
        )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._to_lists(self._model.query_embed(text), expected=1)[0]

    def _to_lists(self, arrays: Iterable[Any], *, expected: int) -> list[list[float]]:
        vectors = [[float(x) for x in array] for array in arrays]
        if len(vectors) != expected:
            raise _invalid(f"expected {expected} vectors, got {len(vectors)}")
        for index, vector in enumerate(vectors):
            if len(vector) != self._dim:
                raise _invalid(f"input {index}: returned {len(vector)} dims, expected {self._dim}")
        return vectors


def build_fastembed_embedder(
    model_name: str,
    *,
    dim: int,
    cache_dir: Path,
    threads: int | None,
    local_files_only: bool = True,
) -> FastEmbedEmbedder:
    """Load the model once. The app runs offline (local_files_only); `make install` warms it."""
    from fastembed import TextEmbedding  # heavy (onnxruntime); load only when configured

    supported = {m["model"]: m["dim"] for m in TextEmbedding.list_supported_models()}
    if model_name not in supported:
        raise RuntimeError(f"EMBEDDING_MODEL={model_name} is not a fastembed text model.")
    if supported[model_name] != dim:
        raise RuntimeError(
            f"EMBEDDING_DIM={dim} but {model_name} produces {supported[model_name]} dims; "
            f"set EMBEDDING_DIM={supported[model_name]}."
        )
    try:
        model = TextEmbedding(
            model_name=model_name,
            cache_dir=str(cache_dir),
            threads=threads,
            local_files_only=local_files_only,
        )
    except Exception as exc:  # fastembed raises various errors when the cache is missing
        raise RuntimeError(
            f"Could not load {model_name} from {cache_dir}; run `make install` to download it."
        ) from exc
    return FastEmbedEmbedder(model, model_name=model_name, dim=dim)


def _invalid(message: str) -> ProviderError:
    return ProviderError(ProviderErrorKind.INVALID_RESPONSE, PROVIDER, message)
