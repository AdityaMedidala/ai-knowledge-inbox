"""Pure-ASGI middleware: access logging and the catch-all for unhandled exceptions."""

import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errors import internal_error_response

logger = structlog.get_logger(__name__)


class AccessLogMiddleware:
    """Emits one `http.request` line per HTTP request (replaces uvicorn's access log)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            logger.info(
                "http.request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )


class UnhandledErrorMiddleware:
    """Turns any uncaught exception into the INTERNAL_ERROR envelope and logs the stack.

    Must sit inside CorrelationIdMiddleware and CORSMiddleware so the 500 response still
    carries X-Request-ID and CORS headers. If the response already started (e.g. mid-stream),
    nothing safe can be sent, so the exception is re-raised after logging.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking_start(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking_start)
        except Exception:
            logger.exception(
                "unhandled_exception",
                method=scope["method"],
                path=scope["path"],
                response_started=response_started,
            )
            if response_started:
                raise
            await internal_error_response()(scope, receive, send)
