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
