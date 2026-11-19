"""Repository facade. Pure delegation to the item and chunk repositories; no logic here.

All SQL in the app lives under app/store/repository/.
"""

import sqlite3
from collections.abc import Iterable, Sequence

from app.domain.models import (
    ChunkRecord,
    InboxStats,
    Item,
    ItemErrorCode,
    ItemPage,
    ItemStatus,
    ItemType,
    KeywordHit,
    NewChunk,
    NewItem,
    PageKey,
    VectorHit,
)
from app.store.repository.chunks import ChunksRepository
from app.store.repository.items import ItemsRepository
from app.utils.time import Clock, utc_now


class Repository:
    def __init__(
        self, conn: sqlite3.Connection, *, embedding_dim: int, clock: Clock = utc_now
    ) -> None:
        self._items = ItemsRepository(conn, clock)
        self._chunks = ChunksRepository(conn, embedding_dim, clock)

    def create_item(self, new: NewItem) -> Item:
        return self._items.create_item(new)

    def get_item(self, item_id: str) -> Item | None:
        return self._items.get_item(item_id)

    def find_duplicate(
        self,
        item_type: ItemType,
        *,
        normalized_url: str | None = None,
        content_hash: str | None = None,
    ) -> Item | None:
        return self._items.find_duplicate(
            item_type, normalized_url=normalized_url, content_hash=content_hash
        )

    def list_items(
        self,
        *,
        limit: int,
        status: ItemStatus | None = None,
        item_type: ItemType | None = None,
        after: PageKey | None = None,
    ) -> ItemPage:
        return self._items.list_items(limit=limit, status=status, item_type=item_type, after=after)

    def set_status(
        self,
        item_id: str,
        status: ItemStatus,
        *,
        error_code: ItemErrorCode | None = None,
        error_message: str | None = None,
    ) -> None:
        self._items.set_status(item_id, status, error_code=error_code, error_message=error_message)

    def set_content(
        self,
        item_id: str,
        *,
        title: str | None,
        extracted_text: str,
        content_hash: str,
        raw_content: str | None = None,
        extractor: str | None = None,
    ) -> None:
        self._items.set_content(
            item_id,
            title=title,
            extracted_text=extracted_text,
            content_hash=content_hash,
            raw_content=raw_content,
            extractor=extractor,
        )

    def recover_interrupted(self) -> list[str]:
        return self._items.recover_interrupted()

    def mark_seeded(self, item_id: str) -> None:
        self._items.mark_seeded(item_id)

    def stats(self) -> InboxStats:
        return self._items.stats()

    def delete_item(self, item_id: str) -> bool:
        return self._items.delete_item(item_id)

    def replace_chunks(
        self, item_id: str, chunks: Sequence[NewChunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        self._chunks.replace_chunks(item_id, chunks, embeddings)

    def vector_search(self, query_embedding: Sequence[float], k: int) -> list[VectorHit]:
        return self._chunks.vector_search(query_embedding, k)

    def keyword_search(self, text: str, limit: int) -> list[KeywordHit]:
        return self._chunks.keyword_search(text, limit)

    def get_chunks_by_ids(self, chunk_ids: Iterable[int]) -> dict[int, ChunkRecord]:
        return self._chunks.get_chunks_by_ids(chunk_ids)
