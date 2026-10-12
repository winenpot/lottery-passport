"""Campaign day and week boundaries.

The campaign day is a local calendar day in the campaign zone (Asia/Tehran);
the week runs Saturday to Friday. Clients take these from ``GET /config``
and never from the phone clock.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

_SATURDAY = 5  # date.weekday(): Monday is 0


@dataclass(frozen=True, slots=True)
class CampaignPeriod:
    day_key: str
    week_key: str
    day_ends_at: datetime
    week_ends_at: datetime


def _midnight(local_date_value: datetime, zone: ZoneInfo) -> datetime:
    return datetime.combine(local_date_value.date(), time.min, tzinfo=zone).astimezone(
        UTC
    )


def campaign_period(moment: datetime, zone: ZoneInfo) -> CampaignPeriod:
    local = moment.astimezone(zone)
    week_start = local - timedelta(days=(local.weekday() - _SATURDAY) % 7)
    return CampaignPeriod(
        day_key=f"D:{local.date().isoformat()}",
        week_key=f"W:{week_start.date().isoformat()}",
        day_ends_at=_midnight(local + timedelta(days=1), zone),
        week_ends_at=_midnight(week_start + timedelta(days=7), zone),
    )
