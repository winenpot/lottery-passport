"""RedemptionService rules, against an in-memory unit of work.

The fake applies changes to a copy of the store and only publishes them on
commit, so these tests also prove that a failed redemption leaves nothing
behind. Concurrency and real constraints are covered by
``tests/integration/test_redemption_flow.py``.
"""

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from app.application.failure_throttle import ThrottleSettings
from app.application.redemption_codes import (
    RedemptionError,
    RedemptionErrorCode,
    RedemptionService,
    first_code_bonus_idempotency_key,
    hash_redemption_code,
    seconds_until_next_local_midnight,
    start_of_local_day,
)
from app.application.unit_of_work import ClaimedCode, CodeLookup
from app.domain.codes import ALPHABET, compute_check_value, generate_code
from app.domain.ledger import NewLedgerEntry
from app.domain.passports import Campaign, CityCode, PassportProgress
from app.domain.reward_rules import Cadence, RewardRule
from app.domain.teams import TeamMembership

PEPPER = "test-pepper"
TEHRAN = ZoneInfo("Asia/Tehran")


@dataclass
class StoredCode:
    id: UUID
    city: CityCode
    batch_active: bool
    coins_per_code: int
    redeemed_by: UUID | None = None
    redeemed_at: datetime | None = None


@dataclass
class Store:
    codes: dict[str, StoredCode] = field(default_factory=dict)
    entries: dict[tuple[UUID, Campaign], int] = field(default_factory=dict)
    ledger: list[NewLedgerEntry] = field(default_factory=list)
    wallets: dict[UUID, int] = field(default_factory=dict)
    rules: dict[str, RewardRule] = field(default_factory=dict)
    team_memberships: list[TeamMembership] = field(default_factory=list)


class FakeCodes:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def claim(
        self, code_hash: str, user_id: UUID, now: datetime
    ) -> ClaimedCode | None:
        code = self.store.codes.get(code_hash)
        if code is None or code.redeemed_by is not None or not code.batch_active:
            return None
        code.redeemed_by, code.redeemed_at = user_id, now
        return ClaimedCode(code.id, code.city, code.coins_per_code)

    async def lookup(self, code_hash: str) -> CodeLookup | None:
        code = self.store.codes.get(code_hash)
        if code is None:
            return None
        return CodeLookup(code.id, code.city, code.redeemed_by, code.batch_active)

    async def count_redeemed_since(self, user_id: UUID, since: datetime) -> int:
        return sum(
            1
            for code in self.store.codes.values()
            if code.redeemed_by == user_id
            and code.redeemed_at is not None
            and code.redeemed_at >= since
        )


class FakePassports:
    def __init__(self, store: Store) -> None:
        self.store = store

    def _progress(self, user_id: UUID, campaign: Campaign) -> PassportProgress:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        points = self.store.entries[(user_id, campaign)]
        return PassportProgress(uuid4(), user_id, campaign, points, now, now)

    async def add_entries(
        self, user_id: UUID, campaign: Campaign, amount: int, now: datetime
    ) -> PassportProgress:
        key = (user_id, campaign)
        self.store.entries[key] = self.store.entries.get(key, 0) + amount
        return self._progress(user_id, campaign)

    async def get(self, user_id: UUID, campaign: Campaign) -> PassportProgress | None:
        if (user_id, campaign) not in self.store.entries:
            return None
        return self._progress(user_id, campaign)


class FakeLedger:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def lock_wallet(self, user_id: UUID, now: datetime) -> int:
        return self.store.wallets.setdefault(user_id, 0)

    async def record(self, entry: NewLedgerEntry) -> int:
        if any(e.idempotency_key == entry.idempotency_key for e in self.store.ledger):
            raise AssertionError("duplicate idempotency key")  # the DB would reject
        self.store.ledger.append(entry)
        self.store.wallets[entry.user_id] += entry.amount
        return self.store.wallets[entry.user_id]

    async def amount_for_key(self, idempotency_key: str) -> int | None:
        for entry in self.store.ledger:
            if entry.idempotency_key == idempotency_key:
                return entry.amount
        return None


class FakeRewardRules:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def get(self, key: str) -> RewardRule | None:
        return self.store.rules.get(key)


class FakeTeams:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current(self, user_id: UUID) -> TeamMembership | None:
        memberships = [m for m in self.store.team_memberships if m.user_id == user_id]
        return max(memberships, key=lambda m: m.switch_no) if memberships else None

    async def count_codes(self, user_id: UUID, flavor: CityCode) -> int:
        return sum(
            1
            for code in self.store.codes.values()
            if code.redeemed_by == user_id and code.city is flavor
        )

    async def add(self, membership: TeamMembership) -> None:
        self.store.team_memberships.append(membership)


class FakeUnitOfWork:
    def __init__(self, committed: Store) -> None:
        self._committed = committed
        self.working = Store()

    @property
    def codes(self) -> FakeCodes:
        return FakeCodes(self.working)

    @property
    def passports(self) -> FakePassports:
        return FakePassports(self.working)

    @property
    def ledger(self) -> FakeLedger:
        return FakeLedger(self.working)

    @property
    def rules(self) -> FakeRewardRules:
        return FakeRewardRules(self.working)

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


@dataclass
class FakeThrottle:
    failures: list[tuple[UUID, datetime]] = field(default_factory=list)

    async def record(self, user_id: UUID, occurred_at: datetime) -> None:
        self.failures.append((user_id, occurred_at))

    async def count_in_window(self, user_id: UUID, window_start: datetime) -> int:
        return sum(
            1 for uid, t in self.failures if uid == user_id and t >= window_start
        )


def build(
    *,
    daily_limit: int = 20,
    now: datetime | None = None,
    throttle: FakeThrottle | None = None,
    max_invalid_attempts: int = 10,
    first_code_bonus_coins: int = 0,
) -> tuple[RedemptionService, Store, FakeClock]:
    store = Store()
    clock = FakeClock(now or datetime(2026, 10, 10, 12, 0, tzinfo=UTC))
    service = RedemptionService(
        unit_of_work=lambda: FakeUnitOfWork(store),
        clock=clock,
        pepper=PEPPER,
        daily_limit=daily_limit,
        campaign_zone=TEHRAN,
        throttle=throttle,
        throttle_settings=ThrottleSettings(
            max_attempts=max_invalid_attempts, window_seconds=3600
        ),
        first_code_bonus_coins=first_code_bonus_coins,
    )
    return service, store, clock


def add_code(
    store: Store,
    city: CityCode = CityCode.TOKYO,
    *,
    batch_active: bool = True,
    coins: int = 10,
) -> str:
    code = generate_code(city)
    store.codes[hash_redemption_code(code, PEPPER)] = StoredCode(
        id=uuid4(), city=city, batch_active=batch_active, coins_per_code=coins
    )
    return code


async def test_redeem_adds_one_entry_and_the_batch_coins() -> None:
    service, store, _ = build()
    user = uuid4()
    code = add_code(store, coins=15)

    result = await service.redeem(user, code.lower())

    assert (result.city, result.entries_added, result.city_entries) == (
        CityCode.TOKYO,
        1,
        1,
    )
    assert (result.coins_awarded, result.coin_balance, result.replayed) == (
        15,
        15,
        False,
    )
    assert store.wallets[user] == 15
    assert len(store.ledger) == 1


async def test_entries_accumulate_per_city_and_never_cross_cities() -> None:
    service, store, _ = build()
    user = uuid4()
    for _ in range(3):
        await service.redeem(user, add_code(store, CityCode.MOSCOW))
    await service.redeem(user, add_code(store, CityCode.PARIS))

    assert store.entries[(user, Campaign.MOSCOW)] == 3
    assert store.entries[(user, Campaign.PARIS)] == 1


async def test_resubmitting_your_own_code_replays_without_new_coins() -> None:
    service, store, _ = build()
    user = uuid4()
    code = add_code(store, coins=10)
    first = await service.redeem(user, code)

    again = await service.redeem(user, code)

    assert again.replayed is True
    assert (again.coins_awarded, again.coin_balance, again.city_entries) == (10, 10, 1)
    assert first.coin_balance == again.coin_balance
    assert len(store.ledger) == 1


async def test_someone_elses_code_is_already_redeemed() -> None:
    service, store, _ = build()
    code = add_code(store)
    await service.redeem(uuid4(), code)

    with pytest.raises(RedemptionError) as raised:
        await service.redeem(uuid4(), code)

    assert raised.value.code is RedemptionErrorCode.ALREADY_REDEEMED


async def test_unknown_and_inactive_batch_codes_look_the_same() -> None:
    service, store, _ = build()
    inactive = add_code(store, batch_active=False)
    unknown = generate_code(CityCode.TOKYO)

    for code in (inactive, unknown):
        with pytest.raises(RedemptionError) as raised:
            await service.redeem(uuid4(), code)
        assert raised.value.code is RedemptionErrorCode.INVALID


async def test_typos_and_garbage_are_rejected_before_touching_the_store() -> None:
    service, store, _ = build()
    code = add_code(store)
    wrong_check = code[:-1] + ("0" if code[-1] != "0" else "1")

    with pytest.raises(RedemptionError) as mistyped:
        await service.redeem(uuid4(), wrong_check)
    with pytest.raises(RedemptionError) as malformed:
        await service.redeem(uuid4(), "hello")

    assert mistyped.value.code is RedemptionErrorCode.MISTYPED
    assert malformed.value.code is RedemptionErrorCode.MALFORMED
    assert store.wallets == {}


async def test_daily_limit_rolls_back_the_claim_so_the_code_stays_usable() -> None:
    service, store, _ = build(daily_limit=2)
    user = uuid4()
    await service.redeem(user, add_code(store))
    await service.redeem(user, add_code(store))
    third = add_code(store)

    with pytest.raises(RedemptionError) as raised:
        await service.redeem(user, third)

    assert raised.value.code is RedemptionErrorCode.DAILY_LIMIT
    assert raised.value.retry_after is not None and raised.value.retry_after > 0
    assert store.codes[hash_redemption_code(third, PEPPER)].redeemed_by is None
    assert store.wallets[user] == 20
    assert len(store.ledger) == 2


def test_seconds_until_next_local_midnight_counts_to_tehran_not_utc() -> None:
    moment = datetime(2026, 10, 10, 20, 29, tzinfo=UTC)  # 23:59 in Tehran

    assert seconds_until_next_local_midnight(moment, TEHRAN) == 60


async def test_daily_limit_resets_at_tehran_midnight_not_utc_midnight() -> None:
    # 20:29 UTC is 23:59 in Tehran (UTC+03:30, no DST since 2023).
    before_midnight = datetime(2026, 10, 10, 20, 29, tzinfo=UTC)
    service, store, clock = build(daily_limit=1, now=before_midnight)
    user = uuid4()
    await service.redeem(user, add_code(store))

    clock.current = before_midnight + timedelta(minutes=2)  # 00:01 in Tehran
    result = await service.redeem(user, add_code(store))

    assert result.replayed is False


def test_start_of_local_day_uses_the_campaign_zone() -> None:
    moment = datetime(2026, 10, 10, 21, 0, tzinfo=UTC)  # 00:30 on the 11th

    start = start_of_local_day(moment, TEHRAN)

    assert start.astimezone(UTC) == datetime(2026, 10, 10, 20, 30, tzinfo=UTC)


async def test_lottery_only_batches_add_entries_without_ledger_rows() -> None:
    service, store, _ = build()
    user = uuid4()

    result = await service.redeem(user, add_code(store, coins=0))

    assert (result.coins_awarded, result.city_entries) == (0, 1)
    assert store.ledger == []


async def test_missing_pepper_fails_closed() -> None:
    service = RedemptionService(
        unit_of_work=lambda: FakeUnitOfWork(Store()),
        clock=FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        pepper=None,
        daily_limit=20,
        campaign_zone=TEHRAN,
    )
    body = "7KQ2M9XH4R"
    code = f"TO{body}{ALPHABET[compute_check_value(CityCode.TOKYO, body)]}"

    with pytest.raises(RedemptionError) as raised:
        await service.redeem(uuid4(), code)

    assert raised.value.code is RedemptionErrorCode.NOT_CONFIGURED


def test_hash_is_keyed_by_the_pepper() -> None:
    assert hash_redemption_code("TO1", "a") == hash_redemption_code("TO1", "a")
    assert hash_redemption_code("TO1", "a") != hash_redemption_code("TO1", "b")


# ---------------------------------------------------------------------------
# Per-account invalid-code throttle
# ---------------------------------------------------------------------------


async def test_invalid_code_is_recorded_in_the_throttle() -> None:
    throttle = FakeThrottle()
    service, store, _ = build(throttle=throttle)
    user = uuid4()
    body = "7KQ2M9XH4R"
    bad_code = f"TO{body}{ALPHABET[compute_check_value(CityCode.TOKYO, body)]}"
    # make the hash unknown so it becomes CODE_INVALID
    with pytest.raises(RedemptionError) as raised:
        await service.redeem(user, bad_code)

    assert raised.value.code is RedemptionErrorCode.INVALID
    assert len(throttle.failures) == 1
    assert throttle.failures[0][0] == user


async def test_malformed_code_does_not_count_against_the_throttle() -> None:
    throttle = FakeThrottle()
    service, _, _ = build(throttle=throttle)
    with pytest.raises(RedemptionError) as raised:
        await service.redeem(uuid4(), "not-a-code")
    assert raised.value.code is RedemptionErrorCode.MALFORMED
    assert throttle.failures == []


async def test_eleventh_invalid_attempt_is_refused_before_db_work() -> None:
    throttle = FakeThrottle()
    service, store, _ = build(throttle=throttle, max_invalid_attempts=10)
    user = uuid4()
    body = "7KQ2M9XH4R"
    bad_code = f"TO{body}{ALPHABET[compute_check_value(CityCode.TOKYO, body)]}"

    # burn 10 failures
    for _ in range(10):
        with pytest.raises(RedemptionError):
            await service.redeem(user, bad_code)

    assert len(throttle.failures) == 10

    # 11th attempt is blocked before touching the store
    with pytest.raises(RedemptionError) as raised:
        await service.redeem(user, bad_code)

    assert raised.value.code is RedemptionErrorCode.ATTEMPTS_LIMITED
    assert raised.value.retry_after == 3600
    assert len(throttle.failures) == 10  # no new failure recorded when throttled


async def test_throttle_is_per_account_not_global() -> None:
    throttle = FakeThrottle()
    service, store, _ = build(throttle=throttle, max_invalid_attempts=2)
    user_a, user_b = uuid4(), uuid4()
    body = "7KQ2M9XH4R"
    bad_code = f"TO{body}{ALPHABET[compute_check_value(CityCode.TOKYO, body)]}"

    for _ in range(2):
        with pytest.raises(RedemptionError):
            await service.redeem(user_a, bad_code)

    # user_b is not throttled even though user_a is
    with pytest.raises(RedemptionError) as raised:
        await service.redeem(user_b, bad_code)

    assert raised.value.code is RedemptionErrorCode.INVALID  # not ATTEMPTS_LIMITED


async def test_no_throttle_configured_does_not_block() -> None:
    # When throttle=None, the service keeps working normally (NullThrottle default).
    service, store, _ = build(throttle=None)
    user = uuid4()
    result = await service.redeem(user, add_code(store))
    assert result.replayed is False


# ---------------------------------------------------------------------------
# First-code bonus (ADR 0010)
# ---------------------------------------------------------------------------


async def test_first_code_bonus_is_off_by_default() -> None:
    service, store, _ = build()  # first_code_bonus_coins defaults to 0
    user = uuid4()

    result = await service.redeem(user, add_code(store, coins=10))

    assert (result.bonus_awarded, result.coin_balance) == (0, 10)
    assert len(store.ledger) == 1


async def test_first_code_bonus_pays_once_on_the_first_redemption() -> None:
    service, store, _ = build(first_code_bonus_coins=50)
    user = uuid4()

    first = await service.redeem(user, add_code(store, coins=10))
    second = await service.redeem(user, add_code(store, coins=10))

    assert (first.bonus_awarded, first.coin_balance) == (50, 60)
    assert (second.bonus_awarded, second.coin_balance) == (0, 70)
    assert store.wallets[user] == 70
    bonus_entries = [
        e
        for e in store.ledger
        if e.idempotency_key == first_code_bonus_idempotency_key(user)
    ]
    assert len(bonus_entries) == 1


async def test_first_code_bonus_is_per_user() -> None:
    service, store, _ = build(first_code_bonus_coins=50)

    first_user = await service.redeem(uuid4(), add_code(store, coins=0))
    second_user = await service.redeem(uuid4(), add_code(store, coins=0))

    assert first_user.bonus_awarded == 50
    assert second_user.bonus_awarded == 50


async def test_reward_rule_overrides_the_configured_bonus_amount() -> None:
    service, store, _ = build(first_code_bonus_coins=50)
    store.rules["first_code"] = RewardRule(
        key="first_code", amount=99, cadence=Cadence.ONCE, active=True
    )
    user = uuid4()

    result = await service.redeem(user, add_code(store, coins=0))

    assert result.bonus_awarded == 99


async def test_reward_rule_can_switch_the_bonus_off() -> None:
    service, store, _ = build(first_code_bonus_coins=50)
    store.rules["first_code"] = RewardRule(
        key="first_code", amount=50, cadence=Cadence.ONCE, active=False
    )
    user = uuid4()

    result = await service.redeem(user, add_code(store, coins=0))

    assert result.bonus_awarded == 0
    assert store.ledger == []


# ---------------------------------------------------------------------------
# Flavor unlock (teams, P1.4)
# ---------------------------------------------------------------------------


async def test_the_fifth_code_of_a_flavor_reports_it_unlocked() -> None:
    service, store, _ = build()
    user = uuid4()

    results = [
        await service.redeem(user, add_code(store, CityCode.MOSCOW)) for _ in range(5)
    ]

    assert [r.flavor_unlocked for r in results] == [
        None,
        None,
        None,
        None,
        CityCode.MOSCOW,
    ]


async def test_a_sixth_code_does_not_report_an_unlock_again() -> None:
    service, store, _ = build()
    user = uuid4()
    for _ in range(5):
        await service.redeem(user, add_code(store, CityCode.MOSCOW))

    sixth = await service.redeem(user, add_code(store, CityCode.MOSCOW))

    assert sixth.flavor_unlocked is None


async def test_flavors_unlock_independently_per_user() -> None:
    service, store, _ = build()
    user_a, user_b = uuid4(), uuid4()
    for _ in range(4):
        await service.redeem(user_a, add_code(store, CityCode.TOKYO))

    result = await service.redeem(user_b, add_code(store, CityCode.TOKYO))

    assert result.flavor_unlocked is None  # user_b's first code, not user_a's fifth


async def test_a_replay_never_reports_an_unlock() -> None:
    service, store, _ = build()
    user = uuid4()
    codes = [add_code(store, CityCode.TOKYO) for _ in range(5)]
    for code in codes[:-1]:
        await service.redeem(user, code)
    first_try = await service.redeem(user, codes[-1])

    replay = await service.redeem(user, codes[-1])

    assert (first_try.flavor_unlocked, replay.replayed) == (CityCode.TOKYO, True)
    assert replay.flavor_unlocked is None
