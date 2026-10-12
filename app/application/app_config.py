from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.domain.calendar import CampaignPeriod, campaign_period
from app.domain.nickname import NICKNAME_MAX_LENGTH, NICKNAME_MIN_LENGTH


@dataclass(frozen=True, slots=True)
class AppConfig:
    server_time: datetime
    timezone: str
    period: CampaignPeriod
    terms_version: str
    scans_per_day: int
    nickname_min_length: int
    nickname_max_length: int


class AppConfigService:
    """What the client needs before anyone signs in (``GET /config``)."""

    def __init__(
        self,
        clock: Clock,
        zone: ZoneInfo,
        terms_version: str,
        scans_per_day: int,
    ) -> None:
        self._clock = clock
        self._zone = zone
        self._terms_version = terms_version
        self._scans_per_day = scans_per_day

    def current(self) -> AppConfig:
        now = self._clock.now()
        return AppConfig(
            server_time=now,
            timezone=self._zone.key,
            period=campaign_period(now, self._zone),
            terms_version=self._terms_version,
            scans_per_day=self._scans_per_day,
            nickname_min_length=NICKNAME_MIN_LENGTH,
            nickname_max_length=NICKNAME_MAX_LENGTH,
        )
