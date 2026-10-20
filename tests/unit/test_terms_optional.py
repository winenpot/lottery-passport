"""TERMS_REQUIRED=false: sign-up and scanning without accepted terms (FX4).

Test environments run without legal text for now; the frontend hides the
terms step and never sends a fake acceptance. Production must refuse it.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import (
    get_current_user,
    get_me_service,
    get_redemption_service,
    get_referral_service,
)
from app.app import create_app
from app.application.me import MeExtras
from app.application.redemption_codes import RedemptionResult
from app.core.config import Settings
from app.domain.passports import CityCode
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus

NOW = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
DB = "postgresql+asyncpg://app:secret@postgres:5432/db"


def make_user(*, nickname: str | None, terms: bool) -> User:
    return User(
        id=uuid4(),
        identifier="+989690000001",
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=UserRole.PLAYER,
        created_at=NOW,
        updated_at=NOW,
        nickname=nickname,
        terms_version="2026-10-01" if terms else None,
        terms_accepted_at=NOW if terms else None,
    )


# --- domain ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("nickname", "terms", "required", "complete"),
    [
        ("NightOwl", True, True, True),
        ("NightOwl", False, True, False),
        ("NightOwl", False, False, True),
        (None, True, False, False),
        (None, False, False, False),
    ],
)
def test_profile_completion_rule(
    nickname: str | None, terms: bool, required: bool, complete: bool
) -> None:
    user = make_user(nickname=nickname, terms=terms)

    assert user.is_profile_complete(terms_required=required) is complete


def test_the_plain_property_keeps_the_strict_rule() -> None:
    assert make_user(nickname="NightOwl", terms=False).profile_complete is False


# --- settings -------------------------------------------------------------


def test_production_refuses_optional_terms() -> None:
    with pytest.raises(ValidationError, match="TERMS_REQUIRED"):
        Settings(
            environment="production",
            database_url=DB,
            redemption_code_pepper="p" * 48,
            admin_session_secret="a" * 48,
            terms_required=False,
        )


def test_staging_may_switch_terms_off() -> None:
    settings = Settings(
        environment="staging",
        database_url=DB,
        redemption_code_pepper="p" * 48,
        admin_session_secret="a" * 48,
        terms_required=False,
    )

    assert settings.terms_required is False


def test_terms_are_required_by_default() -> None:
    assert Settings(_env_file=None).terms_required is True  # type: ignore[call-arg]


# --- HTTP -----------------------------------------------------------------


class FakeRedemptions:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str]] = []

    async def redeem(self, user_id: UUID, code: str) -> RedemptionResult:
        self.calls.append((user_id, code))
        return RedemptionResult(
            city=CityCode.TOKYO,
            entries_added=1,
            city_entries=1,
            coins_awarded=100,
            coin_balance=100,
            replayed=False,
        )


class FakeMeService:
    async def extras(self, user_id: UUID) -> MeExtras:
        return MeExtras(team=None, last_scanned_flavor=None)


class FakeReferralService:
    async def settle(self, user_id: UUID) -> None:
        return None

    async def ensure_code(self, user_id: UUID) -> str:
        return "REFCODE1"


def client(user: User, *, terms_required: bool) -> tuple[TestClient, FakeRedemptions]:
    fake = FakeRedemptions()
    application = create_app(Settings(database_url=DB, terms_required=terms_required))
    application.dependency_overrides[get_current_user] = lambda: user
    application.dependency_overrides[get_redemption_service] = lambda: fake
    application.dependency_overrides[get_me_service] = lambda: FakeMeService()
    application.dependency_overrides[get_referral_service] = lambda: (
        FakeReferralService()
    )
    return TestClient(application, headers={"X-Requested-With": "test"}), fake


def test_scan_works_without_terms_when_they_are_optional() -> None:
    user = make_user(nickname="NightOwl", terms=False)
    http, fake = client(user, terms_required=False)

    response = http.post("/api/v1/redemptions", json={"code": "x"})

    assert response.status_code == 200
    assert fake.calls == [(user.id, "x")]


def test_optional_terms_still_need_a_nickname_to_scan() -> None:
    http, fake = client(make_user(nickname=None, terms=False), terms_required=False)

    response = http.post("/api/v1/redemptions", json={"code": "x"})

    assert response.json()["error"]["code"] == "PROFILE_INCOMPLETE"
    assert fake.calls == []


def test_required_terms_still_block_the_scan() -> None:
    http, fake = client(
        make_user(nickname="NightOwl", terms=False), terms_required=True
    )

    response = http.post("/api/v1/redemptions", json={"code": "x"})

    assert response.json()["error"]["code"] == "TERMS_NOT_ACCEPTED"
    assert fake.calls == []


def test_me_reports_complete_but_never_pretends_terms_were_accepted() -> None:
    http, _ = client(make_user(nickname="NightOwl", terms=False), terms_required=False)

    body = http.get("/api/v1/me").json()

    assert body["profile_complete"] is True
    assert body["terms_accepted"] is False
