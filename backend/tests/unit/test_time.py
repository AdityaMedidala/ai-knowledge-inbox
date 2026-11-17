from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.utils.time import format_timestamp, is_timestamp, utc_now_iso


def test_format_is_exact_utc_microseconds_z() -> None:
    moment = datetime(2026, 11, 17, 15, 43, 6, 5, tzinfo=UTC)
    assert format_timestamp(moment) == "2026-11-17T15:43:06.000005Z"


def test_other_timezones_are_normalized_to_utc() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    moment = datetime(2026, 11, 17, 21, 13, 6, tzinfo=ist)
    assert format_timestamp(moment) == "2026-11-17T15:43:06.000000Z"


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="naive"):
        format_timestamp(datetime(2026, 1, 1))


def test_utc_now_iso_uses_injected_clock() -> None:
    assert utc_now_iso(lambda: datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00.000000Z"


@pytest.mark.parametrize(
    ("value", "valid"),
    [
        ("2026-01-01T00:00:00.000000Z", True),
        ("2026-01-01T00:00:00Z", False),
        ("2026-01-01T00:00:00.000000+00:00", False),
        ("2026-13-01T00:00:00.000000Z", False),
        ("garbage", False),
    ],
)
def test_is_timestamp(value: str, valid: bool) -> None:
    assert is_timestamp(value) is valid
