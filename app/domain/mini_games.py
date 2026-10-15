"""Server-verified MINI-games (G1).

Named "mini game" throughout (this module, the migration, the API, JSON
fields) rather than "game": it is our own in-app reaction game, not the
physical arcade machines at the OxinGame lounges (docs/GLOSSARY.md
"Lounge"). If a real-machine integration is ever built it gets its own
clearly separate `RealGame`/`real_game` naming -- never reuse "game" bare.

Only ``TAP_REFLEX`` ships now (the plan's "only Mehdi's 2 mini-games, Tap
Reflex first" -- the second has no agreed mechanic yet, left out of
``MiniGameId`` entirely rather than wired to a guess, same pattern C1 used
for "first game" before this module existed).

A run is issued by the server with its own per-round delays so the client
cannot know in advance when the "react now" signal comes (``open_run``).
The client plays, then reports its measured reaction time per round
(``POST /mini-games/runs/<run_id>/finish``). The server never trusts those
numbers at face value -- a browser game cannot be made cheat-proof, so the
real control is a cheap plausibility check (``assess_plausibility``) plus
small, capped rewards paid only through C1 challenges, never from this
module directly. A run that fails the check is stored FINISHED but
REJECTED: no reward, no exception, just a verdict the caller counts
(3 rejected runs/day -> flag for admin review, service-layer concern).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from random import Random
from uuid import UUID, uuid4


class MiniGameId(StrEnum):
    TAP_REFLEX = "tap_reflex"


ROUNDS_PER_RUN = 5
MIN_ROUND_DELAY_MS = 800
MAX_ROUND_DELAY_MS = 3_000
RUN_TTL = timedelta(minutes=2)
# Below this, it is not a human reaction -- it is a script firing on the
# signal before a person could physically perceive it.
MIN_HUMAN_REACTION_MS = 100


class MiniGameRunStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"  # finished, plausible
    REJECTED = "rejected"  # finished, implausible -- no reward
    EXPIRED = "expired"  # never finished within RUN_TTL


@dataclass(frozen=True, slots=True)
class NewMiniGameRun:
    id: UUID
    user_id: UUID
    mini_game_id: MiniGameId
    round_delays_ms: tuple[int, ...]
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MiniGameRun:
    """A run as stored: adds the fields that only exist once it is open in
    the database (status), read back by the finish/verification path."""

    id: UUID
    user_id: UUID
    mini_game_id: MiniGameId
    round_delays_ms: tuple[int, ...]
    issued_at: datetime
    expires_at: datetime
    status: MiniGameRunStatus


def generate_round_delays(rng: Random, rounds: int = ROUNDS_PER_RUN) -> tuple[int, ...]:
    """Server-chosen per-round delays (ms) before the "react now" signal.

    ``rng`` is injected so tests get determinism; production callers pass a
    process-level ``random.Random()`` (or the stdlib module, which satisfies
    the same ``randint`` interface).
    """
    return tuple(
        rng.randint(MIN_ROUND_DELAY_MS, MAX_ROUND_DELAY_MS) for _ in range(rounds)
    )


def open_run(
    user_id: UUID, mini_game_id: MiniGameId, now: datetime, rng: Random
) -> NewMiniGameRun:
    return NewMiniGameRun(
        id=uuid4(),
        user_id=user_id,
        mini_game_id=mini_game_id,
        round_delays_ms=generate_round_delays(rng),
        issued_at=now,
        expires_at=now + RUN_TTL,
    )


class MiniGameRunRefusal(StrEnum):
    """Structural problems with a finish request -- real API errors, as
    opposed to ``MiniGameRunRejection`` below (a plausibility verdict, not
    an error)."""

    NOT_FOUND = "not_found"
    NOT_OWNER = "not_owner"
    ALREADY_FINISHED = "already_finished"
    EXPIRED = "expired"
    ROUND_COUNT_MISMATCH = "round_count_mismatch"


class MiniGameRunError(Exception):
    def __init__(self, reason: MiniGameRunRefusal) -> None:
        super().__init__(reason.value)
        self.reason = reason


def check_can_finish(
    run: MiniGameRun, user_id: UUID, reactions_ms: Sequence[int], now: datetime
) -> None:
    """Raises ``MiniGameRunError`` for anything that is not a legitimate
    attempt to finish THIS run. Does not judge plausibility -- call
    ``assess_plausibility`` next once this passes."""
    if run.user_id != user_id:
        raise MiniGameRunError(MiniGameRunRefusal.NOT_OWNER)
    if run.status is not MiniGameRunStatus.OPEN:
        raise MiniGameRunError(MiniGameRunRefusal.ALREADY_FINISHED)
    if now > run.expires_at:
        raise MiniGameRunError(MiniGameRunRefusal.EXPIRED)
    if len(reactions_ms) != len(run.round_delays_ms):
        raise MiniGameRunError(MiniGameRunRefusal.ROUND_COUNT_MISMATCH)


class MiniGameRunRejection(StrEnum):
    """Why a plausibility check failed. Not an exception: a rejected run is
    still a normal (finished, unpaid) outcome, never a 4xx."""

    REACTION_TOO_FAST = "reaction_too_fast"
    IDENTICAL_REACTIONS = "identical_reactions"
    WALL_TIME_TOO_SHORT = "wall_time_too_short"


@dataclass(frozen=True, slots=True)
class MiniGameRunAssessment:
    plausible: bool
    reason: MiniGameRunRejection | None
    average_reaction_ms: float


def assess_plausibility(
    round_delays_ms: Sequence[int],
    reactions_ms: Sequence[int],
    issued_at: datetime,
    finished_at: datetime,
) -> MiniGameRunAssessment:
    """Judges a finish attempt that already passed ``check_can_finish``
    (same round count). Three independent, cheap checks:

    * every reaction is at or above the human floor;
    * reactions are not all identical (a replayed/scripted constant);
    * the wall-clock time the SERVER measured between issuing the run and
      this finish call is at least the sum of the server's own delays plus
      the reported reactions -- a client that skips the waiting and submits
      canned numbers immediately cannot satisfy this.
    """
    average = sum(reactions_ms) / len(reactions_ms)
    if any(reaction < MIN_HUMAN_REACTION_MS for reaction in reactions_ms):
        return MiniGameRunAssessment(
            False, MiniGameRunRejection.REACTION_TOO_FAST, average
        )
    if len(set(reactions_ms)) == 1:
        return MiniGameRunAssessment(
            False, MiniGameRunRejection.IDENTICAL_REACTIONS, average
        )
    wall_time_ms = (finished_at - issued_at) / timedelta(milliseconds=1)
    required_ms = sum(round_delays_ms) + sum(reactions_ms)
    if wall_time_ms < required_ms:
        return MiniGameRunAssessment(
            False, MiniGameRunRejection.WALL_TIME_TOO_SHORT, average
        )
    return MiniGameRunAssessment(True, None, average)
