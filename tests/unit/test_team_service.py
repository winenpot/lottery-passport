"""TeamService: GET/POST /me/team plumbing (P1.5), against fakes.

The actual join/switch/lock rule is tested in isolation in
``tests/unit/test_teams.py`` (``app/domain/teams.py``); here we check that
the service wires the reader and the unit of work correctly: ``status()``
aggregates all 7 flavors, ``change()`` locks the wallet first and commits
only on success, same per-user serialization as redemption.
"""

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

import pytest

from app.application.teams import TeamService
from app.domain.passports import CityCode
from app.domain.teams import (
    TEAM_LOCK,
    TeamChangeError,
    TeamChangeRefusal,
    TeamMembership,
)


@dataclass
class Store:
    wallets: dict[UUID, int] = field(default_factory=dict)
    flavor_codes: dict[tuple[UUID, CityCode], int] = field(default_factory=dict)
    memberships: list[TeamMembership] = field(default_factory=list)


def _current(store: Store, user_id: UUID) -> TeamMembership | None:
    mine = [m for m in store.memberships if m.user_id == user_id]
    return max(mine, key=lambda m: m.switch_no) if mine else None


class FakeReader:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current(self, user_id: UUID) -> TeamMembership | None:
        return _current(self.store, user_id)

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        return self.store.flavor_codes.get((user_id, flavor), 0)


class FakeLedger:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def lock_wallet(self, user_id: UUID, now: datetime) -> int:
        return self.store.wallets.setdefault(user_id, 0)


class FakeTeams:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current(self, user_id: UUID) -> TeamMembership | None:
        return _current(self.store, user_id)

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        return self.store.flavor_codes.get((user_id, flavor), 0)

    async def add(self, membership: TeamMembership) -> None:
        self.store.memberships.append(membership)


class FakeUnitOfWork:
    def __init__(self, committed: Store) -> None:
        self._committed = committed
        self.working = Store()

    @property
    def ledger(self) -> FakeLedger:
        return FakeLedger(self.working)

    @property
    def teams(self) -> FakeTeams:
        return FakeTeams(self.working)

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
    store: Store | None = None, now: datetime | None = None
) -> tuple[TeamService, Store, FakeClock]:
    store = store if store is not None else Store()
    clock = FakeClock(now or datetime(2026, 10, 15, 9, 0, tzinfo=UTC))
    service = TeamService(
        reader=FakeReader(store),
        unit_of_work=lambda: FakeUnitOfWork(store),
        clock=clock,
    )
    return service, store, clock


async def test_status_lists_all_seven_flavors_with_lifetime_counts() -> None:
    user = uuid4()
    store = Store(flavor_codes={(user, CityCode.TOKYO): 7, (user, CityCode.MOSCOW): 3})
    service, _, _ = build(store)

    status = await service.status(user)

    assert status.team is None
    assert status.switch_allowed_at is None
    by_flavor = {p.flavor: p for p in status.flavors}
    assert len(by_flavor) == 7
    tokyo, moscow = by_flavor[CityCode.TOKYO], by_flavor[CityCode.MOSCOW]
    assert (tokyo.codes, tokyo.unlocked) == (7, True)
    assert (moscow.codes, moscow.unlocked) == (3, False)
    assert by_flavor[CityCode.PARIS].codes == 0


async def test_first_join_needs_five_codes_and_locks_the_wallet() -> None:
    user = uuid4()
    store = Store(flavor_codes={(user, CityCode.TOKYO): 5})
    service, store, _ = build(store)

    membership = await service.change(user, CityCode.TOKYO)

    assert (membership.flavor, membership.switch_no) == (CityCode.TOKYO, 0)
    assert store.memberships == [membership]
    assert user in store.wallets  # lock_wallet created the row


async def test_a_refused_change_commits_nothing() -> None:
    user = uuid4()
    store = Store(flavor_codes={(user, CityCode.TOKYO): 4})
    service, store, _ = build(store)

    with pytest.raises(TeamChangeError) as caught:
        await service.change(user, CityCode.TOKYO)

    assert caught.value.reason is TeamChangeRefusal.FLAVOR_NOT_UNLOCKED
    assert store.memberships == []


async def test_switching_before_the_lock_expires_is_refused() -> None:
    user = uuid4()
    joined_at = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    store = Store(
        memberships=[TeamMembership(user, CityCode.TOKYO, 0, joined_at)],
        flavor_codes={(user, CityCode.MOSCOW): 10},
    )
    service, store, _ = build(store, now=joined_at + TEAM_LOCK - timedelta(seconds=1))

    with pytest.raises(TeamChangeError) as caught:
        await service.change(user, CityCode.MOSCOW)

    assert caught.value.reason is TeamChangeRefusal.TEAM_LOCKED
    assert len(store.memberships) == 1


async def test_switching_after_the_lock_succeeds_and_status_reflects_it() -> None:
    user = uuid4()
    joined_at = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    store = Store(
        memberships=[TeamMembership(user, CityCode.TOKYO, 0, joined_at)],
        flavor_codes={(user, CityCode.MOSCOW): 10},
    )
    service, store, _ = build(store, now=joined_at + TEAM_LOCK)

    switched = await service.change(user, CityCode.MOSCOW)
    status = await service.status(user)

    assert (switched.flavor, switched.switch_no) == (CityCode.MOSCOW, 1)
    assert status.team is not None and status.team.flavor is CityCode.MOSCOW
    assert status.switch_allowed_at == joined_at + TEAM_LOCK + TEAM_LOCK
