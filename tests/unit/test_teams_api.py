"""`GET/POST /api/v1/me/team`: route wiring and error mapping (P1.5).

``TeamService`` itself is exercised against fakes in
``tests/unit/test_team_service.py`` and against real PostgreSQL in
``tests/integration/test_team_service_db.py``; this file only proves the
route maps ``TeamChangeError`` to the documented HTTP status/code/details.
"""

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_team_service
from app.app import create_app
from app.application.teams import FlavorProgress, TeamStatus
from app.core.config import Settings
from app.domain.passports import CityCode
from app.domain.teams import TeamChangeError, TeamChangeRefusal, TeamMembership
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


class FakeTeamService:
    def __init__(self) -> None:
        self.status_value = TeamStatus(
            team=None,
            switch_allowed_at=None,
            flavors=[FlavorProgress(flavor, 0, False) for flavor in CityCode],
        )
        self.change_error: TeamChangeError | None = None
        self.change_result: TeamMembership | None = None

    async def status(self, user_id: UUID) -> TeamStatus:
        return self.status_value

    async def change(self, user_id: UUID, flavor: CityCode) -> TeamMembership:
        if self.change_error is not None:
            raise self.change_error
        assert self.change_result is not None
        return self.change_result


def client(service: FakeTeamService) -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_team_service] = lambda: service
    return TestClient(app)


def test_get_my_team_before_any_join() -> None:
    response = client(FakeTeamService()).get("/api/v1/me/team")

    assert response.status_code == 200
    body = response.json()
    assert (body["team"], body["switch_allowed_at"]) == (None, None)
    assert len(body["flavors"]) == 7


def test_joining_an_unlocked_flavor() -> None:
    service = FakeTeamService()
    service.change_result = TeamMembership(USER_ID, CityCode.TOKYO, 0, NOW)
    service.status_value = TeamStatus(
        team=service.change_result,
        switch_allowed_at=NOW,
        flavors=service.status_value.flavors,
    )

    response = client(service).post("/api/v1/me/team", json={"flavor": "tokyo"})

    assert response.status_code == 200
    assert response.json()["team"] == "tokyo"


def test_an_unknown_flavor_slug_is_422() -> None:
    response = client(FakeTeamService()).post(
        "/api/v1/me/team", json={"flavor": "not-a-flavor"}
    )

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "CATALOGUE_UNKNOWN",
    )


def test_flavor_not_unlocked_carries_required_and_have() -> None:
    service = FakeTeamService()
    service.change_error = TeamChangeError(
        TeamChangeRefusal.FLAVOR_NOT_UNLOCKED, required=5, have=2
    )

    response = client(service).post("/api/v1/me/team", json={"flavor": "moscow"})

    body = response.json()
    assert (response.status_code, body["error"]["code"]) == (409, "FLAVOR_NOT_UNLOCKED")
    assert body["error"]["details"] == {"required": 5, "have": 2}


def test_team_locked_carries_switch_allowed_at() -> None:
    service = FakeTeamService()
    service.change_error = TeamChangeError(
        TeamChangeRefusal.TEAM_LOCKED, allowed_at=NOW
    )

    response = client(service).post("/api/v1/me/team", json={"flavor": "moscow"})

    body = response.json()
    assert (response.status_code, body["error"]["code"]) == (409, "TEAM_LOCKED")
    assert body["error"]["details"] == {"switch_allowed_at": NOW.isoformat()}


def test_switching_to_the_same_team_is_422() -> None:
    service = FakeTeamService()
    service.change_error = TeamChangeError(TeamChangeRefusal.SAME_TEAM)

    response = client(service).post("/api/v1/me/team", json={"flavor": "tokyo"})

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "TEAM_SAME",
    )
