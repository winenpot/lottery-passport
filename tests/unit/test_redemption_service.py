from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.application.redemption_codes import (
    RedemptionError,
    RedemptionService,
    hash_redemption_code,
)
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.redemption_codes import RedemptionCode

PEPPER = "test-pepper"


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


class FakeRedemptionCodes:
    def __init__(self) -> None:
        self.items: dict[UUID, RedemptionCode] = {}

    async def bulk_insert(self, codes: list[RedemptionCode]) -> None:
        for code in codes:
            self.items[code.id] = code

    async def get_unredeemed_by_hash(self, code_hash: str) -> RedemptionCode | None:
        return next(
            (
                code
                for code in self.items.values()
                if code.code_hash == code_hash and code.redeemed_at is None
            ),
            None,
        )

    async def mark_redeemed(self, code_id: UUID, user_id: UUID, now: datetime) -> bool:
        code = self.items[code_id]
        if code.redeemed_at is not None:
            return False
        code.redeemed_at = now
        code.redeemed_by_user_id = user_id
        return True


class FakePassports:
    def __init__(self) -> None:
        self.items: dict[tuple[UUID, Campaign], PassportProgress] = {}

    async def list_for_user(self, user_id: UUID) -> list[PassportProgress]:
        return [
            progress for (owner, _), progress in self.items.items() if owner == user_id
        ]

    async def add_points(
        self, user_id: UUID, campaign: Campaign, amount: int, now: datetime
    ) -> PassportProgress:
        key = (user_id, campaign)
        existing = self.items.get(key)
        if existing is None:
            progress = PassportProgress(
                id=uuid4(),
                user_id=user_id,
                campaign=campaign,
                points=amount,
                created_at=now,
                updated_at=now,
            )
        else:
            progress = PassportProgress(
                id=existing.id,
                user_id=user_id,
                campaign=campaign,
                points=existing.points + amount,
                created_at=existing.created_at,
                updated_at=now,
            )
        self.items[key] = progress
        return progress


def build_service() -> tuple[RedemptionService, FakeRedemptionCodes, FakePassports]:
    codes = FakeRedemptionCodes()
    passports = FakePassports()
    service = RedemptionService(
        codes=codes,
        passports=passports,
        clock=FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        pepper=PEPPER,
    )
    return service, codes, passports


@pytest.mark.asyncio
async def test_redeem_credits_passport_and_consumes_code_once() -> None:
    service, codes, passports = build_service()
    raw_code = "PR0000001"
    await codes.bulk_insert(
        [
            RedemptionCode(
                id=uuid4(),
                city=CityCode.PARIS,
                code_hash=hash_redemption_code(raw_code, PEPPER),
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                redeemed_at=None,
                redeemed_by_user_id=None,
            )
        ]
    )
    user_id = uuid4()

    progress = await service.redeem(user_id, raw_code.lower())

    assert progress.campaign is Campaign.PARIS
    assert progress.points == 1
    assert (await passports.list_for_user(user_id))[0].points == 1

    with pytest.raises(RedemptionError):
        await service.redeem(user_id, raw_code)


@pytest.mark.asyncio
async def test_redeem_rejects_unknown_and_malformed_codes() -> None:
    service, _, _ = build_service()

    with pytest.raises(RedemptionError):
        await service.redeem(uuid4(), "not-a-code")

    with pytest.raises(RedemptionError):
        await service.redeem(uuid4(), "PR0000001")


@pytest.mark.asyncio
async def test_redeem_without_configured_pepper_fails_closed() -> None:
    service = RedemptionService(
        codes=FakeRedemptionCodes(),
        passports=FakePassports(),
        clock=FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        pepper=None,
    )

    with pytest.raises(RedemptionError):
        await service.redeem(uuid4(), "PR0000001")
