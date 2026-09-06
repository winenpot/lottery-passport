import hashlib
import hmac
import re
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.authentication import Clock
from app.application.passports import PassportRepository
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.redemption_codes import RedemptionCode

CODE_PATTERN = re.compile(r"^[A-Z]{2}\d{7}$")

_CITY_TO_CAMPAIGN: dict[CityCode, Campaign] = {
    CityCode.PARIS: Campaign.PARIS,
    CityCode.BERLIN: Campaign.BERLIN,
    CityCode.PATTAYA: Campaign.PATTAYA,
    CityCode.MEXICO: Campaign.MEXICO,
    CityCode.MADRID: Campaign.MADRID,
    CityCode.TOKYO: Campaign.TOKYO,
    CityCode.MOSCOW: Campaign.MOSCOW,
}

POINTS_PER_REDEMPTION = 1


class RedemptionError(Exception):
    """Raised for any invalid, unknown, or already-used redemption code."""


class RedemptionCodeRepository(Protocol):
    async def bulk_insert(self, codes: list[RedemptionCode]) -> None: ...

    async def get_unredeemed_by_hash(self, code_hash: str) -> RedemptionCode | None: ...

    async def mark_redeemed(
        self, code_id: UUID, user_id: UUID, now: datetime
    ) -> bool: ...


def hash_redemption_code(code: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode("utf-8"), code.encode("utf-8"), hashlib.sha256
    ).hexdigest()


class RedemptionService:
    def __init__(
        self,
        codes: RedemptionCodeRepository,
        passports: PassportRepository,
        clock: Clock,
        pepper: str | None,
    ) -> None:
        self._codes = codes
        self._passports = passports
        self._clock = clock
        self._pepper = pepper

    async def redeem(self, user_id: UUID, raw_code: str) -> PassportProgress:
        if self._pepper is None:
            raise RedemptionError("redemption is not configured")

        code = raw_code.strip().upper()
        if not CODE_PATTERN.match(code):
            raise RedemptionError("invalid redemption code")

        code_hash = hash_redemption_code(code, self._pepper)
        record = await self._codes.get_unredeemed_by_hash(code_hash)
        if record is None:
            raise RedemptionError("invalid redemption code")

        now = self._clock.now()
        marked = await self._codes.mark_redeemed(record.id, user_id, now)
        if not marked:
            raise RedemptionError("redemption code already used")

        campaign = _CITY_TO_CAMPAIGN[record.city]
        return await self._passports.add_points(
            user_id, campaign, POINTS_PER_REDEMPTION, now
        )
