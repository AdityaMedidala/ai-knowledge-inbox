"""Saved fetch snapshots of the eval corpus, replayed instead of fetching the web.

The eval and the demo seed (SEED_ON_EMPTY, `make seed`) both ingest these pages offline: only the
fetch is replaced, extraction, chunking and embedding are the normal pipeline.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.fetcher import FetchedPage
from app.utils.urls import redact_url


@dataclass(frozen=True, slots=True)
class CorpusItem:
    key: str
    type: str  # note | url
    title: str | None = None
    content: str | None = None  # notes
    url: str | None = None  # urls


def load_items(data: dict[str, Any]) -> list[CorpusItem]:
    return [CorpusItem(**item) for item in data["items"]]


def snapshot_paths(corpus_dir: Path, key: str) -> tuple[Path, Path]:
    return corpus_dir / f"{key}.body", corpus_dir / f"{key}.meta.json"


class SnapshotFetcher:
    """PageFetcher that replays saved snapshots; an unknown URL fails like a blocked fetch."""

    def __init__(self, items: list[CorpusItem], corpus_dir: Path) -> None:
        self._keys = {item.url: item.key for item in items if item.type == "url"}
        self._corpus_dir = corpus_dir

    def fetch(self, url: str) -> FetchedPage:
        key = self._keys.get(url)
        body_path, meta_path = snapshot_paths(self._corpus_dir, key or "")
        if key is None or not meta_path.exists():
            raise IngestError(
                ItemErrorCode.FETCH_BLOCKED, f"No saved snapshot for {redact_url(url)}."
            )
        meta = json.loads(meta_path.read_text("utf-8"))
        meta.pop("url")
        return FetchedPage(body=body_path.read_bytes(), **meta)
