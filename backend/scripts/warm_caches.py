"""Download the tokenizer and embedding model once, so the app and tests run offline.

Run by `make install`. Warms the configured fastembed model, or the default one when .env is
not filled in yet.
"""

from pathlib import Path

from pydantic import ValidationError

from app.config import Settings
from app.providers.fastembed_provider import build_fastembed_embedder
from app.utils.tokens import count_tokens


def _fastembed_target() -> tuple[str, int, Path] | None:
    try:
        settings = Settings()
    except ValidationError:
        fields = Settings.model_fields
        return (
            fields["embedding_model"].default,
            fields["embedding_dim"].default,
            fields["fastembed_cache_dir"].default,
        )
    if settings.embedding_provider != "fastembed":
        return None
    return settings.embedding_model, settings.embedding_dim, settings.fastembed_cache_dir


def main() -> None:
    count_tokens("warm the tiktoken cache")
    print("tiktoken   cache warm")
    target = _fastembed_target()
    if target is None:
        print("fastembed  skipped (EMBEDDING_PROVIDER is not fastembed)")
        return
    model, dim, cache_dir = target
    build_fastembed_embedder(
        model, dim=dim, cache_dir=cache_dir, threads=None, local_files_only=False
    )
    print(f"fastembed  {model} cached in {cache_dir}")


if __name__ == "__main__":
    main()
