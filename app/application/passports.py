from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.passports import Campaign, PassportProgress


class PassportRepository(Protocol):
    async def list_for_user(self, user_id: UUID) -> list[PassportProgress]: ...

    async def add_points(
        self, user_id: UUID, campaign: Campaign, amount: int, now: datetime
    ) -> PassportProgress: ...


class PassportService:
    def __init__(self, passports: PassportRepository) -> None:
        self._passports = passports

    async def list_for_user(self, user_id: UUID) -> list[PassportProgress]:
        return await self._passports.list_for_user(user_id)
