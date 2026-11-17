"""Opaque keyset cursors: URL-safe base64 of JSON [created_at, id]."""

import base64
import json
import re

from app.domain.errors import AppError, ErrorCode
from app.domain.models import PageKey
from app.utils.time import is_timestamp

MAX_CURSOR_LENGTH = 256
_ITEM_ID = re.compile(r"[0-9a-f]{32}")


def encode_cursor(key: PageKey) -> str:
    raw = json.dumps([key.created_at, key.id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> PageKey:
    if len(cursor) > MAX_CURSOR_LENGTH:
        raise _invalid_cursor()
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except ValueError as exc:  # binascii.Error, JSONDecodeError and Unicode errors are ValueErrors
        raise _invalid_cursor() from exc

    match value:
        case [str(created_at), str(item_id)] if is_timestamp(created_at) and _ITEM_ID.fullmatch(
            item_id
        ):
            return PageKey(created_at=created_at, id=item_id)
        case _:
            raise _invalid_cursor()


def _invalid_cursor() -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        "Invalid pagination cursor.",
        {
            "fields": [
                {
                    "loc": "query.cursor",
                    "message": "Cursor is malformed; use next_cursor from a previous response.",
                    "type": "invalid_cursor",
                }
            ]
        },
    )
