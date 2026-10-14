"""Tehran (Asia/Tehran) period keys for cadence-based rewards.

One tested implementation so challenges (C1), games (G1) and venue
check-in (V1) all agree on "which Saturday does this week start on" and
"what day is it in Tehran right now" — the campaign's clock, never the
caller's. Keys match the format ``docs/ARCHITECTURE.md`` documents for
``challenge_claims.period_key``: a day is ``D:<date>``, a week is
``W:<date of the Saturday it starts>``, a month is ``M:<year>-<month>``.
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# Python's Monday=0 .. Sunday=6; the Tehran week starts Saturday.
_SATURDAY = 5


def _local_date(moment: datetime, zone: ZoneInfo) -> date:
    return moment.astimezone(zone).date()


def tehran_day_key(moment: datetime, zone: ZoneInfo) -> str:
    """``D:2026-10-14`` for the Tehran calendar day ``moment`` falls in."""
    return f"D:{_local_date(moment, zone).isoformat()}"


def tehran_week_key(moment: datetime, zone: ZoneInfo) -> str:
    """``W:2026-10-10``: the Saturday on or before ``moment``'s Tehran day."""
    today = _local_date(moment, zone)
    saturday = today - timedelta(days=(today.weekday() - _SATURDAY) % 7)
    return f"W:{saturday.isoformat()}"


def tehran_month_key(moment: datetime, zone: ZoneInfo) -> str:
    """``M:2026-10`` for the Tehran calendar month ``moment`` falls in."""
    today = _local_date(moment, zone)
    return f"M:{today.year:04d}-{today.month:02d}"
