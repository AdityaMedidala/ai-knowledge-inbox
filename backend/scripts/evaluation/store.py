"""Load the eval set and ingest its items through the app's real submit → fetch → chunk → embed
path. URL items replay frozen snapshots (see corpus.py)."""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.providers.base import Embedder
from app.services.chunker import ChunkLimits
from app.services.ingestion import IngestionService, IngestionSettings
from app.services.snapshots import CorpusItem, SnapshotFetcher, load_items
from app.services.submission import SubmissionService
from app.store.db import connect
from app.store.migrations import apply_migrations
from app.store.repository import Repository
from scripts.evaluation.corpus import CORPUS_DIR, EVAL_DIR

EVAL_SET = EVAL_DIR / "eval_set.json"
RESULTS_DIR = EVAL_DIR / "results"

KINDS = ("answerable", "multi_source", "conflicting", "injection", "near_miss", "out_of_scope")
REFUSE_KINDS = frozenset({"near_miss", "out_of_scope"})
_MARKDOWN_NOISE = re.compile(r"[\\`*]")


@dataclass(frozen=True, slots=True)
class Question:
    id: str
    kind: str
    question: str
    expected_items: list[str]
    expected_answer: str
    evidence: dict[str, str] = field(default_factory=dict)
    split: str | None = None
    note: str | None = None

    @property
    def should_refuse(self) -> bool:
        return self.kind in REFUSE_KINDS


def normalize(text: str) -> str:
    """Comparable form for evidence matching: no markdown escapes, single spaces, lowercase."""
    return " ".join(_MARKDOWN_NOISE.sub("", text).split()).lower()


def load_raw() -> dict[str, Any]:
    return json.loads(EVAL_SET.read_text(encoding="utf-8"))


def load_eval_set() -> tuple[list[CorpusItem], list[Question]]:
    data = load_raw()
    return load_items(data), [Question(**q) for q in data["questions"]]


def build_store(
    settings: Settings, embedder: Embedder, items: list[CorpusItem]
) -> tuple[Repository, dict[str, str]]:
    """Fresh DB at settings.db_path with every item ready. Returns (repo, item_id -> item key)."""
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.db_path)
    apply_migrations(
        conn,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
        db_label="eval",
    )
    repo = Repository(conn, embedding_dim=settings.embedding_dim)
    submission = SubmissionService(repo, note_max_chars=settings.note_max_chars)
    limits = ChunkLimits(
        max_tokens=settings.chunk_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
        max_block_tokens=settings.chunk_max_block_tokens,
    )
    ingestion = IngestionService(
        repo,
        embedder,
        SnapshotFetcher(items, CORPUS_DIR),
        IngestionSettings(limits=limits, max_attempts=1),
    )
    keys: dict[str, str] = {}
    for item in items:
        if item.type == "url":
            assert item.url is not None  # noqa: S101 — url items always carry one
            created = submission.submit_url(item.url)
        else:
            created = submission.submit_note(item.content or "", item.title)
        ingestion.process(created.id)
        ready = repo.get_item(created.id)
        if ready is None or ready.status != "ready":
            raise RuntimeError(f"eval item {item.key} did not become ready")
        keys[created.id] = item.key
    return repo, keys
