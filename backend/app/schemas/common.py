from typing import Any

from pydantic import BaseModel, Field

from app.domain.errors import ErrorCode


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class ErrorEnvelope(BaseModel):
    """Shape of every non-2xx JSON response."""

    error: ErrorBody
    request_id: str | None = Field(description="Same value as the X-Request-ID response header.")
