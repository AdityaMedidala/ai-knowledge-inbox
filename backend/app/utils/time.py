"""The one place timestamps are formatted.

Keyset pagination compares `created_at` as TEXT, so every stored timestamp must have identical
shape: UTC, microsecond precision, `Z` suffix — e.g. 2026-11-17T15:43:06.569224Z.
"""

from collections.abc import Callable
from datetime import UTC, datetime

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
TIMESTAMP_LENGTH = len("2026-01-01T00:00:00.000000Z")

Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_timestamp(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("Refusing to format a naive datetime; pass an aware one.")
    return moment.astimezone(UTC).strftime(TIMESTAMP_FORMAT)


def utc_now_iso(clock: Clock = utc_now) -> str:
    return format_timestamp(clock())


def is_timestamp(value: str) -> bool:
    if len(value) != TIMESTAMP_LENGTH:
        return False
    try:
        datetime.strptime(value, TIMESTAMP_FORMAT)
    except ValueError:
        return False
    return True
