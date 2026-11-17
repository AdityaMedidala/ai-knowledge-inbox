"""Idempotent schema application plus a guard against embedding-config drift."""

import sqlite3
from pathlib import Path

import structlog

from app.domain.errors import EmbeddingConfigMismatchError
from app.store.db import transaction

logger = structlog.get_logger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DIM_PLACEHOLDER = "{{EMBEDDING_DIM}}"


def apply_migrations(
    conn: sqlite3.Connection, *, embedding_model: str, embedding_dim: int, db_label: str
) -> None:
    """Check the embedding guard first, so a mismatched DB is never modified, then apply schema."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    _guard_embedding_config(conn, embedding_model, embedding_dim, db_label)
    conn.executescript(render_schema(embedding_dim))
    logger.info("db.migrated", embedding_model=embedding_model, embedding_dim=embedding_dim)


def render_schema(embedding_dim: int) -> str:
    if embedding_dim <= 0:
        raise ValueError(f"embedding_dim must be positive, got {embedding_dim}.")
    return SCHEMA_PATH.read_text(encoding="utf-8").replace(DIM_PLACEHOLDER, str(embedding_dim))


def _guard_embedding_config(conn: sqlite3.Connection, model: str, dim: int, db_label: str) -> None:
    with transaction(conn):
        stored = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if not stored:
            conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [("embedding_model", model), ("embedding_dim", str(dim))],
            )
            return

    stored_model, stored_dim = stored.get("embedding_model"), stored.get("embedding_dim")
    if (stored_model, stored_dim) != (model, str(dim)):
        raise EmbeddingConfigMismatchError(
            f"Embedding config changed: database at {db_label} was built with {stored_model} "
            f"({stored_dim} dims) but config is {model} ({dim} dims). "
            "Run `make reindex` or delete the DB file."
        )
