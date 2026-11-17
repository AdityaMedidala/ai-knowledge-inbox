"""Chunk rows plus their FTS5 and sqlite-vec shadows: writes and both search arms."""

import sqlite3
from collections.abc import Iterable, Sequence

import sqlite_vec
import structlog

from app.domain.errors import EmbeddingDimensionError, ItemNotProcessingError
from app.domain.models import ChunkRecord, ItemType, KeywordHit, NewChunk, VectorHit
from app.store.db import transaction
from app.store.fts import build_fts_query
from app.utils.time import Clock, utc_now_iso

logger = structlog.get_logger(__name__)

# context_header repeats the item title in every chunk; down-weight it so it doesn't dominate.
FTS_HEADER_WEIGHT = 0.5
FTS_TEXT_WEIGHT = 1.0


class ChunksRepository:
    def __init__(self, conn: sqlite3.Connection, embedding_dim: int, clock: Clock) -> None:
        self._conn = conn
        self._dim = embedding_dim
        self._clock = clock

    def replace_chunks(
        self,
        item_id: str,
        chunks: Sequence[NewChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        """Atomically swap in an item's chunks + vectors and mark it ready.

        Inputs are validated before the transaction; inside it, the item must still exist and
        be 'processing', otherwise ItemNotProcessingError is raised and nothing is written.
        """
        if not chunks:
            raise ValueError("replace_chunks needs at least one chunk.")
        if len(chunks) != len(embeddings):
            raise ValueError(f"{len(chunks)} chunks but {len(embeddings)} embeddings.")
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            self._check_dim(embedding, f"embedding for chunk ordinal {chunk.ordinal}")

        with transaction(self._conn) as conn:
            row = conn.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None or row["status"] != "processing":
                raise ItemNotProcessingError(item_id, row["status"] if row else None)

            conn.execute("DELETE FROM chunks WHERE item_id = ?", (item_id,))
            for chunk, embedding in zip(chunks, embeddings, strict=True):
                cursor = conn.execute(
                    "INSERT INTO chunks (item_id, ordinal, section, context_header, text, "
                    "token_count) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        item_id,
                        chunk.ordinal,
                        chunk.section,
                        chunk.context_header,
                        chunk.text,
                        chunk.token_count,
                    ),
                )
                conn.execute(
                    "INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)",
                    (cursor.lastrowid, sqlite_vec.serialize_float32(list(embedding))),
                )
            conn.execute(
                "UPDATE items SET status = 'ready', chunk_count = ?, error_code = NULL, "
                "error_message = NULL, updated_at = ? WHERE id = ?",
                (len(chunks), utc_now_iso(self._clock), item_id),
            )

    def vector_search(self, query_embedding: Sequence[float], k: int) -> list[VectorHit]:
        """k nearest chunks of ready items by cosine similarity, best first.

        vec0 picks the k nearest before any join. Chunks only exist for ready items (see
        replace_chunks), so the status filter is a safety net; if it ever drops rows the
        invariant is broken, and we log it rather than silently returning fewer hits.
        """
        self._check_dim(query_embedding, "query embedding")
        rows = self._conn.execute(
            "WITH knn AS (SELECT rowid, distance FROM chunks_vec "
            "WHERE embedding MATCH ? AND k = ?) "
            "SELECT knn.rowid AS chunk_id, knn.distance, i.status FROM knn "
            "JOIN chunks c ON c.id = knn.rowid JOIN items i ON i.id = c.item_id "
            "ORDER BY knn.distance",
            (sqlite_vec.serialize_float32(list(query_embedding)), k),
        ).fetchall()
        ready = [row for row in rows if row["status"] == "ready"]
        if len(ready) != len(rows):
            logger.warning("store.vector_search_filtered", returned=len(rows), ready=len(ready))
        return [
            VectorHit(chunk_id=row["chunk_id"], position=pos, similarity=1.0 - row["distance"])
            for pos, row in enumerate(ready, start=1)
        ]

    def keyword_search(self, text: str, limit: int) -> list[KeywordHit]:
        """BM25 search over ready items. Free text is sanitized, so it never raises on syntax.

        FTS5 bm25 is ascending: lower (more negative) means more relevant.
        """
        match = build_fts_query(text)
        if match is None:
            return []
        rows = self._conn.execute(
            "SELECT chunks_fts.rowid AS chunk_id, bm25(chunks_fts, ?, ?) AS score "
            "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
            "JOIN items i ON i.id = c.item_id "
            "WHERE chunks_fts MATCH ? AND i.status = 'ready' "
            "ORDER BY score LIMIT ?",
            (FTS_HEADER_WEIGHT, FTS_TEXT_WEIGHT, match, limit),
        ).fetchall()
        return [
            KeywordHit(chunk_id=row["chunk_id"], position=pos, bm25=row["score"])
            for pos, row in enumerate(rows, start=1)
        ]

    def get_chunks_by_ids(self, chunk_ids: Iterable[int]) -> dict[int, ChunkRecord]:
        ids = list(dict.fromkeys(chunk_ids))
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = self._conn.execute(
            "SELECT c.id, c.item_id, c.ordinal, c.section, c.context_header, c.text, "  # noqa: S608  # constant column list / placeholders only
            "c.token_count, i.title, i.type, i.source_url "
            f"FROM chunks c JOIN items i ON i.id = c.item_id WHERE c.id IN ({placeholders})",
            ids,
        ).fetchall()
        return {
            row["id"]: ChunkRecord(
                id=row["id"],
                item_id=row["item_id"],
                ordinal=row["ordinal"],
                section=row["section"],
                context_header=row["context_header"],
                text=row["text"],
                token_count=row["token_count"],
                item_title=row["title"],
                item_type=ItemType(row["type"]),
                source_url=row["source_url"],
            )
            for row in rows
        }

    def _check_dim(self, vector: Sequence[float], label: str) -> None:
        if len(vector) != self._dim:
            raise EmbeddingDimensionError(
                f"{label} has {len(vector)} dims; expected {self._dim} (EMBEDDING_DIM)."
            )
