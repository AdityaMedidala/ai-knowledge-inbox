"""structlog setup. Pretty console output in dev, one JSON object per line when LOG_JSON=true.

stdlib loggers (uvicorn, libraries) are routed through the same processors, so every line,
whatever its origin, carries `request_id` while a request is in flight.
"""

import logging
import sys

import structlog
from asgi_correlation_id import correlation_id
from structlog.types import EventDict, Processor, WrappedLogger


def _add_request_id(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    request_id = correlation_id.get()
    if request_id is not None:
        event_dict.setdefault("request_id", request_id)
    return event_dict


def configure_logging(level: str, json_logs: bool) -> None:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    final: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if json_logs:
        final += [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
    else:
        final.append(structlog.dev.ConsoleRenderer())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(foreign_pre_chain=shared, processors=final)
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn installs its own handlers before the app factory runs; send them to root instead.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    # AccessLogMiddleware's `http.request` replaces uvicorn's access log entirely.
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False
