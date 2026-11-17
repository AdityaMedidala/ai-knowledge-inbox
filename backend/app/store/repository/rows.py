"""Row <-> domain mapping and the column lists each query selects."""

import sqlite3

from app.domain.models import Item, ItemErrorCode, ItemStatus, ItemSummary, ItemType
from app.utils.text import PREVIEW_CHARS, preview_of

ITEM_COLUMNS = (
    "id, type, title, source_url, normalized_url, content_hash, raw_content, extracted_text, "
    "status, error_code, error_message, attempts, chunk_count, created_at, updated_at"
)
# List view: explicit columns, never raw_content (fetched HTML can be megabytes) and only the
# head of extracted_text, enough to build the preview.
SUMMARY_COLUMNS = (
    "id, type, title, source_url, status, error_code, error_message, chunk_count, created_at, "
    f"updated_at, substr(extracted_text, 1, {PREVIEW_CHARS * 2}) AS preview_source"
)


def row_to_summary(row: sqlite3.Row) -> ItemSummary:
    return ItemSummary(
        id=row["id"],
        type=ItemType(row["type"]),
        title=row["title"],
        source_url=row["source_url"],
        status=ItemStatus(row["status"]),
        error_code=ItemErrorCode(row["error_code"]) if row["error_code"] else None,
        error_message=row["error_message"],
        chunk_count=row["chunk_count"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        preview=preview_of(row["preview_source"]),
    )


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
