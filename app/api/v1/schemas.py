from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.users import User


class AuthenticationRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)


class AuthenticationVerification(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class AuthenticationRequested(BaseModel):
    message: str


class UserResponse(BaseModel):
    id: UUID
    identifier: str
    display_name: str | None
    account_status: str
    verification_status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            identifier=user.identifier,
            display_name=user.display_name,
            account_status=user.account_status.value,
            verification_status=user.verification_status.value,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
