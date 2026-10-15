from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domain.passports import CityCode
from app.domain.teams import (
    JOIN_THRESHOLD,
    SwitchRefusal,
    TeamMembership,
    TeamSwitchError,
    next_required,
    should_auto_join,
    switch_team,
    switch_threshold,
)

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def test_thresholds_follow_fibonacci_from_five() -> None:
    assert [switch_threshold(n) for n in range(7)] == [5, 8, 13, 21, 34, 55, 89]


def test_negative_switch_number_is_rejected() -> None:
    with pytest.raises(ValueError):
        switch_threshold(-1)


def test_auto_join_only_without_a_team_and_at_five_codes() -> None:
    user_id = uuid4()
    on_team = TeamMembership(user_id, CityCode.TOKYO, 0, NOW)

    assert not should_auto_join(None, JOIN_THRESHOLD - 1)
    assert should_auto_join(None, JOIN_THRESHOLD)
    assert not should_auto_join(on_team, 100)


def test_walk_join_five_then_switch_eight_then_switch_thirteen() -> None:
    user_id = uuid4()
    assert next_required(None) == 5
    team = TeamMembership(user_id, CityCode.TOKYO, 0, NOW)

    assert next_required(team) == 8
    team = switch_team(team, CityCode.MOSCOW, 8, NOW + timedelta(days=1))
    assert (team.flavor, team.switch_no) == (CityCode.MOSCOW, 1)

    assert next_required(team) == 13
    team = switch_team(team, CityCode.PARIS, 13, NOW + timedelta(days=2))
    assert (team.flavor, team.switch_no, team.user_id) == (CityCode.PARIS, 2, user_id)
    assert team.joined_at == NOW + timedelta(days=2)
    assert next_required(team) == 21


def test_seven_target_codes_are_not_enough_for_the_first_switch() -> None:
    team = TeamMembership(uuid4(), CityCode.TOKYO, 0, NOW)

    with pytest.raises(TeamSwitchError) as caught:
        switch_team(team, CityCode.MOSCOW, 7, NOW)

    assert caught.value.reason is SwitchRefusal.THRESHOLD_NOT_MET
    assert (caught.value.required, caught.value.have) == (8, 7)


def test_switching_needs_a_current_team() -> None:
    with pytest.raises(TeamSwitchError) as caught:
        switch_team(None, CityCode.MOSCOW, 50, NOW)

    assert caught.value.reason is SwitchRefusal.NOT_JOINED


def test_switching_to_the_current_team_is_refused() -> None:
    team = TeamMembership(uuid4(), CityCode.TOKYO, 0, NOW)

    with pytest.raises(TeamSwitchError) as caught:
        switch_team(team, CityCode.TOKYO, 50, NOW)

    assert caught.value.reason is SwitchRefusal.SAME_TEAM
