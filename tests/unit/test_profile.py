"""Nickname rules, campaign calendar, profile service and the config/profile routes."""

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.api.deps import (
    get_app_config_service,
    get_current_user,
    get_profile_service,
)
from app.app import create_app
from app.application.app_config import AppConfigService
from app.application.authentication import AuthenticationError
from app.application.profile import (
    NicknameTaken,
    ProfileService,
    TermsVersionMismatch,
    VenueUnknown,
)
from app.core.config import Settings
from app.domain.calendar import campaign_period
from app.domain.nickname import Nickname, NicknameError, parse_nickname
from app.domain.users import AccountStatus, User, UserRole, VerificationStatus
from app.domain.venues import Venue

TEHRAN = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 10, 10, 8, 30, tzinfo=UTC)


# --- nickname -------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", ["NightOwl", "علی_رضا", "a.b-c_9", "می\u200cخواهم", "نیما۱۲"]
)
def test_valid_nicknames_are_accepted(raw: str) -> None:
    assert parse_nickname(raw).display == raw


@pytest.mark.parametrize(
    "raw",
    [
        "ab",  # too short
        "x" * 17,  # too long
        "has space",
        "evil\u202etxt",  # right-to-left override
        "zero\u200bwidth",  # zero-width space
        "join\u200der",  # zero-width joiner
        "bom\ufeffname",
        "\u200cعلی",  # ZWNJ at the start
        "علی\u200c",  # ZWNJ at the end
        "ع\u200c\u200cلی",  # ZWNJ twice
        "smile😀",
        "аdmin_",  # Cyrillic a: look-alike script is not whitelisted
        "ali@home",
        "admin",
        "Support",
    ],
)
def test_invalid_nicknames_are_rejected(raw: str) -> None:
    with pytest.raises(NicknameError):
        parse_nickname(raw)


def test_the_key_folds_case_and_arabic_variants() -> None:
    assert parse_nickname("Ali").key == parse_nickname("ALI").key
    assert parse_nickname("علي").key == parse_nickname("علی").key
    assert parse_nickname("کیان").key == parse_nickname("كيان").key
    assert parse_nickname("نیما۱۲").key == parse_nickname("نیما12").key


def test_whitespace_is_trimmed_and_nfc_normalised() -> None:
    assert parse_nickname("  Night  ").display == "Night"
    decomposed = "e\u0301le"  # e + combining acute: not whitelisted either way
    with pytest.raises(NicknameError):
        parse_nickname(decomposed)


# --- calendar -------------------------------------------------------------


def test_period_matches_the_contract_example() -> None:
    period = campaign_period(NOW, TEHRAN)  # a Saturday in Tehran

    assert period.day_key == "D:2026-10-10"
    assert period.week_key == "W:2026-10-10"
    assert period.day_ends_at == datetime(2026, 10, 10, 20, 30, tzinfo=UTC)
    assert period.week_ends_at == datetime(2026, 10, 16, 20, 30, tzinfo=UTC)


def test_the_week_starts_on_saturday_and_ends_friday_midnight() -> None:
    friday = campaign_period(datetime(2026, 10, 16, 12, 0, tzinfo=UTC), TEHRAN)
    saturday = campaign_period(datetime(2026, 10, 16, 21, 0, tzinfo=UTC), TEHRAN)

    assert friday.week_key == "W:2026-10-10"
    assert saturday.week_key == "W:2026-10-17"
    assert saturday.day_key == "D:2026-10-17"


# --- profile service ------------------------------------------------------


def make_user(role: UserRole = UserRole.PLAYER) -> User:
    return User(
        id=UUID(int=1),
        identifier="+989120000001",
        display_name=None,
        account_status=AccountStatus.ACTIVE,
        verification_status=VerificationStatus.VERIFIED,
        role=role,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeVenues:
    def __init__(self) -> None:
        self.venues = [
            Venue(id="parsa", name="Parsa", city="tehran", address="تهران، پونک"),
            Venue(id="old", name="Old", city="tehran", active=False),
        ]

    async def list_active(self) -> list[Venue]:
        return [venue for venue in self.venues if venue.active]

    async def exists_active(self, venue_id: str) -> bool:
        return any(v.id == venue_id and v.active for v in self.venues)


class FakeStore:
    def __init__(self) -> None:
        self.user: User | None = make_user()
        self.taken: set[str] = set()

    async def update_profile(
        self,
        user_id: UUID,
        now: datetime,
        *,
        nickname: Nickname | None,
        terms_version: str | None,
        home_venue_id: str | None = None,
    ) -> User | None:
        if self.user is None:
            return None
        if home_venue_id is not None:
            self.user.home_venue_id = home_venue_id
        if nickname is not None:
            if nickname.key in self.taken:
                raise NicknameTaken(nickname.display)
            self.user.nickname = nickname.display
        if terms_version is not None:
            self.user.terms_version = terms_version
            self.user.terms_accepted_at = now
        return self.user


def service(store: FakeStore | None = None) -> tuple[ProfileService, FakeStore]:
    store = store or FakeStore()
    return ProfileService(store, FakeClock(), "2026-10-01", FakeVenues()), store


async def test_profile_is_complete_once_nickname_and_terms_are_set() -> None:
    profile, _ = service()

    after_nickname = await profile.update(
        UUID(int=1), nickname="NightOwl", accept_terms_version=None
    )
    assert after_nickname.nickname == "NightOwl"
    assert not after_nickname.profile_complete

    done = await profile.update(
        UUID(int=1), nickname=None, accept_terms_version="2026-10-01"
    )
    assert done.profile_complete
    assert done.terms_accepted_at == NOW


async def test_a_stale_terms_version_is_refused() -> None:
    profile, store = service()

    with pytest.raises(TermsVersionMismatch):
        await profile.update(
            UUID(int=1), nickname=None, accept_terms_version="2025-01-01"
        )
    assert store.user is not None and store.user.terms_accepted_at is None


async def test_invalid_and_taken_nicknames_propagate() -> None:
    store = FakeStore()
    store.taken.add("nightowl")
    profile, _ = service(store)

    with pytest.raises(NicknameError):
        await profile.update(UUID(int=1), nickname="a b", accept_terms_version=None)
    with pytest.raises(NicknameTaken):
        await profile.update(
            UUID(int=1), nickname="NIGHTOWL", accept_terms_version=None
        )


async def test_an_unknown_user_is_an_authentication_error() -> None:
    store = FakeStore()
    store.user = None
    profile, _ = service(store)

    with pytest.raises(AuthenticationError):
        await profile.update(
            UUID(int=1), nickname="NightOwl", accept_terms_version=None
        )


async def test_home_venue_must_be_an_active_venue() -> None:
    profile, store = service()

    user = await profile.update(
        UUID(int=1), nickname=None, accept_terms_version=None, home_venue_id="parsa"
    )
    assert user.home_venue_id == "parsa"

    for bad in ("old", "nowhere"):
        with pytest.raises(VenueUnknown):
            await profile.update(
                UUID(int=1), nickname=None, accept_terms_version=None, home_venue_id=bad
            )
    assert store.user is not None and store.user.home_venue_id == "parsa"


# --- routes ---------------------------------------------------------------


def client(store: FakeStore | None = None) -> tuple[TestClient, FakeStore]:
    profile, store = service(store)
    app = create_app(
        Settings(
            database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/x",
        )
    )
    app.dependency_overrides[get_profile_service] = lambda: profile
    app.dependency_overrides[get_app_config_service] = lambda: AppConfigService(
        FakeClock(), TEHRAN, "2026-10-01", 20, FakeVenues()
    )
    assert store.user is not None
    user = store.user
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), store


def test_config_is_public_and_matches_the_contract() -> None:
    http, _ = client()
    http.app.dependency_overrides.pop(get_current_user)  # type: ignore[attr-defined]

    response = http.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json() == {
        "server_time": "2026-10-10T08:30:00Z",
        "timezone": "Asia/Tehran",
        "day_key": "D:2026-10-10",
        "week_key": "W:2026-10-10",
        "day_ends_at": "2026-10-10T20:30:00Z",
        "week_ends_at": "2026-10-16T20:30:00Z",
        "terms_version": "2026-10-01",
        "limits": {"scans_per_day": 20},
        "nickname": {"min_length": 3, "max_length": 16},
        "cities": [
            {"id": "tehran", "name": "تهران"},
            {"id": "ahvaz", "name": "اهواز"},
            {"id": "mashhad", "name": "مشهد"},
            {"id": "isfahan", "name": "اصفهان"},
        ],
        "venues": [
            {
                "id": "parsa",
                "name": "Parsa",
                "city": "tehran",
                "address": "تهران، پونک",
            }
        ],
    }


def test_patch_me_sets_nickname_and_terms() -> None:
    http, _ = client()

    response = http.patch(
        "/api/v1/me",
        json={"nickname": "NightOwl", "accept_terms_version": "2026-10-01"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["nickname"] == "NightOwl"
    assert body["terms_accepted"] is True
    assert body["profile_complete"] is True


def test_patch_me_error_codes() -> None:
    store = FakeStore()
    store.taken.add("taken")
    http, _ = client(store)

    invalid = http.patch("/api/v1/me", json={"nickname": "bad name"})
    taken = http.patch("/api/v1/me", json={"nickname": "Taken"})
    stale = http.patch("/api/v1/me", json={"accept_terms_version": "1999"})

    assert (invalid.status_code, invalid.json()["error"]["code"]) == (
        422,
        "NICKNAME_INVALID",
    )
    assert (taken.status_code, taken.json()["error"]["code"]) == (409, "NICKNAME_TAKEN")
    assert (stale.status_code, stale.json()["error"]["code"]) == (
        422,
        "TERMS_VERSION_INVALID",
    )


def test_patch_me_home_venue() -> None:
    http, _ = client()

    ok = http.patch("/api/v1/me", json={"home_venue_id": "parsa"})
    unknown = http.patch("/api/v1/me", json={"home_venue_id": "old"})

    assert ok.status_code == 200 and ok.json()["home_venue_id"] == "parsa"
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (
        422,
        "CATALOGUE_UNKNOWN",
    )


def test_an_empty_patch_changes_nothing() -> None:
    http, store = client()

    response = http.patch("/api/v1/me", json={})

    assert response.status_code == 200
    assert response.json()["profile_complete"] is False
    assert store.user is not None and store.user.nickname is None
