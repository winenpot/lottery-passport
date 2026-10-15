"""Tehran period keys and boundaries (C1/G1/V1 share this module)."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.domain.periods import (
    current_streak,
    tehran_date,
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


def test_tehran_date_matches_the_day_key() -> None:
    # Same Tehran-midnight-rollover case as the day key test above.
    moment = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)
    assert tehran_date(moment, ZONE) == date(2026, 10, 15)


def test_current_streak_counts_consecutive_days_ending_today() -> None:
    today = date(2026, 10, 15)
    claimed = {date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 15)}
    assert current_streak(claimed, today) == 3


def test_current_streak_does_not_break_before_todays_checkin() -> None:
    # Yesterday's chain is intact; today just has not been claimed YET --
    # the streak should not look broken before the player has had a chance.
    today = date(2026, 10, 15)
    claimed = {date(2026, 10, 13), date(2026, 10, 14)}
    assert current_streak(claimed, today) == 2


def test_current_streak_breaks_on_a_missed_day() -> None:
    # A full day (the 14th) was skipped: only today counts.
    today = date(2026, 10, 15)
    claimed = {date(2026, 10, 12), date(2026, 10, 13), date(2026, 10, 15)}
    assert current_streak(claimed, today) == 1


def test_current_streak_is_zero_with_no_claims() -> None:
    assert current_streak(set(), date(2026, 10, 15)) == 0


def test_rebuilding_a_streak_after_a_gap_does_not_inherit_the_old_length() -> None:
    """The exact scenario the economy relies on NOT paying twice: break a
    streak, rebuild a new (shorter) one -- it must not silently chain back
    onto the old run just because both runs exist in the claimed set."""
    today = date(2026, 10, 15)
    claimed = {
        date(2026, 10, 1),
        date(2026, 10, 2),
        date(2026, 10, 3),  # an old 3-day run, then a gap
        date(2026, 10, 15),  # rebuilt today, day 1 of a new run
    }
    assert current_streak(claimed, today) == 1
