"""``GET /challenges``, ``POST /challenges/{id}/claim``: route wiring and
error mapping (C1). ``ChallengeService`` itself is exercised against
fakes in tests/unit/test_challenge_service.py and against real Postgres
in tests/integration/test_challenges_db.py."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.deps import get_challenge_service, get_current_user
from app.app import create_app
from app.application.challenges import (
    AchievementUnlock,
    ChallengeClaimResult,
    ChallengeProgress,
)
from app.core.config import Settings
from app.domain.challenges import (
    ChallengeClaimError,
    ChallengeClaimRefusal,
    ChallengeKind,
    ChallengePeriod,
)
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
USER_ID = UUID(int=1)


def make_user() -> User:
    return User(
        id=USER_ID,
        identifier="+989****0001",
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=UserRole.PLAYER,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeChallengeService:
    def __init__(self) -> None:
        self.progress = [
            ChallengeProgress(
                id="choose_team",
                kind=ChallengeKind.TEAM_CHOICE,
                period=ChallengePeriod.ONCE,
                target=1,
                have=0,
                reward_coins=30,
                completed=False,
                claimed=False,
            )
        ]
        self.claim_error: ChallengeClaimError | None = None
        self.claim_result: ChallengeClaimResult | None = None

    async def list(self, user_id: UUID) -> list[ChallengeProgress]:
        return self.progress

    async def claim(self, user_id: UUID, challenge_id: str) -> ChallengeClaimResult:
        if self.claim_error is not None:
            raise self.claim_error
        assert self.claim_result is not None
        return self.claim_result


def client(service: FakeChallengeService) -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_challenge_service] = lambda: service
    return TestClient(app)


def test_list_challenges_returns_progress() -> None:
    response = client(FakeChallengeService()).get("/api/v1/challenges")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "choose_team"
    assert body[0]["completed"] is False


def test_claiming_a_completed_challenge() -> None:
    service = FakeChallengeService()
    service.claim_result = ChallengeClaimResult(
        id="choose_team", coins_awarded=30, coin_balance=30
    )

    response = client(service).post("/api/v1/challenges/choose_team/claim")

    assert response.status_code == 200
    assert response.json() == {
        "id": "choose_team",
        "coins_awarded": 30,
        "coin_balance": 30,
        "streak": None,
        "achievements_unlocked": [],
    }


def test_claiming_an_unknown_challenge_is_404() -> None:
    service = FakeChallengeService()
    service.claim_error = ChallengeClaimError(ChallengeClaimRefusal.UNKNOWN)

    response = client(service).post("/api/v1/challenges/nope/claim")

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "NOT_FOUND",
    )


def test_claiming_twice_is_409_already_claimed() -> None:
    service = FakeChallengeService()
    service.claim_error = ChallengeClaimError(ChallengeClaimRefusal.ALREADY_CLAIMED)

    response = client(service).post("/api/v1/challenges/choose_team/claim")

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "CHALLENGE_ALREADY_CLAIMED",
    )


def test_claiming_before_completion_carries_required_and_have() -> None:
    service = FakeChallengeService()
    service.claim_error = ChallengeClaimError(
        ChallengeClaimRefusal.NOT_UNLOCKED, required=3, have=1
    )

    response = client(service).post("/api/v1/challenges/discover_3_flavors/claim")

    body = response.json()
    assert (response.status_code, body["error"]["code"]) == (
        409,
        "CHALLENGE_NOT_UNLOCKED",
    )
    assert body["error"]["details"] == {"required": 3, "have": 1}


def test_claiming_a_daily_checkin_surfaces_streak_and_unlocked_achievements() -> None:
    service = FakeChallengeService()
    service.claim_result = ChallengeClaimResult(
        id="daily_checkin",
        coins_awarded=10,
        coin_balance=30,
        streak=3,
        achievements_unlocked=[AchievementUnlock(id="streak_3", reward_coins=20)],
    )

    response = client(service).post("/api/v1/challenges/daily_checkin/claim")

    assert response.status_code == 200
    assert response.json() == {
        "id": "daily_checkin",
        "coins_awarded": 10,
        "coin_balance": 30,
        "streak": 3,
        "achievements_unlocked": [{"id": "streak_3", "reward_coins": 20}],
    }


def test_list_surfaces_the_streak_field_on_the_daily_checkin_card() -> None:
    service = FakeChallengeService()
    service.progress = [
        ChallengeProgress(
            id="daily_checkin",
            kind=ChallengeKind.DAILY_CHECKIN,
            period=ChallengePeriod.DAY,
            target=1,
            have=1,
            reward_coins=10,
            completed=True,
            claimed=False,
            streak=4,
        )
    ]

    response = client(service).get("/api/v1/challenges")

    assert response.status_code == 200
    assert response.json()[0]["streak"] == 4
