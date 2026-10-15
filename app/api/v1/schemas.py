from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.application.app_config import AppConfig
from app.application.challenges import (
    AchievementUnlock,
    ChallengeClaimResult,
    ChallengeProgress,
)
from app.application.redemption_codes import RedemptionResult
from app.application.teams import FlavorProgress, TeamStatus
from app.application.wallets import WalletView
from app.domain.achievements import UnlockedAchievement
from app.domain.avatars import Avatar
from app.domain.passports import CAMPAIGN_BY_CITY, PassportProgress
from app.domain.users import User


class AuthenticationRequest(BaseModel):
    identifier: str = Field(
        min_length=3,
        max_length=32,
        examples=["0912 345 6789"],
        description=(
            "An Iranian mobile number: Persian or Latin digits, spaces, "
            "+98/0098/98 or a leading 0. 'identifier' kept as the field name "
            "for one release so an older client sending 'phone'-shaped "
            "values here keeps working."
        ),
    )


class AuthenticationVerification(BaseModel):
    identifier: str = Field(min_length=3, max_length=32, examples=["0912 345 6789"])
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class AuthenticationRequested(BaseModel):
    resend_after_seconds: int = Field(
        description="Seconds to wait before POSTing /auth/request again."
    )
    expires_in_seconds: int = Field(description="How long the code stays valid.")
    code_length: int
    test_code: str | None = Field(
        default=None,
        description=(
            "Demo only: the code itself, for test numbers "
            "starting 0969 (no SMS is sent). Absent for real numbers and "
            "always absent in production."
        ),
    )


class UserResponse(BaseModel):
    id: UUID
    identifier: str
    display_name: str | None
    nickname: str | None
    home_venue_id: str | None
    location_city: str | None
    avatar_id: str | None
    team: str | None = Field(
        description="Current flavor team (campaign slug, e.g. 'tokyo'), or null."
    )
    last_scanned_flavor: str | None = Field(
        description="Flavor of the most recently redeemed code, or null."
    )
    terms_accepted: bool
    profile_complete: bool
    account_status: str
    verification_status: str
    role: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(
        cls,
        user: User,
        *,
        team: str | None = None,
        last_scanned_flavor: str | None = None,
    ) -> "UserResponse":
        return cls(
            id=user.id,
            identifier=user.identifier,
            display_name=user.display_name,
            nickname=user.nickname,
            home_venue_id=user.home_venue_id,
            location_city=user.location_city,
            avatar_id=user.avatar_id,
            team=team,
            last_scanned_flavor=last_scanned_flavor,
            terms_accepted=user.terms_accepted_at is not None,
            profile_complete=user.profile_complete,
            account_status=user.account_status.value,
            verification_status=user.verification_status.value,
            role=user.role.value,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class UserPageResponse(BaseModel):
    items: list[UserResponse]
    next_cursor: str | None = Field(
        description="Pass as ``cursor`` for the next page; null on the last page."
    )


class UserUpdate(BaseModel):
    """Every field is optional; only the ones sent are changed."""

    display_name: str | None = Field(default=None, max_length=100)
    nickname: str | None = Field(
        default=None,
        max_length=64,
        description="3-16 characters; rules in docs/SECURITY.md.",
    )
    accept_terms_version: str | None = Field(
        default=None, max_length=20, description="Must equal ``terms_version``."
    )
    home_venue_id: str | None = Field(
        default=None,
        max_length=40,
        description="An ``id`` from ``GET /config`` ``venues``.",
    )
    location_city: str | None = Field(
        default=None,
        max_length=40,
        description="One of ``location_cities`` ids from ``GET /config``.",
    )
    avatar_id: str | None = Field(
        default=None,
        max_length=40,
        description="An unlocked ``id`` from ``GET /avatars``.",
    )


class NicknameLimits(BaseModel):
    min_length: int
    max_length: int


class ConfigLimits(BaseModel):
    scans_per_day: int


class LocationCityResponse(BaseModel):
    id: str = Field(examples=["tehran"])
    name: str = Field(description="Persian name.", examples=["تهران"])


class VenueResponse(BaseModel):
    id: str
    name: str
    location_city: str = Field(description="One of location_cities ids.")
    address: str | None = Field(
        description="Street address in Persian; null when unknown."
    )


class ConfigResponse(BaseModel):
    server_time: datetime
    timezone: str
    day_key: str
    week_key: str
    day_ends_at: datetime
    week_ends_at: datetime
    terms_version: str
    limits: ConfigLimits
    nickname: NicknameLimits
    location_cities: list[LocationCityResponse] = Field(
        description="Real cities with lounges. Not passport cities (flavors)."
    )
    venues: list[VenueResponse]

    @classmethod
    def from_domain(cls, config: AppConfig) -> "ConfigResponse":
        return cls(
            server_time=config.server_time,
            timezone=config.timezone,
            day_key=config.period.day_key,
            week_key=config.period.week_key,
            day_ends_at=config.period.day_ends_at,
            week_ends_at=config.period.week_ends_at,
            terms_version=config.terms_version,
            limits=ConfigLimits(scans_per_day=config.scans_per_day),
            nickname=NicknameLimits(
                min_length=config.nickname_min_length,
                max_length=config.nickname_max_length,
            ),
            location_cities=[
                LocationCityResponse(id=c.id, name=c.name)
                for c in config.location_cities
            ],
            venues=[
                VenueResponse(
                    id=venue.id,
                    name=venue.name,
                    location_city=venue.city,
                    address=venue.address,
                )
                for venue in config.venues
            ],
        )


class PassportProgressResponse(BaseModel):
    campaign: str
    points: int
    updated_at: datetime

    @classmethod
    def from_domain(cls, progress: PassportProgress) -> "PassportProgressResponse":
        return cls(
            campaign=progress.campaign.value,
            points=progress.points,
            updated_at=progress.updated_at,
        )


class RedeemCodeRequest(BaseModel):
    """Raw user input or the code from the QR URL; the server normalizes it."""

    code: str = Field(min_length=1, max_length=64, examples=["TO-7KQ2-M9XH-4R6"])


class RedemptionResponse(BaseModel):
    city: str
    entries_added: int
    city_entries: int
    coins_awarded: int
    coin_balance: int
    replayed: bool
    bonus_awarded: int = 0
    flavor_unlocked: str | None = Field(
        default=None,
        description="Flavor (campaign slug) unlocked by this redemption, or null.",
    )

    @classmethod
    def from_result(cls, result: RedemptionResult) -> "RedemptionResponse":
        return cls(
            city=CAMPAIGN_BY_CITY[result.city].value,
            entries_added=result.entries_added,
            city_entries=result.city_entries,
            coins_awarded=result.coins_awarded,
            coin_balance=result.coin_balance,
            replayed=result.replayed,
            bonus_awarded=result.bonus_awarded,
            flavor_unlocked=(
                CAMPAIGN_BY_CITY[result.flavor_unlocked].value
                if result.flavor_unlocked is not None
                else None
            ),
        )


class LedgerEntryResponse(BaseModel):
    id: int
    amount: int
    reason: str
    created_at: datetime


class WalletResponse(BaseModel):
    balance: int
    lifetime_earned: int
    recent: list[LedgerEntryResponse]

    @classmethod
    def from_view(cls, view: WalletView) -> "WalletResponse":
        return cls(
            balance=view.balance,
            lifetime_earned=view.lifetime_earned,
            recent=[
                LedgerEntryResponse(
                    id=entry.id,
                    amount=entry.amount,
                    reason=entry.reason.value,
                    created_at=entry.created_at,
                )
                for entry in view.recent
            ],
        )


class AvatarResponse(BaseModel):
    id: str
    image_url: str
    locked: bool

    @classmethod
    def from_domain(cls, avatar: Avatar) -> "AvatarResponse":
        return cls(id=avatar.id, image_url=avatar.image_url, locked=avatar.locked)


class FlavorProgressResponse(BaseModel):
    flavor: str
    codes: int
    unlocked: bool

    @classmethod
    def from_domain(cls, progress: FlavorProgress) -> "FlavorProgressResponse":
        return cls(
            flavor=CAMPAIGN_BY_CITY[progress.flavor].value,
            codes=progress.codes,
            unlocked=progress.unlocked,
        )


class TeamStatusResponse(BaseModel):
    team: str | None = Field(
        description="Current flavor team (campaign slug), or null."
    )
    joined_at: datetime | None
    switch_allowed_at: datetime | None = Field(
        description="When the next team change is allowed; null before any join."
    )
    flavors: list[FlavorProgressResponse] = Field(
        description="Lifetime code count per flavor, for the 'N more to unlock' UI."
    )

    @classmethod
    def from_domain(cls, status: TeamStatus) -> "TeamStatusResponse":
        return cls(
            team=CAMPAIGN_BY_CITY[status.team.flavor].value if status.team else None,
            joined_at=status.team.joined_at if status.team else None,
            switch_allowed_at=status.switch_allowed_at,
            flavors=[FlavorProgressResponse.from_domain(f) for f in status.flavors],
        )


class TeamChangeRequest(BaseModel):
    flavor: str = Field(
        examples=["tokyo"], description="A campaign slug from GET /config flavors."
    )


class ChallengeResponse(BaseModel):
    id: str
    kind: str
    period: str
    target: int
    have: int
    reward_coins: int
    completed: bool
    claimed: bool
    streak: int | None = Field(
        default=None, description="DAILY_CHECKIN only; null for every other kind."
    )

    @classmethod
    def from_domain(cls, progress: ChallengeProgress) -> "ChallengeResponse":
        return cls(
            id=progress.id,
            kind=progress.kind.value,
            period=progress.period.value,
            target=progress.target,
            have=progress.have,
            reward_coins=progress.reward_coins,
            completed=progress.completed,
            claimed=progress.claimed,
            streak=progress.streak,
        )


class AchievementUnlockResponse(BaseModel):
    id: str
    reward_coins: int

    @classmethod
    def from_domain(cls, unlock: AchievementUnlock) -> "AchievementUnlockResponse":
        return cls(id=unlock.id, reward_coins=unlock.reward_coins)


class ChallengeClaimResponse(BaseModel):
    id: str
    coins_awarded: int
    coin_balance: int
    streak: int | None = None
    achievements_unlocked: list[AchievementUnlockResponse] = Field(
        default_factory=list,
        description=(
            "Achievements this claim just unlocked, auto-paid in the same "
            "transaction -- no separate claim needed."
        ),
    )

    @classmethod
    def from_result(cls, result: ChallengeClaimResult) -> "ChallengeClaimResponse":
        return cls(
            id=result.id,
            coins_awarded=result.coins_awarded,
            coin_balance=result.coin_balance,
            streak=result.streak,
            achievements_unlocked=[
                AchievementUnlockResponse.from_domain(u)
                for u in result.achievements_unlocked
            ],
        )


class UnlockedAchievementResponse(BaseModel):
    id: str
    threshold: int
    reward_coins: int
    unlocked_at: datetime

    @classmethod
    def from_domain(
        cls, achievement: UnlockedAchievement
    ) -> "UnlockedAchievementResponse":
        return cls(
            id=achievement.id,
            threshold=achievement.threshold,
            reward_coins=achievement.reward_coins,
            unlocked_at=achievement.unlocked_at,
        )
