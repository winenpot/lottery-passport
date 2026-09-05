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


@dataclass(slots=True)
class User:
    id: UUID
    identifier: str
    display_name: str | None
    account_status: AccountStatus
    verification_status: VerificationStatus
    created_at: datetime
    updated_at: datetime
