"""ChallengeService (C1): GET/POST /challenges against fakes.

Exercises the generic engine (progress check, idempotent claim, the
per-user wallet-row lock) for both shipped kinds: ``team_choice`` (once)
and ``distinct_flavors`` (period). The domain rule itself (unlock
threshold, team choice) lives in app/domain/teams.py and is tested there;
this file is about the challenge engine's own plumbing.
"""

import copy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.application.challenges import ChallengeService
from app.domain.achievements import Achievement, AchievementFact
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
NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)  # D:2026-10-15 in Tehran


@dataclass
class Store:
    wallets: dict[UUID, int] = field(default_factory=dict)
    team_memberships: list[TeamMembership] = field(default_factory=list)
    flavors_since: dict[UUID, int] = field(default_factory=dict)  # test-set progress
    mini_game_runs_total: dict[UUID, int] = field(default_factory=dict)
    fast_tap_reflex_since: dict[UUID, int] = field(default_factory=dict)
    claims: set[tuple[str, UUID, str]] = field(default_factory=set)
    challenges: dict[str, Challenge] = field(default_factory=dict)
    achievements: dict[str, Achievement] = field(default_factory=dict)
    user_achievements: set[tuple[str, UUID]] = field(default_factory=set)


def _current_team(store: Store, user_id: UUID) -> TeamMembership | None:
    mine = [m for m in store.team_memberships if m.user_id == user_id]
    return max(mine, key=lambda m: m.switch_no) if mine else None


def _checkin_dates(store: Store, challenge_id: str, user_id: UUID) -> set[date]:
    return {
        date.fromisoformat(key.removeprefix("D:"))
        for (cid, uid, key) in store.claims
        if cid == challenge_id and uid == user_id
    }


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

    async def checkin_days(self, challenge_id: str, user_id: UUID) -> set[date]:
        return _checkin_dates(self.store, challenge_id, user_id)

    async def accepted_mini_game_runs_total(self, user_id: UUID) -> int:
        return self.store.mini_game_runs_total.get(user_id, 0)

    async def fast_tap_reflex_runs_since(
        self, user_id: UUID, since: datetime, max_average_ms: float
    ) -> int:
        return self.store.fast_tap_reflex_since.get(user_id, 0)

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

    async def checkin_days(self, challenge_id: str, user_id: UUID) -> set[date]:
        return _checkin_dates(self.store, challenge_id, user_id)

    async def accepted_mini_game_runs_total(self, user_id: UUID) -> int:
        return self.store.mini_game_runs_total.get(user_id, 0)

    async def fast_tap_reflex_runs_since(
        self, user_id: UUID, since: datetime, max_average_ms: float
    ) -> int:
        return self.store.fast_tap_reflex_since.get(user_id, 0)

    async def has_claimed(
        self, challenge_id: str, user_id: UUID, period_key: str
    ) -> bool:
        return (challenge_id, user_id, period_key) in self.store.claims

    async def claim(
        self, challenge_id: str, user_id: UUID, period_key: str, now: datetime
    ) -> None:
        self.store.claims.add((challenge_id, user_id, period_key))


class FakeAchievements:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def list_active_by_fact(self, fact: AchievementFact) -> list[Achievement]:
        return [
            a for a in self.store.achievements.values() if a.fact is fact and a.active
        ]

    async def already_unlocked(self, achievement_id: str, user_id: UUID) -> bool:
        return (achievement_id, user_id) in self.store.user_achievements

    async def unlock(self, achievement_id: str, user_id: UUID, now: datetime) -> None:
        self.store.user_achievements.add((achievement_id, user_id))


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

    @property
    def achievements(self) -> FakeAchievements:
        return FakeAchievements(self.working)

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


def daily_checkin_challenge(reward: int = 10) -> Challenge:
    return Challenge(
        id="daily_checkin",
        kind=ChallengeKind.DAILY_CHECKIN,
        period=ChallengePeriod.DAY,
        target=1,
        reward_coins=reward,
        active=True,
    )


def first_mini_game_challenge(reward: int = 20) -> Challenge:
    return Challenge(
        id="first_mini_game",
        kind=ChallengeKind.FIRST_MINI_GAME,
        period=ChallengePeriod.ONCE,
        target=1,
        reward_coins=reward,
        active=True,
    )


def tap_reflex_fast_challenge(reward: int = 20) -> Challenge:
    return Challenge(
        id="tap_reflex_fast",
        kind=ChallengeKind.TAP_REFLEX_FAST,
        period=ChallengePeriod.DAY,
        target=1,
        reward_coins=reward,
        active=True,
    )


def streak_achievement(
    achievement_id: str, threshold: int, reward: int = 20
) -> Achievement:
    return Achievement(
        id=achievement_id,
        fact=AchievementFact.CHECKIN_STREAK,
        threshold=threshold,
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


async def test_daily_checkin_is_always_completed_and_pays() -> None:
    user = uuid4()
    store = Store(challenges={"daily_checkin": daily_checkin_challenge(reward=10)})
    service, _ = build(store)

    progress = await service.list(user)
    assert (progress[0].have, progress[0].target, progress[0].completed) == (
        1,
        1,
        True,
    )

    result = await service.claim(user, "daily_checkin")
    assert (result.coins_awarded, result.coin_balance, result.streak) == (10, 10, 1)


async def test_claiming_daily_checkin_twice_the_same_day_is_refused() -> None:
    user = uuid4()
    store = Store(challenges={"daily_checkin": daily_checkin_challenge()})
    service, store = build(store)
    await service.claim(user, "daily_checkin")

    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "daily_checkin")
    assert caught.value.reason is ChallengeClaimRefusal.ALREADY_CLAIMED


async def test_list_reports_the_current_streak_for_daily_checkin_only() -> None:
    user = uuid4()
    store = Store(
        challenges={
            "choose_team": team_choice_challenge(),
            "daily_checkin": daily_checkin_challenge(),
        },
        claims={
            ("daily_checkin", user, "D:2026-10-13"),
            ("daily_checkin", user, "D:2026-10-14"),
        },
    )
    service, _ = build(store)

    progress = await service.list(user)
    by_id = {p.id: p for p in progress}
    assert by_id["daily_checkin"].streak == 2  # today not claimed yet, chain intact
    assert by_id["choose_team"].streak is None


async def test_claiming_daily_checkin_unlocks_a_streak_achievement_and_pays_both() -> (
    None
):
    user = uuid4()
    store = Store(
        challenges={"daily_checkin": daily_checkin_challenge(reward=10)},
        achievements={
            "streak_3": streak_achievement("streak_3", threshold=3, reward=20)
        },
        claims={
            ("daily_checkin", user, "D:2026-10-13"),
            ("daily_checkin", user, "D:2026-10-14"),
        },
    )
    service, store = build(store)

    result = await service.claim(user, "daily_checkin")

    assert result.streak == 3
    assert [u.id for u in result.achievements_unlocked] == ["streak_3"]
    assert result.coin_balance == 10 + 20  # challenge reward + achievement reward
    assert ("streak_3", user) in store.user_achievements


async def test_achievement_unlock_is_one_time_even_after_a_rebuilt_streak() -> None:
    """The exploit the economy must not allow: breaking and rebuilding a
    streak must not re-pay an already-unlocked milestone (see
    docs/vault/Decisions.md 2026-10-15 on daily check-ins/streaks)."""
    user = uuid4()
    store = Store(
        challenges={"daily_checkin": daily_checkin_challenge(reward=10)},
        achievements={
            "streak_3": streak_achievement("streak_3", threshold=3, reward=20)
        },
        user_achievements={("streak_3", user)},  # already unlocked on an earlier run
        claims={
            # a fresh, rebuilt 3-day run ending today
            ("daily_checkin", user, "D:2026-10-13"),
            ("daily_checkin", user, "D:2026-10-14"),
        },
    )
    service, store = build(store)

    result = await service.claim(user, "daily_checkin")

    assert result.streak == 3
    assert result.achievements_unlocked == []  # no second payout
    assert result.coin_balance == 10  # challenge reward only, no achievement bonus


async def test_two_milestones_crossed_in_one_claim_both_unlock() -> None:
    """Defensive: if a streak crosses several thresholds at once, every
    newly-qualifying achievement unlocks in that same claim, not just one."""
    user = uuid4()
    store = Store(
        challenges={"daily_checkin": daily_checkin_challenge(reward=10)},
        achievements={
            "streak_1": streak_achievement("streak_1", threshold=1, reward=5),
            "streak_2": streak_achievement("streak_2", threshold=2, reward=15),
        },
        claims={("daily_checkin", user, "D:2026-10-14")},
    )
    service, store = build(store)

    result = await service.claim(user, "daily_checkin")

    assert result.streak == 2
    assert {u.id for u in result.achievements_unlocked} == {"streak_1", "streak_2"}
    assert result.coin_balance == 10 + 5 + 15


async def test_first_mini_game_is_locked_until_an_accepted_run_exists() -> None:
    user = uuid4()
    store = Store(challenges={"first_mini_game": first_mini_game_challenge()})
    service, _ = build(store)

    progress = await service.list(user)
    assert (progress[0].have, progress[0].completed) == (0, False)

    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "first_mini_game")
    assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED


async def test_first_mini_game_pays_once_an_accepted_run_exists() -> None:
    user = uuid4()
    store = Store(
        challenges={"first_mini_game": first_mini_game_challenge(reward=20)},
        mini_game_runs_total={user: 1},  # one ACCEPTED run, any mini-game id
    )
    service, store = build(store)

    result = await service.claim(user, "first_mini_game")

    assert (result.coins_awarded, result.coin_balance) == (20, 20)
    # Once-per-player (period ONCE): a second claim is refused even if more
    # runs pile up afterwards.
    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "first_mini_game")
    assert caught.value.reason is ChallengeClaimRefusal.ALREADY_CLAIMED


async def test_tap_reflex_fast_pays_only_for_a_qualifying_run_today() -> None:
    """The domain plausibility/threshold check itself lives in
    app/domain/mini_games.py and is tested there; this is the engine's
    read of the resulting count, same shape as ``distinct_flavors_since``."""
    user = uuid4()
    store = Store(challenges={"tap_reflex_fast": tap_reflex_fast_challenge()})
    service, _ = build(store)

    # No ACCEPTED run under the threshold yet (e.g. only a slow or a
    # REJECTED run today): not unlocked.
    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "tap_reflex_fast")
    assert caught.value.reason is ChallengeClaimRefusal.NOT_UNLOCKED

    # One ACCEPTED run under the threshold today: claimable, pays once.
    store.fast_tap_reflex_since[user] = 1
    result = await service.claim(user, "tap_reflex_fast")
    assert (result.coins_awarded, result.coin_balance) == (20, 20)

    with pytest.raises(ChallengeClaimError) as caught:
        await service.claim(user, "tap_reflex_fast")
    assert caught.value.reason is ChallengeClaimRefusal.ALREADY_CLAIMED
