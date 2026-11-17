"""Application error vocabulary. Pure Python so services can raise it without importing FastAPI."""

from enum import StrEnum
from typing import Any


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
        self, existing_id: str, message: str = "This item is already in your inbox."
    ) -> None:
        super().__init__(ErrorCode.DUPLICATE_ITEM, message, {"existing_id": existing_id})
        self.existing_id = existing_id


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


class EmbeddingDimensionError(ValueError):
    pass


class EmbeddingConfigMismatchError(RuntimeError):
    pass
