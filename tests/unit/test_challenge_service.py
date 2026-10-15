"""ChallengeService (C1): GET/POST /challenges against fakes.

Exercises the generic engine (progress check, idempotent claim, the
per-user wallet-row lock) for both shipped kinds: ``team_choice`` (once)
and ``distinct_flavors`` (period). The domain rule itself (unlock
threshold, team choice) lives in app/domain/teams.py and is tested there;
this file is about the challenge engine's own plumbing.
"""

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.application.challenges import ChallengeService
from app.domain.challenges import (
    Challenge,
    ChallengeClaimError,
    ChallengeClaimRefusal,
    ChallengeKind,
    ChallengePeriod,
)
from app.domain.passports import CityCode
from app.domain.teams import TeamMembership

ZONE = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


@dataclass
class Store:
    wallets: dict[UUID, int] = field(default_factory=dict)
    team_memberships: list[TeamMembership] = field(default_factory=list)
    flavors_since: dict[UUID, int] = field(default_factory=dict)  # test-set progress
    claims: set[tuple[str, UUID, str]] = field(default_factory=set)
    challenges: dict[str, Challenge] = field(default_factory=dict)


def _current_team(store: Store, user_id: UUID) -> TeamMembership | None:
    mine = [m for m in store.team_memberships if m.user_id == user_id]
    return max(mine, key=lambda m: m.switch_no) if mine else None


class FakeTeamsReader:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current(self, user_id: UUID) -> TeamMembership | None:
        return _current_team(self.store, user_id)

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        return 0


class FakeChallengesReader:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list_active(self) -> list[Challenge]:
        return [c for c in self.store.challenges.values() if c.active]

    async def distinct_flavors_since(self, user_id: UUID, since: datetime) -> int:
        return self.store.flavors_since.get(user_id, 0)

    async def has_claimed(
        self, challenge_id: str, user_id: UUID, period_key: str
    ) -> bool:
        return (challenge_id, user_id, period_key) in self.store.claims


class FakeLedger:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.records: list[int] = []

    async def lock_wallet(self, user_id: UUID, now: datetime) -> int:
        return self.store.wallets.setdefault(user_id, 0)

    async def record(self, entry) -> int:  # type: ignore[no-untyped-def]
        self.records.append(entry.amount)
        balance = self.store.wallets.get(entry.user_id, 0) + entry.amount
        self.store.wallets[entry.user_id] = balance
        return balance


class FakeTeamsInTransaction:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current(self, user_id: UUID) -> TeamMembership | None:
        return _current_team(self.store, user_id)

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        return 0

    async def add(self, membership: TeamMembership) -> None:
        self.store.team_memberships.append(membership)


class FakeChallenges:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def get(self, challenge_id: str) -> Challenge | None:
        challenge = self.store.challenges.get(challenge_id)
        return challenge if challenge is not None and challenge.active else None

    async def get_by_kind(self, kind: ChallengeKind) -> Challenge | None:
        for challenge in self.store.challenges.values():
            if challenge.kind is kind and challenge.active:
                return challenge
        return None

    async def distinct_flavors_since(self, user_id: UUID, since: datetime) -> int:
        return self.store.flavors_since.get(user_id, 0)

    async def has_claimed(
        self, challenge_id: str, user_id: UUID, period_key: str
    ) -> bool:
        return (challenge_id, user_id, period_key) in self.store.claims

    async def claim(
        self, challenge_id: str, user_id: UUID, period_key: str, now: datetime
    ) -> None:
        self.store.claims.add((challenge_id, user_id, period_key))


class FakeUnitOfWork:
    def __init__(self, committed: Store) -> None:
        self._committed = committed
        self.working = Store()

    @property
    def ledger(self) -> FakeLedger:
        return self._ledger

    @property
    def teams(self) -> FakeTeamsInTransaction:
        return FakeTeamsInTransaction(self.working)

    @property
    def challenges(self) -> FakeChallenges:
        return FakeChallenges(self.working)

    async def __aenter__(self) -> Self:
        self.working = copy.deepcopy(self._committed)
        self._ledger = FakeLedger(self.working)
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


class FakeClock:
    def now(self) -> datetime:
        return NOW


def build(store: Store | None = None) -> tuple[ChallengeService, Store]:
    store = store if store is not None else Store()
    service = ChallengeService(
        reader=FakeChallengesReader(store),
        teams=FakeTeamsReader(store),
        unit_of_work=lambda: FakeUnitOfWork(store),
        clock=FakeClock(),
        zone=ZONE,
    )
    return service, store


def team_choice_challenge(reward: int = 30) -> Challenge:
    return Challenge(
        id="choose_team",
        kind=ChallengeKind.TEAM_CHOICE,
        period=ChallengePeriod.ONCE,
        target=1,
        reward_coins=reward,
        active=True,
    )


def distinct_flavors_challenge(target: int = 3, reward: int = 100) -> Challenge:
    return Challenge(
        id="discover_3_flavors",
        kind=ChallengeKind.DISTINCT_FLAVORS,
        period=ChallengePeriod.MONTH,
        target=target,
        reward_coins=reward,
        active=True,
    )


async def test_list_reports_progress_against_each_active_challenge() -> None:
    user = uuid4()
    store = Store(
        challenges={"choose_team": team_choice_challenge()},
        flavors_since={},
    )
    service, _ = build(store)

    progress = await service.list(user)

    assert len(progress) == 1
    assert (progress[0].have, progress[0].completed, progress[0].claimed) == (
        0,
        False,
        False,
    )


async def test_list_reflects_team_already_joined() -> None:
    user = uuid4()
    store = Store(
        challenges={"choose_team": team_choice_challenge()},
        team_memberships=[TeamMembership(user, CityCode.TOKYO, 0, NOW)],
    )
    service, _ = build(store)

    progress = await service.list(user)

    assert (progress[0].have, progress[0].completed) == (1, True)


async def test_claiming_team_choice_pays_and_then_refuses_a_second_claim() -> None:
    user = uuid4()
    store = Store(
        challenges={"choose_team": team_choice_challenge(reward=30)},
        team_memberships=[TeamMembership(user, CityCode.TOKYO, 0, NOW)],
    )
    service, store = build(store)

    result = await service.claim(user, "choose_team")

    assert (result.coins_awarded, result.coin_balance) == (30, 30)

    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "choose_team")
    assert caught.value.reason is ChallengeClaimRefusal.ALREADY_CLAIMED


async def test_claiming_before_the_target_is_met_reports_required_and_have() -> None:
    user = uuid4()
    store = Store(
        challenges={"discover_3_flavors": distinct_flavors_challenge(target=3)},
        flavors_since={user: 1},
    )
    service, _ = build(store)

    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "discover_3_flavors")

    assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED
    assert (caught.value.required, caught.value.have) == (3, 1)


async def test_claiming_an_unknown_challenge_id_is_refused() -> None:
    service, _ = build()

    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(uuid4(), "no-such-challenge")

    assert caught.value.reason is ChallengeClaimRefusal.UNKNOWN


async def test_claiming_an_inactive_challenge_is_refused_like_unknown() -> None:
    user = uuid4()
    store = Store(
        challenges={
            "choose_team": Challenge(
                id="choose_team",
                kind=ChallengeKind.TEAM_CHOICE,
                period=ChallengePeriod.ONCE,
                target=1,
                reward_coins=30,
                active=False,
            )
        },
        team_memberships=[TeamMembership(user, CityCode.TOKYO, 0, NOW)],
    )
    service, _ = build(store)

    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "choose_team")

    assert caught.value.reason is ChallengeClaimRefusal.UNKNOWN


async def test_a_zero_reward_challenge_still_marks_itself_claimed() -> None:
    user = uuid4()
    store = Store(
        challenges={"choose_team": team_choice_challenge(reward=0)},
        team_memberships=[TeamMembership(user, CityCode.TOKYO, 0, NOW)],
    )
    service, store = build(store)

    result = await service.claim(user, "choose_team")

    assert result.coins_awarded == 0
    progress = await service.list(user)
    assert progress[0].claimed is True


async def test_two_different_users_claim_independently() -> None:
    alice, bob = uuid4(), uuid4()
    store = Store(
        challenges={"choose_team": team_choice_challenge()},
        team_memberships=[
            TeamMembership(alice, CityCode.TOKYO, 0, NOW),
            TeamMembership(bob, CityCode.MOSCOW, 0, NOW),
        ],
    )
    service, store = build(store)

    await service.claim(alice, "choose_team")

    # Bob's own claim is unaffected by Alice's.
    result = await service.claim(bob, "choose_team")
    assert result.coins_awarded == 30
