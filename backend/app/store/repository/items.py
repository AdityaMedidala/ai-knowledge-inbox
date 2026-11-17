"""Item rows: creation, lookup, keyset listing, and the status state machine."""

import sqlite3
from uuid import uuid4

from app.domain.errors import DuplicateItemError, InvalidStatusTransitionError, ItemNotFoundError
from app.domain.models import (
    Item,
    ItemErrorCode,
    ItemPage,
    ItemStatus,
    ItemType,
    NewItem,
    PageKey,
)
from app.utils.time import Clock, utc_now_iso

_COLUMNS = (
    "id, type, title, source_url, normalized_url, content_hash, raw_content, extracted_text, "
    "status, error_code, error_message, attempts, chunk_count, created_at, updated_at"
)

# target status -> statuses it may be entered from. 'ready' is absent on purpose: only
# ChunksRepository.replace_chunks may set it, atomically with writing the chunks.
_ALLOWED_SOURCES: dict[ItemStatus, tuple[ItemStatus, ...]] = {
    ItemStatus.PROCESSING: (ItemStatus.PENDING,),
    ItemStatus.PENDING: (ItemStatus.PROCESSING,),
    ItemStatus.FAILED: (ItemStatus.PROCESSING,),
}


def row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        type=ItemType(row["type"]),
        title=row["title"],
        source_url=row["source_url"],
        normalized_url=row["normalized_url"],
        content_hash=row["content_hash"],
        raw_content=row["raw_content"],
        extracted_text=row["extracted_text"],
        status=ItemStatus(row["status"]),
        error_code=ItemErrorCode(row["error_code"]) if row["error_code"] else None,
        error_message=row["error_message"],
        attempts=row["attempts"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class ItemsRepository:
    def __init__(self, conn: sqlite3.Connection, clock: Clock) -> None:
        self._conn = conn
        self._clock = clock

    def create_item(self, new: NewItem) -> Item:
        """Insert a pending item. Raises DuplicateItemError if the URL / note already exists."""
        now = utc_now_iso(self._clock)
        item_id = uuid4().hex
        try:
            self._conn.execute(
                "INSERT INTO items (id, type, title, source_url, normalized_url, content_hash, "
                "raw_content, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (
                    item_id,
                    new.type,
                    new.title,
                    new.source_url,
                    new.normalized_url,
                    new.content_hash,
                    new.raw_content,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.find_duplicate(
                new.type, normalized_url=new.normalized_url, content_hash=new.content_hash
            )
            if existing is None:
                raise
            raise DuplicateItemError(existing.id) from exc
        return self._require(item_id)

    def get_item(self, item_id: str) -> Item | None:
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM items WHERE id = ?",  # noqa: S608  # constant column list / placeholders only
            (item_id,),
        ).fetchone()
        return row_to_item(row) if row else None

    def find_duplicate(
        self,
        item_type: ItemType,
        *,
        normalized_url: str | None = None,
        content_hash: str | None = None,
    ) -> Item | None:
        if item_type is ItemType.URL:
            sql, key = "type = 'url' AND normalized_url = ?", normalized_url
        else:
            sql, key = "type = 'note' AND content_hash = ?", content_hash
        if key is None:
            return None
        row = self._conn.execute(
            f"SELECT {_COLUMNS} FROM items WHERE {sql}",  # noqa: S608  # constant column list / placeholders only
            (key,),
        ).fetchone()
        return row_to_item(row) if row else None

    def list_items(
        self,
        *,
        limit: int,
        status: ItemStatus | None = None,
        item_type: ItemType | None = None,
        after: PageKey | None = None,
    ) -> ItemPage:
        """Newest first, keyset-paginated on (created_at, id)."""
        if limit <= 0:
            raise ValueError(f"limit must be positive, got {limit}.")
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if item_type is not None:
            clauses.append("type = ?")
            params.append(item_type)
        if after is not None:
            clauses.append("(created_at, id) < (?, ?)")
            params += [after.created_at, after.id]
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM items {where} ORDER BY created_at DESC, id DESC LIMIT ?",  # noqa: S608  # constant column list / placeholders only
            (*params, limit + 1),
        ).fetchall()

        items = [row_to_item(row) for row in rows[:limit]]
        has_more = len(rows) > limit
        next_key = PageKey(items[-1].created_at, items[-1].id) if has_more else None
        return ItemPage(items=items, next_key=next_key)

    def set_status(
        self,
        item_id: str,
        status: ItemStatus,
        *,
        error_code: ItemErrorCode | None = None,
        error_message: str | None = None,
    ) -> None:
        """Apply one legal transition atomically (conditional UPDATE + rowcount check).

        Entering 'processing' increments attempts; entering 'failed' records the error;
        any other transition clears it.
        """
        sources = _ALLOWED_SOURCES.get(status)
        if sources is None:
            raise InvalidStatusTransitionError(item_id, current=None, target=status)
        failed = status is ItemStatus.FAILED
        placeholders = ", ".join("?" for _ in sources)
        cursor = self._conn.execute(
            "UPDATE items SET status = ?, error_code = ?, error_message = ?, "  # noqa: S608  # constant column list / placeholders only
            "attempts = attempts + ?, updated_at = ? "
            f"WHERE id = ? AND status IN ({placeholders})",
            (
                status,
                error_code if failed else None,
                error_message if failed else None,
                1 if status is ItemStatus.PROCESSING else 0,
                utc_now_iso(self._clock),
                item_id,
                *sources,
            ),
        )
        if cursor.rowcount == 1:
            return
        current = self._conn.execute("SELECT status FROM items WHERE id = ?", (item_id,)).fetchone()
        if current is None:
            raise ItemNotFoundError(item_id)
        raise InvalidStatusTransitionError(item_id, current=current["status"], target=status)

    def set_content(
        self, item_id: str, *, title: str | None, extracted_text: str, content_hash: str
    ) -> None:
        """Record extraction results. Only valid while the item is being processed."""
        cursor = self._conn.execute(
            "UPDATE items SET title = COALESCE(?, title), extracted_text = ?, content_hash = ?, "
            "updated_at = ? WHERE id = ? AND status = 'processing'",
            (title, extracted_text, content_hash, utc_now_iso(self._clock), item_id),
        )
        if cursor.rowcount != 1:
            current = self.get_item(item_id)
            if current is None:
                raise ItemNotFoundError(item_id)
            raise InvalidStatusTransitionError(item_id, current.status, "processing (set_content)")

    def delete_item(self, item_id: str) -> bool:
        """Delete an item; FK cascade + triggers remove its chunks, FTS and vector rows."""
        cursor = self._conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        return cursor.rowcount == 1

    def _require(self, item_id: str) -> Item:
        item = self.get_item(item_id)
        if item is None:
            raise ItemNotFoundError(item_id)
        return item
