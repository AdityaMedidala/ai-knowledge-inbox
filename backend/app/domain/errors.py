"""Application error vocabulary. Pure Python so services can raise it without importing FastAPI."""

from enum import StrEnum
from typing import Any

from app.domain.models import ItemErrorCode


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    DUPLICATE_ITEM = "DUPLICATE_ITEM"
    URL_NOT_ALLOWED = "URL_NOT_ALLOWED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """An expected failure with a stable code and a message safe to show the client."""

    def __init__(
        self, code: ErrorCode, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


class DuplicateItemError(AppError):
    def __init__(
        self,
        existing_id: str,
        existing_status: str,
        message: str = "This item is already in your inbox.",
    ) -> None:
        details = {"existing_id": existing_id, "existing_status": existing_status}
        super().__init__(ErrorCode.DUPLICATE_ITEM, message, details)
        self.existing_id = existing_id
        self.existing_status = existing_status


class InvalidStatusTransitionError(Exception):
    def __init__(self, item_id: str, current: str | None, target: str) -> None:
        super().__init__(f"Item {item_id}: illegal status transition {current} -> {target}.")
        self.item_id, self.current, self.target = item_id, current, target


class ItemNotFoundError(Exception):
    def __init__(self, item_id: str) -> None:
        super().__init__(f"Item {item_id} does not exist.")
        self.item_id = item_id


class ItemNotProcessingError(Exception):
    """The item vanished or left 'processing' while a job was working on it."""

    def __init__(self, item_id: str, current: str | None) -> None:
        state = "deleted" if current is None else f"in status '{current}'"
        super().__init__(f"Item {item_id} is {state}, expected 'processing'.")
        self.item_id, self.current = item_id, current


class IngestError(Exception):
    """One ingestion stage failed for one item. `message` is stored on the item and shown in the
    UI, so it must never contain secrets (no query strings, no document text)."""

    def __init__(self, code: ItemErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


class EmbeddingDimensionError(ValueError):
    pass


class EmbeddingConfigMismatchError(RuntimeError):
    pass


class ProviderErrorKind(StrEnum):
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    AUTH = "auth"
    BAD_REQUEST = "bad_request"  # a 4xx we caused
    INVALID_RESPONSE = "invalid_response"  # wrong dims, malformed or missing items


RETRYABLE_PROVIDER_ERRORS = frozenset(
    {ProviderErrorKind.RATE_LIMITED, ProviderErrorKind.TIMEOUT, ProviderErrorKind.UNAVAILABLE}
)


class ProviderError(Exception):
    """An embedding / chat / rerank provider call failed. `message` is for logs, not clients."""

    def __init__(
        self,
        kind: ProviderErrorKind,
        provider: str,
        message: str,
        *,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(f"{provider} {kind}: {message}")
        self.kind = kind
        self.provider = provider
        self.message = message
        self.retryable = kind in RETRYABLE_PROVIDER_ERRORS if retryable is None else retryable
