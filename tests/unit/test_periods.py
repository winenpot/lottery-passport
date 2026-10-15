"""Tehran period keys and boundaries (C1/G1/V1 share this module)."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.domain.periods import (
    tehran_day_key,
    tehran_day_start,
    tehran_month_key,
    tehran_month_start,
    tehran_week_key,
    tehran_week_start,
)

ZONE = ZoneInfo("Asia/Tehran")


def test_day_key_and_start_agree_on_the_same_tehran_day() -> None:
    # 2026-10-15 09:00 UTC is 2026-10-15 12:30 in Tehran (UTC+3:30).
    moment = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    assert tehran_day_key(moment, ZONE) == "D:2026-10-15"
    start = tehran_day_start(moment, ZONE)
    assert start.astimezone(ZONE).strftime("%H:%M:%S") == "00:00:00"
    assert tehran_day_key(start, ZONE) == "D:2026-10-15"


def test_day_key_rolls_over_at_tehran_midnight_not_utc_midnight() -> None:
    # 2026-10-14 21:00 UTC is 2026-10-15 00:30 in Tehran: already the 15th.
    just_after_midnight = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)
    assert tehran_day_key(just_after_midnight, ZONE) == "D:2026-10-15"


def test_week_starts_on_saturday() -> None:
    # 2026-10-15 is a Thursday; the week's Saturday is 2026-10-10.
    moment = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    assert tehran_week_key(moment, ZONE) == "W:2026-10-10"
    start = tehran_week_start(moment, ZONE)
    local_start = start.astimezone(ZONE)
    assert (local_start.date().isoformat(), local_start.weekday()) == (
        "2026-10-10",
        5,  # Saturday
    )


def test_month_key_and_start_use_the_tehran_calendar_month() -> None:
    moment = datetime(2026, 10, 1, 19, 0, tzinfo=UTC)  # 2026-10-01 22:30 Tehran
    assert tehran_month_key(moment, ZONE) == "M:2026-10"
    start = tehran_month_start(moment, ZONE)
    assert start.astimezone(ZONE).date().isoformat() == "2026-10-01"


def test_month_start_is_before_the_moment_it_is_computed_from() -> None:
    moment = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    assert tehran_month_start(moment, ZONE) <= moment
    assert tehran_week_start(moment, ZONE) <= moment
    assert tehran_day_start(moment, ZONE) <= moment
