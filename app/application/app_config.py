from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.application.venues import VenueCatalogue
from app.domain.calendar import CampaignPeriod, campaign_period
from app.domain.nickname import NICKNAME_MAX_LENGTH, NICKNAME_MIN_LENGTH
from app.domain.passports import CAMPAIGN_BY_CITY
from app.domain.venues import SUPPORTED_CITIES, City, Venue


@dataclass(frozen=True, slots=True)
class Flavor:
    """One of the 7 passport-city SKUs, as `/config.flavors` serves it."""

    id: str
    code: str


FLAVORS: tuple[Flavor, ...] = tuple(
    Flavor(id=campaign.value, code=city.value)
    for city, campaign in CAMPAIGN_BY_CITY.items()
)


@dataclass(frozen=True, slots=True)
class FeatureFlags:
    """Read side of `/config.features` (F1). No route enforces these yet;
    that is F1's write side. mini_games is on because it already shipped
    (G1); the rest stay off until their feature ships or gets legal sign-off
    (leaderboard/L1, venue_checkin/V1, diamonds/DI1).
    """

    mini_games: bool = True
    leaderboard: bool = False
    venue_checkin: bool = False
    diamonds: bool = False


@dataclass(frozen=True, slots=True)
class AppConfig:
    server_time: datetime
    timezone: str
    period: CampaignPeriod
    terms_version: str
    terms_required: bool
    terms_url: str | None
    privacy_url: str | None
    scans_per_day: int
    nickname_min_length: int
    nickname_max_length: int
    location_cities: tuple[City, ...]
    venues: list[Venue]
    flavors: tuple[Flavor, ...]
    features: FeatureFlags


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
        terms_url: str | None = None,
        privacy_url: str | None = None,
        features: FeatureFlags | None = None,
    ) -> None:
        self._venues = venues
        self._clock = clock
        self._zone = zone
        self._terms_version = terms_version
        self._terms_required = terms_required
        self._terms_url = terms_url
        self._privacy_url = privacy_url
        self._scans_per_day = scans_per_day
        self._features = features or FeatureFlags()

    async def current(self) -> AppConfig:
        now = self._clock.now()
        return AppConfig(
            server_time=now,
            timezone=self._zone.key,
            period=campaign_period(now, self._zone),
            terms_version=self._terms_version,
            terms_required=self._terms_required,
            terms_url=self._terms_url,
            privacy_url=self._privacy_url,
            scans_per_day=self._scans_per_day,
            nickname_min_length=NICKNAME_MIN_LENGTH,
            nickname_max_length=NICKNAME_MAX_LENGTH,
            location_cities=SUPPORTED_CITIES,
            venues=await self._venues.list_active(),
            flavors=FLAVORS,
            features=self._features,
        )
