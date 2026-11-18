"""Eval corpus: notes plus real web pages frozen as fetch snapshots.

`snapshot` fetches each URL item once through the app's real Fetcher (SSRF guard, redirects,
size and content-type checks) and saves the bytes. Every eval run then replays those bytes, so
extraction, chunking and embedding are the real pipeline while the corpus never drifts.
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.domain.errors import IngestError
from app.domain.models import ItemErrorCode
from app.services.fetcher import FetchedPage, Fetcher, build_fetch_client

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
CORPUS_DIR = EVAL_DIR / "corpus"


@dataclass(frozen=True, slots=True)
class CorpusItem:
    key: str
    type: str  # note | url
    title: str | None = None
    content: str | None = None  # notes
    url: str | None = None  # urls


def load_items(data: dict[str, Any]) -> list[CorpusItem]:
    return [CorpusItem(**item) for item in data["items"]]


def _paths(key: str) -> tuple[Path, Path]:
    return CORPUS_DIR / f"{key}.body", CORPUS_DIR / f"{key}.meta.json"


def snapshot(items: list[CorpusItem], *, timeout_s: float, max_bytes: int, redirects: int) -> None:
    """Fetch every URL item that has no snapshot yet. Existing snapshots are never refreshed."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    with build_fetch_client() as client:
        fetcher = Fetcher(client, timeout_s=timeout_s, max_bytes=max_bytes, max_redirects=redirects)
        for item in items:
            body_path, meta_path = _paths(item.key)
            if item.type != "url" or meta_path.exists():
                continue
            assert item.url is not None  # noqa: S101 — url items always carry one
            page = fetcher.fetch(item.url)
            body_path.write_bytes(page.body)
            meta = {k: v for k, v in asdict(page).items() if k != "body"}
            meta_path.write_text(json.dumps({"url": item.url, **meta}, indent=2), "utf-8")
            print(f"snapshot {item.key}: {len(page.body)} bytes from {page.final_url}")


class SnapshotFetcher:
    """PageFetcher that replays saved snapshots; an unknown URL fails like a blocked fetch."""

    def __init__(self, items: list[CorpusItem]) -> None:
        self._keys = {item.url: item.key for item in items if item.type == "url"}

    def fetch(self, url: str) -> FetchedPage:
        key = self._keys.get(url)
        if key is None:
            raise IngestError(ItemErrorCode.FETCH_BLOCKED, f"no eval snapshot for {url}")
        body_path, meta_path = _paths(key)
        if not meta_path.exists():
            raise SystemExit(f"missing snapshot for {key}; run: make eval ARGS=snapshot")
        meta = json.loads(meta_path.read_text("utf-8"))
        meta.pop("url")
        return FetchedPage(body=body_path.read_bytes(), **meta)
