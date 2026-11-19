"""Seed the inbox with a small demo set through the normal API: `make seed`.

The app runs in-process (Starlette's TestClient drives its lifespan, so the real ingestion worker
runs) against the database in .env. URL items are served from the eval corpus snapshots instead of
the network, so seeding works offline; everything after the fetch (extract, chunk, embed, store)
is the normal pipeline. Items already in the inbox come back 409 and are skipped.
"""

import json
import sys
import time
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from scripts.evaluation.corpus import EVAL_DIR, CorpusItem, SnapshotFetcher, load_items

SEED_KEYS = ("wal", "async_notes", "sourdough", "coffee", "lisbon")  # notes; all URLs are added
TIMEOUT_S = 300
POLL_S = 0.5


def seed_items() -> list[CorpusItem]:
    data = json.loads((EVAL_DIR / "eval_set.json").read_text("utf-8"))
    return [item for item in load_items(data) if item.type == "url" or item.key in SEED_KEYS]


def request_body(item: CorpusItem) -> dict[str, Any]:
    if item.type == "url":
        return {"type": "url", "url": item.url}
    return {"type": "note", "content": item.content, "title": item.title}


def submit(client: TestClient, item: CorpusItem) -> str | None:
    """Returns the new item's id, or None when it is already saved."""
    response = client.post("/ingest", json=request_body(item))
    if response.status_code == 409:
        print(f"skip    {item.key}: already saved")
        return None
    if response.status_code != 202:
        raise SystemExit(f"{item.key}: ingest returned {response.status_code}: {response.text}")
    print(f"queued  {item.key}")
    return response.json()["item"]["id"]


def wait_until_settled(client: TestClient, ids: dict[str, str]) -> int:
    """Polls until every queued item is ready or failed; returns how many failed."""
    pending, failed = dict(ids), 0
    deadline = time.monotonic() + TIMEOUT_S
    while pending and time.monotonic() < deadline:
        for item_id, key in list(pending.items()):
            item = client.get(f"/items/{item_id}").json()
            if item["status"] == "ready":
                print(f"ready   {key}: {item['chunk_count']} chunks")
            elif item["status"] == "failed":
                failed += 1
                print(f"failed  {key}: {item['error']['code']} {item['error']['message']}")
            else:
                continue
            del pending[item_id]
        time.sleep(POLL_S)
    for key in pending.values():
        failed += 1
        print(f"timeout {key}: still processing after {TIMEOUT_S}s")
    return failed


def main() -> None:
    items = seed_items()
    # Only the per-item lines above matter here; the app's own INFO logs would bury them.
    app = create_app(Settings(log_level="WARNING"), fetcher=SnapshotFetcher(items))
    with TestClient(app) as client:
        queued = {item_id: item.key for item in items if (item_id := submit(client, item))}
        failed = wait_until_settled(client, queued)
    print(f"seeded {len(queued) - failed} new, {len(items) - len(queued)} already saved")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
