from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class AccountStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class UserRole(StrEnum):
    """Two roles today: a player, or staff operating admin tooling.

    No per-role permission sets yet -- add a third role only when one is
    actually needed (CLAUDE.md: don't build ahead of a real caller).
    """

    PLAYER = "player"
    ADMIN = "admin"


@dataclass(slots=True)
class User:
    id: UUID
    identifier: str
    display_name: str | None
    account_status: AccountStatus
    verification_status: VerificationStatus
    role: UserRole
    created_at: datetime
    updated_at: datetime
    nickname: str | None = None
    terms_version: str | None = None
    terms_accepted_at: datetime | None = None
    home_venue_id: str | None = None
    location_city: str | None = None
    avatar_id: str | None = None

    @property
    def profile_complete(self) -> bool:
        return self.nickname is not None and self.terms_accepted_at is not None
