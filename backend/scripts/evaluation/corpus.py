"""Eval corpus: notes plus real web pages frozen as fetch snapshots.

`snapshot` fetches each URL item once through the app's real Fetcher (SSRF guard, redirects,
size and content-type checks) and saves the bytes. Every eval run then replays those bytes, so
extraction, chunking and embedding are the real pipeline while the corpus never drifts.
"""

import json
from dataclasses import asdict
from pathlib import Path

from app.services.fetcher import Fetcher, build_fetch_client
from app.services.snapshots import CorpusItem, snapshot_paths

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
CORPUS_DIR = EVAL_DIR / "corpus"


def _paths(key: str) -> tuple[Path, Path]:
    return snapshot_paths(CORPUS_DIR, key)


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
