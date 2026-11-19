from typing import Annotated

import structlog
from fastapi import APIRouter, Query, Response, status

from app.deps import RepositoryDep
from app.domain.errors import AppError, ErrorCode
from app.domain.models import ItemStatus, ItemType
from app.schemas.common import ErrorEnvelope
from app.schemas.items import ItemDetail, ItemList, ItemStats, ItemSummary
from app.utils.cursor import MAX_CURSOR_LENGTH, decode_cursor, encode_cursor

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["items"])

NOT_FOUND = {404: {"model": ErrorEnvelope, "description": "No item with this id"}}


@router.get("/items", response_model=ItemList, responses={422: {"model": ErrorEnvelope}})
def list_items(
    repo: RepositoryDep,
    status_filter: Annotated[ItemStatus | None, Query(alias="status")] = None,
    type_filter: Annotated[ItemType | None, Query(alias="type")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query(max_length=MAX_CURSOR_LENGTH)] = None,
) -> ItemList:
    """Newest first. Pass `next_cursor` back as `cursor` for the next page."""
    after = decode_cursor(cursor) if cursor else None
    page = repo.list_items(limit=limit, status=status_filter, item_type=type_filter, after=after)
    return ItemList(
        items=[ItemSummary.from_domain(summary) for summary in page.items],
        next_cursor=encode_cursor(page.next_key) if page.next_key else None,
    )


# Declared before /items/{item_id} so "stats" is not taken for an id.
@router.get("/items/stats", response_model=ItemStats)
def item_stats(repo: RepositoryDep) -> ItemStats:
    """Totals for the whole inbox (the list endpoint is paginated, so it can't give these)."""
    stats = repo.stats()
    return ItemStats(items=stats.items, chunks=stats.chunks)


@router.get("/items/{item_id}", response_model=ItemDetail, responses=NOT_FOUND)
def get_item(item_id: str, repo: RepositoryDep) -> ItemDetail:
    item = repo.get_item(item_id)
    if item is None:
        raise _not_found()
    return ItemDetail.from_item(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND)
def delete_item(item_id: str, repo: RepositoryDep) -> Response:
    """Works in any status. A job still running on the item notices and drops its result."""
    if not repo.delete_item(item_id):
        raise _not_found()
    logger.info("items.deleted", item_id=item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Item not found.")
