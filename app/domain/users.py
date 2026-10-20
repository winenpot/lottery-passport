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
    referral_code: str | None = None

    @property
    def profile_complete(self) -> bool:
        """Strict rule (production): nickname set AND current terms accepted."""
        return self.is_profile_complete(terms_required=True)

    def is_profile_complete(self, *, terms_required: bool) -> bool:
        """Finished sign-up. Outside production terms can be switched off
        (``TERMS_REQUIRED=false``) until the legal text exists; acceptance is
        then simply not needed, never assumed (``terms_accepted_at`` stays
        whatever the player really did)."""
        if self.nickname is None:
            return False
        return not terms_required or self.terms_accepted_at is not None
