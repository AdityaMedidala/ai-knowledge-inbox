import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import structlog
from asgi_correlation_id import correlation_id
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from starlette.concurrency import iterate_in_threadpool

from app.deps import AnsweringDep
from app.domain.errors import AppError, ErrorCode, ProviderError
from app.errors import INTERNAL_ERROR_MESSAGE, UPSTREAM_UNAVAILABLE_MESSAGE
from app.schemas.common import ErrorEnvelope
from app.schemas.query import (
    Citation,
    QueryRequest,
    QueryResponse,
    QueryTimings,
    debug_info,
    numbered_sources,
)
from app.services.answering import AnsweringService

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["query"])

ERRORS = {
    422: {"model": ErrorEnvelope, "description": "Invalid body"},
    503: {"model": ErrorEnvelope, "description": "Embedding or LLM provider unavailable"},
}
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


@router.post("/query", response_model=QueryResponse, responses=ERRORS)
def query(body: QueryRequest, answering: AnsweringDep) -> QueryResponse:
    """Answer from saved items with [n] citations. `mode: none` → not-found answer, no LLM call."""
    answer = answering.answer(body.question, body.top_k)
    return QueryResponse(
        answer=answer.text,
        mode=answer.mode,
        citations=[Citation.from_domain(c) for c in answer.citations],
        timings_ms=QueryTimings.from_domain(answer.timings),
        request_id=correlation_id.get(),
        debug=debug_info(answer.candidates) if body.debug else None,
    )


@router.post(
    "/query/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}, 422: ERRORS[422]},
)
async def query_stream(body: QueryRequest, answering: AnsweringDep) -> StreamingResponse:
    """SSE: meta → sources → token… → done, or error (then the stream closes)."""
    answering.validate_question(body.question)  # a 422 before the stream starts
    return StreamingResponse(
        _events(answering, body), media_type="text/event-stream", headers=SSE_HEADERS
    )


async def _events(answering: AnsweringService, body: QueryRequest) -> AsyncIterator[str]:
    yield _sse("meta", {"request_id": correlation_id.get()})
    try:
        prepared = await asyncio.to_thread(answering.prepare, body.question, body.top_k)
        sources = [s.model_dump(mode="json") for s in numbered_sources(prepared.sources)]
        yield _sse("sources", {"mode": prepared.mode, "sources": sources})
        parts: list[str] = []
        async for token in iterate_in_threadpool(answering.stream(prepared)):
            parts.append(token)
            yield _sse("token", {"text": token})
        answer = await asyncio.to_thread(answering.finish, prepared, "".join(parts))
        citations = [Citation.from_domain(c).model_dump(mode="json") for c in answer.citations]
        yield _sse("done", {"citations": citations, "timings_ms": answer.timings.as_dict()})
    except ProviderError as exc:
        logger.warning(
            "query.provider_error", provider=exc.provider, kind=exc.kind, retryable=exc.retryable
        )
        yield _error(ErrorCode.UPSTREAM_UNAVAILABLE, UPSTREAM_UNAVAILABLE_MESSAGE)
    except AppError as exc:
        yield _error(exc.code, exc.message)
    except Exception:
        logger.exception("query.stream_failed")
        yield _error(ErrorCode.INTERNAL_ERROR, INTERNAL_ERROR_MESSAGE)


def _error(code: ErrorCode, message: str) -> str:
    return _sse("error", {"code": code, "message": message})


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
