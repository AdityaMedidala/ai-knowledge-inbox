import base64

import pytest

from app.domain.errors import AppError, ErrorCode
from app.domain.models import PageKey
from app.utils.cursor import decode_cursor, encode_cursor

KEY = PageKey(created_at="2026-01-01T00:00:00.000000Z", id="a" * 32)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_round_trip() -> None:
    cursor = encode_cursor(KEY)
    assert "=" not in cursor
    assert decode_cursor(cursor) == KEY


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!!!not-base64!!!",
        b64(b"not json"),
        b64(b'{"created_at": "x"}'),
        b64(b'["2026-01-01T00:00:00.000000Z"]'),
        b64(b'["2026-01-01", "' + b"a" * 32 + b'"]'),
        b64(b'["2026-01-01T00:00:00.000000Z", "not-hex"]'),
        b64(b'["2026-01-01T00:00:00.000000Z", 5]'),
        "é",
        "A" * 300,
    ],
)
def test_invalid_cursor_is_a_validation_error(cursor: str) -> None:
    with pytest.raises(AppError) as excinfo:
        decode_cursor(cursor)
    assert excinfo.value.code is ErrorCode.VALIDATION_ERROR
    assert excinfo.value.details == {
        "fields": [
            {
                "loc": "query.cursor",
                "message": "Cursor is malformed; use next_cursor from a previous response.",
                "type": "invalid_cursor",
            }
        ]
    }
