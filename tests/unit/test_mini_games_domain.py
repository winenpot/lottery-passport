from dataclasses import replace
from datetime import UTC, datetime, timedelta
from random import Random
from uuid import uuid4

import pytest

from app.domain.mini_games import (
    MAX_ROUND_DELAY_MS,
    MIN_HUMAN_REACTION_MS,
    MIN_ROUND_DELAY_MS,
    ROUNDS_PER_RUN,
    RUN_TTL,
    MiniGameId,
    MiniGameRun,
    MiniGameRunError,
    MiniGameRunRefusal,
    MiniGameRunRejection,
    MiniGameRunStatus,
    assess_plausibility,
    check_can_finish,
    generate_round_delays,
    open_run,
)

NOW = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


def test_generated_delays_are_within_bounds_and_the_configured_count() -> None:
    delays = generate_round_delays(Random(1))
    assert len(delays) == ROUNDS_PER_RUN
    assert all(MIN_ROUND_DELAY_MS <= delay <= MAX_ROUND_DELAY_MS for delay in delays)


def test_generation_is_deterministic_for_a_seeded_rng() -> None:
    assert generate_round_delays(Random(42)) == generate_round_delays(Random(42))


def test_open_run_sets_issued_and_expiry() -> None:
    user_id = uuid4()
    run = open_run(user_id, MiniGameId.TAP_REFLEX, NOW, Random(1))
    assert run.user_id == user_id
    assert run.mini_game_id is MiniGameId.TAP_REFLEX
    assert run.issued_at == NOW
    assert run.expires_at == NOW + RUN_TTL
    assert len(run.round_delays_ms) == ROUNDS_PER_RUN


def _open_mini_game_run(delays: tuple[int, ...] = (1000, 1000, 1000)) -> MiniGameRun:
    user_id = uuid4()
    return MiniGameRun(
        id=uuid4(),
        user_id=user_id,
        mini_game_id=MiniGameId.TAP_REFLEX,
        round_delays_ms=delays,
        issued_at=NOW,
        expires_at=NOW + RUN_TTL,
        status=MiniGameRunStatus.OPEN,
    )


def test_check_can_finish_rejects_a_different_owner() -> None:
    run = _open_mini_game_run()
    with pytest.raises(MiniGameRunError) as caught:
        check_can_finish(run, uuid4(), [200, 200, 200], NOW)
    assert caught.value.reason is MiniGameRunRefusal.NOT_OWNER


def test_check_can_finish_rejects_a_run_that_is_not_open() -> None:
    run = _open_mini_game_run()
    finished = replace(run, status=MiniGameRunStatus.ACCEPTED)
    with pytest.raises(MiniGameRunError) as caught:
        check_can_finish(finished, finished.user_id, [200, 200, 200], NOW)
    assert caught.value.reason is MiniGameRunRefusal.ALREADY_FINISHED


def test_check_can_finish_rejects_after_expiry() -> None:
    run = _open_mini_game_run()
    with pytest.raises(MiniGameRunError) as caught:
        check_can_finish(
            run, run.user_id, [200, 200, 200], run.expires_at + timedelta(seconds=1)
        )
    assert caught.value.reason is MiniGameRunRefusal.EXPIRED


def test_check_can_finish_rejects_a_round_count_mismatch() -> None:
    run = _open_mini_game_run()
    with pytest.raises(MiniGameRunError) as caught:
        check_can_finish(run, run.user_id, [200, 200], NOW)
    assert caught.value.reason is MiniGameRunRefusal.ROUND_COUNT_MISMATCH


def test_check_can_finish_passes_a_legitimate_attempt() -> None:
    run = _open_mini_game_run()
    check_can_finish(run, run.user_id, [200, 200, 200], NOW + timedelta(seconds=10))


def test_plausible_run_passes_every_check() -> None:
    delays = (1000, 1500, 2000)
    reactions = (250, 300, 275)
    finished_at = NOW + timedelta(milliseconds=sum(delays) + sum(reactions) + 50)
    result = assess_plausibility(delays, reactions, NOW, finished_at)
    assert result.plausible
    assert result.reason is None
    assert result.average_reaction_ms == pytest.approx(275.0)


def test_a_reaction_below_the_human_floor_is_rejected() -> None:
    delays = (1000, 1500, 2000)
    reactions = (MIN_HUMAN_REACTION_MS - 1, 300, 275)
    finished_at = NOW + timedelta(milliseconds=sum(delays) + sum(reactions) + 50)
    result = assess_plausibility(delays, reactions, NOW, finished_at)
    assert not result.plausible
    assert result.reason is MiniGameRunRejection.REACTION_TOO_FAST


def test_identical_reactions_are_rejected_even_if_individually_plausible() -> None:
    delays = (1000, 1500, 2000)
    reactions = (250, 250, 250)
    finished_at = NOW + timedelta(milliseconds=sum(delays) + sum(reactions) + 50)
    result = assess_plausibility(delays, reactions, NOW, finished_at)
    assert not result.plausible
    assert result.reason is MiniGameRunRejection.IDENTICAL_REACTIONS


def test_submitting_immediately_without_waiting_is_rejected() -> None:
    delays = (1000, 1500, 2000)
    reactions = (250, 300, 275)
    # The client claims plausible reactions but the server's own clock says
    # far less wall time passed than the delays + reactions require.
    finished_at = NOW + timedelta(milliseconds=10)
    result = assess_plausibility(delays, reactions, NOW, finished_at)
    assert not result.plausible
    assert result.reason is MiniGameRunRejection.WALL_TIME_TOO_SHORT
