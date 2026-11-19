"""Item response models. raw_content is deliberately absent from every one of them."""

from pydantic import BaseModel, Field

from app.domain import models
from app.domain.models import ItemErrorCode, ItemStatus, ItemType


class ItemError(BaseModel):
    code: ItemErrorCode
    message: str


class ItemSummary(BaseModel):
    id: str
    type: ItemType
    title: str | None
    source_url: str | None
    status: ItemStatus
    error: ItemError | None = Field(description="Set only when status is 'failed'.")
    chunk_count: int
    created_at: str
    updated_at: str
    preview: str | None = Field(
        description="First ~160 characters of the text; null until a URL has been extracted."
    )

    @classmethod
    def from_domain(cls, summary: models.ItemSummary) -> "ItemSummary":
        error = None
        if summary.error_code is not None:
            error = ItemError(code=summary.error_code, message=summary.error_message or "")
        return cls(
            id=summary.id,
            type=summary.type,
            title=summary.title,
            source_url=summary.source_url,
            status=summary.status,
            error=error,
            chunk_count=summary.chunk_count,
            created_at=summary.created_at,
            updated_at=summary.updated_at,
            preview=summary.preview,
        )


class ItemDetail(ItemSummary):
    extracted_text: str | None = Field(description="Markdown the item was chunked from.")

    @classmethod
    def from_item(cls, item: models.Item) -> "ItemDetail":
        summary = ItemSummary.from_domain(item.summary())
        return cls(**summary.model_dump(), extracted_text=item.extracted_text)


class ItemList(BaseModel):
    items: list[ItemSummary]
    next_cursor: str | None = Field(description="Pass as ?cursor= for the next page; null at end.")


class ItemStats(BaseModel):
    items: int = Field(description="Saved items in any status.")
    chunks: int = Field(description="Searchable chunks across all ready items.")
