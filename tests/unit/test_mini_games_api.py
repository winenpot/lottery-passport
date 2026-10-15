"""``POST /mini-games/{mini_game_id}/runs``, ``POST /mini-games/runs/{run_id}/finish``:
route wiring and error mapping (G1.4). ``MiniGameService`` itself is
exercised against fakes in tests/unit/test_mini_game_service.py and
against real Postgres in tests/integration/test_mini_games_uow_db.py.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_mini_game_service
from app.app import create_app
from app.application.mini_games import (
    MiniGameFinishResult,
    MiniGameRunError,
    MiniGameRunRefusal,
    MiniGameStartError,
    MiniGameStartRefusal,
    RunStarted,
)
from app.core.config import Settings
from app.domain.mini_games import MiniGameId, MiniGameRunRejection
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


class FakeMiniGameService:
    def __init__(self) -> None:
        self.start_result: RunStarted | None = None
        self.start_error: MiniGameStartError | None = None
        self.finish_result: MiniGameFinishResult | None = None
        self.finish_error: MiniGameRunError | None = None

    async def start_run(self, user_id: UUID, mini_game_id: MiniGameId) -> RunStarted:
        if self.start_error is not None:
            raise self.start_error
        assert self.start_result is not None
        return self.start_result

    async def finish_run(
        self, user_id: UUID, run_id: UUID, reactions_ms: list[int]
    ) -> MiniGameFinishResult:
        if self.finish_error is not None:
            raise self.finish_error
        assert self.finish_result is not None
        return self.finish_result


def client(service: FakeMiniGameService) -> TestClient:
    app = create_app(
        Settings(database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x")
    )
    app.dependency_overrides[get_current_user] = lambda: make_user()
    app.dependency_overrides[get_mini_game_service] = lambda: service
    return TestClient(app)


def test_starting_a_run_returns_the_round_delays() -> None:
    service = FakeMiniGameService()
    run_id = uuid4()
    service.start_result = RunStarted(
        run_id=run_id,
        mini_game_id=MiniGameId.TAP_REFLEX,
        round_delays_ms=[1000, 1500, 2000],
        expires_at=NOW + timedelta(minutes=2),
    )

    response = client(service).post("/api/v1/mini-games/tap_reflex/runs")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == str(run_id)
    assert body["mini_game_id"] == "tap_reflex"
    assert body["round_delays_ms"] == [1000, 1500, 2000]


def test_starting_a_run_while_one_is_open_is_409() -> None:
    service = FakeMiniGameService()
    service.start_error = MiniGameStartError(MiniGameStartRefusal.ALREADY_OPEN)

    response = client(service).post("/api/v1/mini-games/tap_reflex/runs")

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "MINI_GAME_RUN_ALREADY_OPEN",
    )


def test_an_unknown_mini_game_id_is_422() -> None:
    response = client(FakeMiniGameService()).post("/api/v1/mini-games/spin/runs")

    assert response.status_code == 422


def test_finishing_a_run_returns_the_acceptance_verdict() -> None:
    service = FakeMiniGameService()
    run_id = uuid4()
    service.finish_result = MiniGameFinishResult(
        run_id=run_id, accepted=True, average_reaction_ms=250.0
    )

    response = client(service).post(
        f"/api/v1/mini-games/runs/{run_id}/finish",
        json={"reactions_ms": [250, 260, 240]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": str(run_id),
        "accepted": True,
        "average_reaction_ms": 250.0,
        "reason": None,
    }


def test_a_rejected_finish_is_still_200() -> None:
    service = FakeMiniGameService()
    run_id = uuid4()
    service.finish_result = MiniGameFinishResult(
        run_id=run_id,
        accepted=False,
        average_reaction_ms=250.0,
        reason=MiniGameRunRejection.IDENTICAL_REACTIONS,
    )

    response = client(service).post(
        f"/api/v1/mini-games/runs/{run_id}/finish",
        json={"reactions_ms": [250, 250, 250]},
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["accepted"], body["reason"]) == (False, "identical_reactions")


def test_finishing_an_unknown_run_is_404() -> None:
    service = FakeMiniGameService()
    service.finish_error = MiniGameRunError(MiniGameRunRefusal.NOT_FOUND)

    response = client(service).post(
        f"/api/v1/mini-games/runs/{uuid4()}/finish",
        json={"reactions_ms": [250, 250, 250]},
    )

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "NOT_FOUND",
    )


def test_finishing_someone_elses_run_is_also_404_not_403() -> None:
    service = FakeMiniGameService()
    service.finish_error = MiniGameRunError(MiniGameRunRefusal.NOT_OWNER)

    response = client(service).post(
        f"/api/v1/mini-games/runs/{uuid4()}/finish",
        json={"reactions_ms": [250, 250, 250]},
    )

    assert (response.status_code, response.json()["error"]["code"]) == (
        404,
        "NOT_FOUND",
    )


def test_finishing_an_expired_run_is_409() -> None:
    service = FakeMiniGameService()
    service.finish_error = MiniGameRunError(MiniGameRunRefusal.EXPIRED)

    response = client(service).post(
        f"/api/v1/mini-games/runs/{uuid4()}/finish",
        json={"reactions_ms": [250, 250, 250]},
    )

    assert (response.status_code, response.json()["error"]["code"]) == (
        409,
        "MINI_GAME_RUN_EXPIRED",
    )


def test_a_round_count_mismatch_is_422() -> None:
    service = FakeMiniGameService()
    service.finish_error = MiniGameRunError(MiniGameRunRefusal.ROUND_COUNT_MISMATCH)

    response = client(service).post(
        f"/api/v1/mini-games/runs/{uuid4()}/finish",
        json={"reactions_ms": [250]},
    )

    assert (response.status_code, response.json()["error"]["code"]) == (
        422,
        "MINI_GAME_ROUND_COUNT_MISMATCH",
    )
