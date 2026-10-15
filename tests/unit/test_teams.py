from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.passports import CityCode
from app.domain.teams import (
    TEAM_LOCK,
    UNLOCK_THRESHOLD,
    TeamChangeError,
    TeamChangeRefusal,
    TeamMembership,
    change_team,
    is_unlocked,
    unlocks_now,
)

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def test_five_codes_unlock_a_flavor() -> None:
    assert UNLOCK_THRESHOLD == 5
    assert not is_unlocked(4)
    assert is_unlocked(5)
    assert is_unlocked(40)


def test_the_unlock_fires_once_on_the_fifth_code() -> None:
    assert [count for count in range(1, 20) if unlocks_now(count)] == [5]


def test_the_lock_lasts_thirty_days() -> None:
    assert timedelta(days=30) == TEAM_LOCK


def test_first_join_needs_an_unlocked_flavor() -> None:
    user_id = uuid4()

    with pytest.raises(TeamChangeError) as caught:
        change_team(user_id, None, CityCode.TOKYO, 4, NOW)
    assert caught.value.reason is TeamChangeRefusal.FLAVOR_NOT_UNLOCKED
    assert (caught.value.required, caught.value.have) == (5, 4)

    team = change_team(user_id, None, CityCode.TOKYO, 5, NOW)
    assert team == TeamMembership(user_id, CityCode.TOKYO, 0, NOW)


def test_switching_is_locked_for_thirty_days_after_joining() -> None:
    user_id = uuid4()
    team = TeamMembership(user_id, CityCode.TOKYO, 0, NOW)
    almost = NOW + TEAM_LOCK - timedelta(seconds=1)

    with pytest.raises(TeamChangeError) as caught:
        change_team(user_id, team, CityCode.MOSCOW, 12, almost)
    assert caught.value.reason is TeamChangeRefusal.TEAM_LOCKED
    assert caught.value.allowed_at == NOW + TEAM_LOCK

    switched = change_team(user_id, team, CityCode.MOSCOW, 12, NOW + TEAM_LOCK)
    assert (switched.flavor, switched.switch_no) == (CityCode.MOSCOW, 1)
    assert switched.joined_at == NOW + TEAM_LOCK


def test_switching_after_the_lock_still_needs_the_target_unlocked() -> None:
    user_id = uuid4()
    team = TeamMembership(user_id, CityCode.TOKYO, 0, NOW)

    with pytest.raises(TeamChangeError) as caught:
        change_team(user_id, team, CityCode.MOSCOW, 4, NOW + timedelta(days=60))
    assert caught.value.reason is TeamChangeRefusal.FLAVOR_NOT_UNLOCKED


def test_a_switch_starts_a_new_lock_and_going_back_is_allowed_later() -> None:
    user_id = uuid4()
    team = TeamMembership(user_id, CityCode.TOKYO, 0, NOW)
    team = change_team(user_id, team, CityCode.MOSCOW, 5, NOW + TEAM_LOCK)

    with pytest.raises(TeamChangeError) as caught:
        change_team(
            user_id, team, CityCode.TOKYO, 5, NOW + TEAM_LOCK + timedelta(days=1)
        )
    assert caught.value.reason is TeamChangeRefusal.TEAM_LOCKED

    back = change_team(user_id, team, CityCode.TOKYO, 5, NOW + 2 * TEAM_LOCK)
    assert (back.flavor, back.switch_no) == (CityCode.TOKYO, 2)


def test_choosing_the_current_team_is_refused() -> None:
    user_id = uuid4()
    team = TeamMembership(user_id, CityCode.TOKYO, 0, NOW)

    with pytest.raises(TeamChangeError) as caught:
        change_team(user_id, team, CityCode.TOKYO, 50, NOW + 2 * TEAM_LOCK)
    assert caught.value.reason is TeamChangeRefusal.SAME_TEAM
