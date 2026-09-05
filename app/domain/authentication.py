from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(slots=True)
class AuthenticationChallenge:
    id: UUID
    user_id: UUID
    code_hash: str
    code_salt: str
    expires_at: datetime
    attempts: int
    max_attempts: int
    consumed_at: datetime | None
    created_at: datetime


@dataclass(slots=True)
class AuthenticatedSession:
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
