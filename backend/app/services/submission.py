"""Synchronous submit-time checks for POST /ingest. No network: fetching happens in the worker."""

from app.domain.errors import AppError, DuplicateItemError, ErrorCode, field_validation_error
from app.domain.models import Item, ItemType, NewItem
from app.services.url_guard import UrlRejectedError, check_url
from app.store.repository import Repository
from app.utils.text import derive_title, normalize_note, sha256_hex
from app.utils.urls import normalize_url

DUPLICATE_URL_MESSAGE = "This URL is already in your inbox."
DUPLICATE_NOTE_MESSAGE = "This note is already in your inbox."


class SubmissionService:
    def __init__(self, repo: Repository, *, note_max_chars: int) -> None:
        self._repo = repo
        self._note_max_chars = note_max_chars

    def submit_note(self, content: str, title: str | None) -> Item:
        if len(content) > self._note_max_chars:
            raise field_validation_error(
                "body.content",
                f"Note is too long ({len(content)} characters; the limit is "
                f"{self._note_max_chars}).",
                "string_too_long",
            )
        content_hash = sha256_hex(normalize_note(content))
        existing = self._repo.find_duplicate(ItemType.NOTE, content_hash=content_hash)
        if existing is not None:
            raise DuplicateItemError(existing.id, existing.status, DUPLICATE_NOTE_MESSAGE)
        return self._create(
            NewItem(
                type=ItemType.NOTE,
                title=title or derive_title(content),
                content_hash=content_hash,
                raw_content=content,
                extracted_text=content,  # notes need no extraction
            ),
            DUPLICATE_NOTE_MESSAGE,
        )

    def submit_url(self, url: str) -> Item:
        try:
            check_url(url)
            normalized = normalize_url(url)
        except UrlRejectedError as exc:
            raise AppError(ErrorCode.URL_NOT_ALLOWED, exc.message, {"reason": exc.reason}) from exc
        existing = self._repo.find_duplicate(ItemType.URL, normalized_url=normalized)
        if existing is not None:
            raise DuplicateItemError(existing.id, existing.status, DUPLICATE_URL_MESSAGE)
        return self._create(
            NewItem(type=ItemType.URL, source_url=url, normalized_url=normalized),
            DUPLICATE_URL_MESSAGE,
        )

    def _create(self, new: NewItem, duplicate_message: str) -> Item:
        """Insert (autocommitted). A concurrent duplicate loses on the unique index."""
        try:
            return self._repo.create_item(new)
        except DuplicateItemError as exc:
            raise DuplicateItemError(
                exc.existing_id, exc.existing_status, duplicate_message
            ) from exc
