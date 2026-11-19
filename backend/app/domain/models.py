"""Plain domain types shared by the store and services. No framework imports."""

from dataclasses import dataclass
from enum import StrEnum

from app.utils.text import preview_of


class ItemType(StrEnum):
    NOTE = "note"
    URL = "url"


class ItemStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ItemErrorCode(StrEnum):
    """Why an item failed asynchronously. Stored on the item, never an HTTP status."""

    FETCH_FAILED = "FETCH_FAILED"
    FETCH_BLOCKED = "FETCH_BLOCKED"
    FETCH_TIMEOUT = "FETCH_TIMEOUT"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"  # an unexpected bug; details are in the logs


@dataclass(frozen=True, slots=True)
class NewItem:
    type: ItemType
    title: str | None = None
    source_url: str | None = None
    normalized_url: str | None = None
    content_hash: str | None = None
    raw_content: str | None = None
    extracted_text: str | None = None  # notes have it at submit time; URLs after extraction


@dataclass(frozen=True, slots=True)
class Item:
    id: str
    type: ItemType
    title: str | None
    source_url: str | None
    normalized_url: str | None
    content_hash: str | None
    raw_content: str | None
    extracted_text: str | None
    status: ItemStatus
    error_code: ItemErrorCode | None
    error_message: str | None
    attempts: int
    chunk_count: int
    created_at: str
    updated_at: str

    def summary(self) -> "ItemSummary":
        return ItemSummary(
            id=self.id,
            type=self.type,
            title=self.title,
            source_url=self.source_url,
            status=self.status,
            error_code=self.error_code,
            error_message=self.error_message,
            chunk_count=self.chunk_count,
            created_at=self.created_at,
            updated_at=self.updated_at,
            preview=preview_of(self.extracted_text),
        )


@dataclass(frozen=True, slots=True)
class ItemSummary:
    """List-view projection: never carries raw_content or the full extracted text."""

    id: str
    type: ItemType
    title: str | None
    source_url: str | None
    status: ItemStatus
    error_code: ItemErrorCode | None
    error_message: str | None
    chunk_count: int
    created_at: str
    updated_at: str
    preview: str | None


@dataclass(frozen=True, slots=True)
class PageKey:
    """Keyset position: the (created_at, id) of the last item on the previous page."""

    created_at: str
    id: str


@dataclass(frozen=True, slots=True)
class ItemPage:
    items: list[ItemSummary]
    next_key: PageKey | None


@dataclass(frozen=True, slots=True)
class InboxStats:
    items: int
    chunks: int


@dataclass(frozen=True, slots=True)
class NewChunk:
    ordinal: int
    section: str | None
    context_header: str
    text: str
    token_count: int


@dataclass(frozen=True, slots=True)
class ChunkRecord:
    id: int
    item_id: str
    ordinal: int
    section: str | None
    context_header: str
    text: str
    token_count: int
    item_title: str | None
    item_type: ItemType
    source_url: str | None


@dataclass(frozen=True, slots=True)
class VectorHit:
    chunk_id: int
    position: int  # 1-based rank within the vector arm
    similarity: float  # 1 - cosine distance


@dataclass(frozen=True, slots=True)
class KeywordHit:
    chunk_id: int
    position: int  # 1-based rank within the keyword arm
    bm25: float  # raw FTS5 bm25; lower (more negative) is better


class RetrievalMode(StrEnum):
    """How well the saved items cover a question; `none` means the LLM is never called."""

    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """A fused candidate with its full score breakdown (ranks are 1-based, None = not in arm)."""

    chunk: ChunkRecord
    vec_rank: int | None
    fts_rank: int | None
    rrf: float
    similarity: float | None  # None when only the keyword arm found it
    rerank: float | None = None

    @property
    def score(self) -> float | None:
        """The relevance score shown to users and used by the gate: rerank if present."""
        return self.rerank if self.rerank is not None else self.similarity
