from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.application.venues import VenueCatalogue
from app.domain.calendar import CampaignPeriod, campaign_period
from app.domain.nickname import NICKNAME_MAX_LENGTH, NICKNAME_MIN_LENGTH
from app.domain.venues import SUPPORTED_CITIES, City, Venue


@dataclass(frozen=True, slots=True)
class AppConfig:
    server_time: datetime
    timezone: str
    period: CampaignPeriod
    terms_version: str
    terms_required: bool
    scans_per_day: int
    nickname_min_length: int
    nickname_max_length: int
    location_cities: tuple[City, ...]
    venues: list[Venue]


class AppConfigService:
    """What the client needs before anyone signs in (``GET /config``)."""

    def __init__(
        self,
        clock: Clock,
        zone: ZoneInfo,
        terms_version: str,
        scans_per_day: int,
        venues: VenueCatalogue,
        *,
        terms_required: bool = True,
    ) -> None:
        self._venues = venues
        self._clock = clock
        self._zone = zone
        self._terms_version = terms_version
        self._terms_required = terms_required
        self._scans_per_day = scans_per_day

    async def current(self) -> AppConfig:
        now = self._clock.now()
        return AppConfig(
            server_time=now,
            timezone=self._zone.key,
            period=campaign_period(now, self._zone),
            terms_version=self._terms_version,
            terms_required=self._terms_required,
            scans_per_day=self._scans_per_day,
            nickname_min_length=NICKNAME_MIN_LENGTH,
            nickname_max_length=NICKNAME_MAX_LENGTH,
            location_cities=SUPPORTED_CITIES,
            venues=await self._venues.list_active(),
        )
