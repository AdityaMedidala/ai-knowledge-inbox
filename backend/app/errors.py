"""HTTP mapping for errors: status codes, the error envelope, and FastAPI exception handlers.

Unhandled exceptions are NOT handled here: a handler registered for `Exception` is installed on
Starlette's ServerErrorMiddleware, outside all user middleware, so its responses would lack
X-Request-ID and CORS headers. See `app.middleware.UnhandledErrorMiddleware` instead.
"""

from collections.abc import Sequence
from http import HTTPStatus
from typing import Any

import structlog
from asgi_correlation_id import correlation_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import AppError, ErrorCode, ProviderError
from app.schemas.common import ErrorBody, ErrorEnvelope

logger = structlog.get_logger(__name__)

STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.BAD_REQUEST: HTTPStatus.BAD_REQUEST,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.METHOD_NOT_ALLOWED: HTTPStatus.METHOD_NOT_ALLOWED,
    ErrorCode.DUPLICATE_ITEM: HTTPStatus.CONFLICT,
    ErrorCode.URL_NOT_ALLOWED: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.UPSTREAM_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.INBOX_FULL: HTTPStatus.CONFLICT,
    ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
}

_CODE_BY_HTTP_STATUS: dict[int, ErrorCode] = {
    HTTPStatus.NOT_FOUND: ErrorCode.NOT_FOUND,
    HTTPStatus.METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
}

INTERNAL_ERROR_MESSAGE = "An unexpected error occurred. Quote the request_id when reporting it."
UPSTREAM_UNAVAILABLE_MESSAGE = "The AI provider is unavailable right now. Please try again shortly."


def error_response(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    status_code: int | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ErrorBody(code=code, message=message, details=details),
        request_id=correlation_id.get(),
    )
    return JSONResponse(
        status_code=status_code or STATUS_BY_CODE[code],
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


def internal_error_response() -> JSONResponse:
    return error_response(ErrorCode.INTERNAL_ERROR, INTERNAL_ERROR_MESSAGE)


def _field_errors(errors: Sequence[Any]) -> list[dict[str, str]]:
    """Reduce pydantic errors to loc/message/type; never echo the submitted input back."""
    return [
        {
            "loc": ".".join(str(part) for part in err.get("loc", ())),
            "message": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in errors
    ]


async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    logger.info("request.app_error", error_code=exc.code, message=exc.message)
    retry_after = (exc.details or {}).get("retry_after_s")
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
    return error_response(exc.code, exc.message, exc.details, headers=headers)


async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = _field_errors(exc.errors())
    logger.info("request.validation_failed", fields=[f["loc"] for f in fields])
    return error_response(
        ErrorCode.VALIDATION_ERROR,
        "Request validation failed. See details.fields.",
        {"fields": fields},
    )


async def _handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _CODE_BY_HTTP_STATUS.get(exc.status_code)
    if code is None:
        code = ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST
    message = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(code, message, headers=exc.headers, status_code=exc.status_code)


async def _handle_provider_error(_: Request, exc: ProviderError) -> JSONResponse:
    logger.warning(
        "request.provider_error", provider=exc.provider, kind=exc.kind, retryable=exc.retryable
    )
    return error_response(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        UPSTREAM_UNAVAILABLE_MESSAGE,
        {"provider": exc.provider, "kind": exc.kind, "retryable": exc.retryable},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(ProviderError, _handle_provider_error)
