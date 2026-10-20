"""MiniGameService (G1.4): start/finish plumbing against fakes.

The plausibility check itself (assess_plausibility, check_can_finish) is
tested in isolation in tests/unit/test_mini_games_domain.py; this file
checks that the service wires the unit of work correctly: one open run
per user, the wallet lock, and the rejected-run audit flag threshold.
"""

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.application.mini_games import MiniGameService
from app.domain.audit import NewAuditEntry
from app.domain.mini_games import (
    RUN_TTL,
    MiniGameId,
    MiniGameRun,
    MiniGameRunError,
    MiniGameRunRefusal,
    MiniGameRunRejection,
    MiniGameRunStatus,
)

ZONE = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


@dataclass
class Store:
    wallets: dict[UUID, int] = field(default_factory=dict)
    runs: dict[UUID, MiniGameRun] = field(default_factory=dict)
    audit_entries: list[NewAuditEntry] = field(default_factory=list)


class FakeLedger:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def lock_wallet(self, user_id: UUID, now: datetime) -> int:
        return self.store.wallets.setdefault(user_id, 0)


class FakeMiniGames:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def open(self, run: object) -> None:
        # `run` is a NewMiniGameRun; store it already "open".
        self.store.runs[run.id] = MiniGameRun(  # type: ignore[attr-defined]
            id=run.id,  # type: ignore[attr-defined]
            user_id=run.user_id,  # type: ignore[attr-defined]
            mini_game_id=run.mini_game_id,  # type: ignore[attr-defined]
            round_delays_ms=run.round_delays_ms,  # type: ignore[attr-defined]
            issued_at=run.issued_at,  # type: ignore[attr-defined]
            expires_at=run.expires_at,  # type: ignore[attr-defined]
            status=MiniGameRunStatus.OPEN,
        )

    async def get_open(
        self, user_id: UUID, mini_game_id: MiniGameId
    ) -> MiniGameRun | None:
        for run in self.store.runs.values():
            if (
                run.user_id == user_id
                and run.mini_game_id == mini_game_id
                and run.status is MiniGameRunStatus.OPEN
            ):
                return run
        return None

    async def get(self, run_id: UUID) -> MiniGameRun | None:
        return self.store.runs.get(run_id)

    async def finish(
        self,
        run_id: UUID,
        status: MiniGameRunStatus,
        finished_at: datetime,
        average_reaction_ms: float | None,
    ) -> None:
        run = self.store.runs[run_id]
        self.store.runs[run_id] = MiniGameRun(
            id=run.id,
            user_id=run.user_id,
            mini_game_id=run.mini_game_id,
            round_delays_ms=run.round_delays_ms,
            issued_at=run.issued_at,
            expires_at=run.expires_at,
            status=status,
        )

    async def count_rejected_since(self, user_id: UUID, since: datetime) -> int:
        return sum(
            1
            for run in self.store.runs.values()
            if run.user_id == user_id and run.status is MiniGameRunStatus.REJECTED
        )


class FakeAudit:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def record(self, entry: NewAuditEntry) -> None:
        self.store.audit_entries.append(entry)


class FakeUnitOfWork:
    def __init__(self, committed: Store) -> None:
        self._committed = committed
        self.working = Store()

    @property
    def ledger(self) -> FakeLedger:
        return FakeLedger(self.working)

    @property
    def mini_games(self) -> FakeMiniGames:
        return FakeMiniGames(self.working)

    @property
    def audit(self) -> FakeAudit:
        return FakeAudit(self.working)

    async def __aenter__(self) -> Self:
        self.working = copy.deepcopy(self._committed)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self._committed.__dict__.update(copy.deepcopy(self.working).__dict__)


@dataclass
class FakeClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


def build(
    store: Store | None = None,
    now: datetime | None = None,
    rejected_review_threshold: int = 3,
) -> tuple[MiniGameService, Store, FakeClock]:
    store = store if store is not None else Store()
    clock = FakeClock(now or NOW)
    service = MiniGameService(
        unit_of_work=lambda: FakeUnitOfWork(store),
        clock=clock,
        zone=ZONE,
        rejected_review_threshold=rejected_review_threshold,
    )
    return service, store, clock


async def test_starting_a_run_locks_the_wallet_and_stores_it_open() -> None:
    user = uuid4()
    service, store, _ = build()

    started = await service.start_run(user, MiniGameId.TAP_REFLEX)

    assert started.mini_game_id is MiniGameId.TAP_REFLEX
    assert started.expires_at == NOW + RUN_TTL
    assert len(started.round_delays_ms) == 5
    assert user in store.wallets
    assert store.runs[started.run_id].status is MiniGameRunStatus.OPEN


async def test_starting_again_closes_the_open_run_as_expired() -> None:
    user = uuid4()
    service, store, _ = build()
    first = await service.start_run(user, MiniGameId.TAP_REFLEX)

    second = await service.start_run(user, MiniGameId.TAP_REFLEX)

    assert second.run_id != first.run_id
    assert store.runs[first.run_id].status is MiniGameRunStatus.EXPIRED
    assert store.runs[second.run_id].status is MiniGameRunStatus.OPEN


async def test_an_abandoned_run_never_locks_the_player_out() -> None:
    # N17: a run left open past its TTL used to answer 409 forever.
    user = uuid4()
    service, store, clock = build()
    abandoned = await service.start_run(user, MiniGameId.TAP_REFLEX)
    clock.current = abandoned.expires_at + timedelta(minutes=30)

    fresh = await service.start_run(user, MiniGameId.TAP_REFLEX)

    assert store.runs[abandoned.run_id].status is MiniGameRunStatus.EXPIRED
    assert fresh.expires_at == clock.current + RUN_TTL


async def test_finishing_a_replaced_run_is_refused_as_expired() -> None:
    user = uuid4()
    service, store, _ = build()
    replaced = await service.start_run(user, MiniGameId.TAP_REFLEX)
    await service.start_run(user, MiniGameId.TAP_REFLEX)

    with pytest.raises(MiniGameRunError) as caught:
        await service.finish_run(user, replaced.run_id, [250, 260, 270, 280, 290])
    assert caught.value.reason is MiniGameRunRefusal.EXPIRED
    assert store.runs[replaced.run_id].status is MiniGameRunStatus.EXPIRED


async def test_finishing_after_the_ttl_records_the_run_as_expired() -> None:
    user = uuid4()
    service, store, clock = build()
    started = await service.start_run(user, MiniGameId.TAP_REFLEX)
    clock.current = started.expires_at + timedelta(seconds=1)

    with pytest.raises(MiniGameRunError) as caught:
        await service.finish_run(user, started.run_id, [250, 260, 270, 280, 290])
    assert caught.value.reason is MiniGameRunRefusal.EXPIRED
    assert store.runs[started.run_id].status is MiniGameRunStatus.EXPIRED


async def test_finishing_an_unknown_run_is_refused() -> None:
    service, _, _ = build()

    with pytest.raises(MiniGameRunError) as caught:
        await service.finish_run(uuid4(), uuid4(), [250, 300, 275])
    assert caught.value.reason is MiniGameRunRefusal.NOT_FOUND


async def test_a_plausible_finish_is_accepted() -> None:
    user = uuid4()
    service, store, clock = build()
    started = await service.start_run(user, MiniGameId.TAP_REFLEX)
    reactions = [250] * len(started.round_delays_ms)
    reactions[0] += 1  # not all identical
    clock.current = NOW + timedelta(
        milliseconds=sum(started.round_delays_ms) + sum(reactions) + 50
    )

    result = await service.finish_run(user, started.run_id, reactions)

    assert result.accepted is True
    assert result.reason is None
    assert store.runs[started.run_id].status is MiniGameRunStatus.ACCEPTED


async def test_an_implausible_finish_is_rejected_not_an_error() -> None:
    user = uuid4()
    service, store, clock = build()
    started = await service.start_run(user, MiniGameId.TAP_REFLEX)
    reactions = [250] * len(started.round_delays_ms)  # all identical -> rejected
    clock.current = NOW + timedelta(
        milliseconds=sum(started.round_delays_ms) + sum(reactions) + 50
    )

    result = await service.finish_run(user, started.run_id, reactions)

    assert result.accepted is False
    assert result.reason is MiniGameRunRejection.IDENTICAL_REACTIONS
    assert store.runs[started.run_id].status is MiniGameRunStatus.REJECTED


async def test_crossing_the_rejected_threshold_writes_one_audit_entry() -> None:
    user = uuid4()
    service, store, clock = build(rejected_review_threshold=2)

    async def run_and_reject() -> None:
        started = await service.start_run(user, MiniGameId.TAP_REFLEX)
        reactions = [111] * len(started.round_delays_ms)  # identical -> rejected
        clock.current = started.expires_at - timedelta(seconds=1)
        await service.finish_run(user, started.run_id, reactions)

    await run_and_reject()
    assert store.audit_entries == []  # 1st rejection, below the threshold

    await run_and_reject()
    assert len(store.audit_entries) == 1  # 2nd rejection crosses it
    entry = store.audit_entries[0]
    assert entry.entity == "mini_game_run_abuse"
    assert entry.actor_user_id == user
    assert entry.changes == {"mini_game_id": "tap_reflex", "rejected_today": 2}

    await run_and_reject()
    assert len(store.audit_entries) == 2  # still >= threshold, flagged again
