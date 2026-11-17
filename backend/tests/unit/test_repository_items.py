from datetime import timedelta

import pytest

from app.domain.errors import DuplicateItemError, InvalidStatusTransitionError, ItemNotFoundError
from app.domain.models import ItemErrorCode, ItemStatus, ItemType, NewItem
from app.store.repository import Repository
from app.utils.text import PREVIEW_CHARS
from app.utils.time import is_timestamp
from tests.conftest import FakeClock, make_note


def new_url(url: str) -> NewItem:
    return NewItem(type=ItemType.URL, source_url=url, normalized_url=url)


def test_create_and_get_item(repo: Repository) -> None:
    item = make_note(repo, "hello", title="Greeting")

    fetched = repo.get_item(item.id)
    assert fetched == item
    assert item.status is ItemStatus.PENDING
    assert item.type is ItemType.NOTE
    assert len(item.id) == 32
    assert (item.attempts, item.chunk_count) == (0, 0)
    assert is_timestamp(item.created_at)
    assert item.created_at == item.updated_at


def test_get_missing_item_returns_none(repo: Repository) -> None:
    assert repo.get_item("0" * 32) is None


def test_duplicate_url_raises_with_existing_id(repo: Repository) -> None:
    first = repo.create_item(new_url("https://example.com/a"))
    with pytest.raises(DuplicateItemError) as excinfo:
        repo.create_item(new_url("https://example.com/a"))
    assert excinfo.value.existing_id == first.id
    assert excinfo.value.details == {"existing_id": first.id, "existing_status": "pending"}


def test_duplicate_note_hash_raises(repo: Repository) -> None:
    first = make_note(repo, "same text")
    with pytest.raises(DuplicateItemError) as excinfo:
        make_note(repo, "same text")
    assert excinfo.value.existing_id == first.id


def test_unique_indexes_are_partial_by_type(repo: Repository) -> None:
    repo.create_item(NewItem(type=ItemType.URL, normalized_url="u", content_hash="h"))
    note = repo.create_item(NewItem(type=ItemType.NOTE, content_hash="h"))
    assert repo.find_duplicate(ItemType.NOTE, content_hash="h") == note
    assert repo.find_duplicate(ItemType.URL, normalized_url="missing") is None


def test_list_is_newest_first_and_filters(repo: Repository) -> None:
    note = make_note(repo, "n1")
    url = repo.create_item(new_url("https://e.com"))
    newest = make_note(repo, "n2")
    repo.set_status(newest.id, ItemStatus.PROCESSING)

    assert [i.id for i in repo.list_items(limit=10).items] == [newest.id, url.id, note.id]
    by_type = repo.list_items(limit=10, item_type=ItemType.URL).items
    assert [i.id for i in by_type] == [url.id]
    by_status = repo.list_items(limit=10, status=ItemStatus.PENDING).items
    assert [i.id for i in by_status] == [url.id, note.id]


def test_keyset_pagination_visits_every_item_once_including_ties(
    repo: Repository, clock: FakeClock
) -> None:
    clock.step = timedelta(0)  # identical created_at for the first three: ties broken by id
    tied = [make_note(repo, f"tie{i}").id for i in range(3)]
    clock.step = timedelta(seconds=1)
    clock.now += clock.step
    later = [make_note(repo, f"later{i}").id for i in range(2)]

    seen, after, pages = [], None, 0
    while True:
        page = repo.list_items(limit=2, after=after)
        seen += [i.id for i in page.items]
        pages += 1
        if page.next_key is None:
            break
        after = page.next_key

    assert pages == 3
    assert seen == [*reversed(later), *sorted(tied, reverse=True)]


def test_last_page_has_no_next_key(repo: Repository) -> None:
    make_note(repo, "only")
    assert repo.list_items(limit=1).next_key is None
    assert repo.list_items(limit=5).next_key is None


def test_processing_increments_attempts_and_failed_records_error(repo: Repository) -> None:
    item = make_note(repo)
    repo.set_status(item.id, ItemStatus.PROCESSING)
    repo.set_status(item.id, ItemStatus.PENDING)
    repo.set_status(item.id, ItemStatus.PROCESSING)
    repo.set_status(
        item.id, ItemStatus.FAILED, error_code=ItemErrorCode.FETCH_TIMEOUT, error_message="slow"
    )

    failed = repo.get_item(item.id)
    assert failed is not None
    assert failed.status is ItemStatus.FAILED
    assert failed.attempts == 2
    assert (failed.error_code, failed.error_message) == (ItemErrorCode.FETCH_TIMEOUT, "slow")
    assert failed.updated_at > failed.created_at


ILLEGAL = [
    (ItemStatus.PENDING, ItemStatus.PENDING),
    (ItemStatus.PENDING, ItemStatus.FAILED),
    (ItemStatus.PROCESSING, ItemStatus.PROCESSING),
    (ItemStatus.FAILED, ItemStatus.PROCESSING),
    (ItemStatus.FAILED, ItemStatus.PENDING),
    (ItemStatus.FAILED, ItemStatus.FAILED),
]


def _move_to(repo: Repository, item_id: str, status: ItemStatus) -> None:
    if status is ItemStatus.PENDING:
        return
    repo.set_status(item_id, ItemStatus.PROCESSING)
    if status is ItemStatus.FAILED:
        repo.set_status(item_id, ItemStatus.FAILED, error_code=ItemErrorCode.FETCH_FAILED)


@pytest.mark.parametrize(("current", "target"), ILLEGAL)
def test_illegal_transitions_are_rejected_and_change_nothing(
    repo: Repository, current: ItemStatus, target: ItemStatus
) -> None:
    item = make_note(repo)
    _move_to(repo, item.id, current)
    before = repo.get_item(item.id)

    with pytest.raises(InvalidStatusTransitionError) as excinfo:
        repo.set_status(item.id, target)

    assert (excinfo.value.current, excinfo.value.target) == (current, target)
    assert repo.get_item(item.id) == before


@pytest.mark.parametrize("current", [ItemStatus.PENDING, ItemStatus.PROCESSING, ItemStatus.FAILED])
def test_ready_can_never_be_set_directly(repo: Repository, current: ItemStatus) -> None:
    item = make_note(repo)
    _move_to(repo, item.id, current)
    with pytest.raises(InvalidStatusTransitionError):
        repo.set_status(item.id, ItemStatus.READY)


def test_set_status_on_missing_item_raises_not_found(repo: Repository) -> None:
    with pytest.raises(ItemNotFoundError):
        repo.set_status("0" * 32, ItemStatus.PROCESSING)


def test_set_content_only_while_processing(repo: Repository) -> None:
    item = make_note(repo)
    with pytest.raises(InvalidStatusTransitionError):
        repo.set_content(item.id, title="T", extracted_text="x", content_hash="h2")

    repo.set_status(item.id, ItemStatus.PROCESSING)
    repo.set_content(item.id, title="T", extracted_text="body", content_hash="h2")
    updated = repo.get_item(item.id)
    assert updated is not None
    assert (updated.title, updated.extracted_text) == ("T", "body")


def test_delete_item_reports_whether_it_existed(repo: Repository) -> None:
    item = make_note(repo)
    assert repo.delete_item(item.id) is True
    assert repo.delete_item(item.id) is False
    assert repo.get_item(item.id) is None


# --- M3: summaries, raw_content handling, crash recovery ----------------------------------


def test_list_items_returns_summaries_without_raw_content(repo: Repository) -> None:
    long_text = "word " * 100
    repo.create_item(
        NewItem(
            type=ItemType.NOTE, content_hash="n1", raw_content=long_text, extracted_text=long_text
        )
    )
    repo.create_item(new_url("https://example.com/pending"))
    note_summary, url_summary = sorted(repo.list_items(limit=10).items, key=lambda i: i.type)
    assert not hasattr(note_summary, "raw_content")
    assert not hasattr(note_summary, "extracted_text")
    assert note_summary.preview is not None and len(note_summary.preview) <= PREVIEW_CHARS
    assert note_summary.preview.endswith("…")
    assert url_summary.preview is None  # no extracted text yet


def test_set_content_stores_raw_content_when_given(repo: Repository) -> None:
    item = repo.create_item(new_url("https://example.com/raw"))
    repo.set_status(item.id, ItemStatus.PROCESSING)
    repo.set_content(
        item.id, title="T", extracted_text="body", content_hash="h", raw_content="<html>…</html>"
    )
    stored = repo.get_item(item.id)
    assert stored is not None
    assert (stored.raw_content, stored.extracted_text) == ("<html>…</html>", "body")


def test_recover_interrupted_resets_processing_and_lists_pending_oldest_first(
    repo: Repository,
) -> None:
    first = make_note(repo, "one")
    second = make_note(repo, "two")
    done = make_note(repo, "three")
    repo.set_status(second.id, ItemStatus.PROCESSING)
    repo.set_status(done.id, ItemStatus.PROCESSING)
    repo.set_status(done.id, ItemStatus.FAILED, error_code=ItemErrorCode.FETCH_FAILED)

    assert repo.recover_interrupted() == [first.id, second.id]
    recovered = repo.get_item(second.id)
    assert recovered is not None and recovered.status is ItemStatus.PENDING
    assert recovered.attempts == 1  # attempts survive recovery
