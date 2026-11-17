import asyncio

import structlog
from fastapi import APIRouter, Response, status

from app.deps import SubmissionDep, WorkerDep
from app.domain.models import Item
from app.schemas.common import ErrorEnvelope
from app.schemas.ingest import IngestRequest, IngestResponse, NoteIngest
from app.schemas.items import ItemSummary
from app.services.submission import SubmissionService
from app.worker import WorkerStoppedError

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["ingest"])


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IngestResponse,
    responses={
        409: {"model": ErrorEnvelope, "description": "Already saved (details.existing_id)"},
        422: {"model": ErrorEnvelope, "description": "Invalid body or URL not allowed"},
    },
)
async def ingest(
    body: IngestRequest, submission: SubmissionDep, worker: WorkerDep, response: Response
) -> IngestResponse:
    """Validate and store the item as 'pending'; the worker fetches, chunks and embeds it."""
    item = await asyncio.to_thread(_submit, submission, body)  # committed when this returns
    logger.info("ingest.accepted", item_id=item.id, item_type=item.type)
    try:
        worker.enqueue(item.id)  # on the event loop: the queue is not thread-safe
    except WorkerStoppedError:
        logger.warning("ingest.enqueue_failed", item_id=item.id)  # startup recovery picks it up
    response.headers["Location"] = f"/items/{item.id}"
    return IngestResponse(item=ItemSummary.from_domain(item.summary()))


def _submit(submission: SubmissionService, body: IngestRequest) -> Item:
    if isinstance(body, NoteIngest):
        return submission.submit_note(body.content, body.title)
    return submission.submit_url(body.url)
