"""Mini-games (G1, B17-adjacent): starting and finishing a Tap Reflex run.

Opening and finishing a run both lock the player's wallet row first, the
same per-user serialization ``RedemptionService``/``TeamService``/
``ChallengeService`` use -- not because this moves coins directly (it
never does: rewards pay only through C1 challenges), but because it keeps
"is there already an open run" and "is this run still open" checks from
racing another request from the same player.

Rate limiting (decision, 2026-10-15): no dedicated per-user run-creation
counter. The existing global ``RateLimitMiddleware`` already bounds
request volume per client, and the database's own partial unique index
(``uq_mini_game_runs_user_open``) means a player can have at most one run
outstanding at a time -- opening a new one requires finishing or
expiring (2 min) the last, which already caps the creation rate without
another moving part. Revisit only if real abuse data says otherwise.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from random import Random
from uuid import UUID
from zoneinfo import ZoneInfo

from app.application.authentication import Clock
from app.application.unit_of_work import UnitOfWork, UnitOfWorkFactory
from app.domain.audit import AuditAction, NewAuditEntry
from app.domain.mini_games import (
    MiniGameId,
    MiniGameRunError,
    MiniGameRunRefusal,
    MiniGameRunRejection,
    MiniGameRunStatus,
    MiniGameStartError,
    MiniGameStartRefusal,
    assess_plausibility,
    check_can_finish,
    open_run,
)
from app.domain.periods import tehran_day_start

__all__ = [
    "MiniGameFinishResult",
    "MiniGameRunError",
    "MiniGameRunRefusal",
    "MiniGameRunRejection",
    "MiniGameService",
    "MiniGameStartError",
    "MiniGameStartRefusal",
    "RunStarted",
]


@dataclass(frozen=True, slots=True)
class RunStarted:
    run_id: UUID
    mini_game_id: MiniGameId
    round_delays_ms: Sequence[int]
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class MiniGameFinishResult:
    run_id: UUID
    accepted: bool
    average_reaction_ms: float
    reason: MiniGameRunRejection | None = None


class MiniGameService:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        clock: Clock,
        zone: ZoneInfo,
        rejected_review_threshold: int = 3,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._zone = zone
        self._rejected_review_threshold = rejected_review_threshold

    async def start_run(self, user_id: UUID, mini_game_id: MiniGameId) -> RunStarted:
        """Raises ``MiniGameStartError`` (ALREADY_OPEN)."""
        now = self._clock.now()
        async with self._unit_of_work() as uow:
            await uow.ledger.lock_wallet(user_id, now)
            if await uow.mini_games.get_open(user_id, mini_game_id) is not None:
                raise MiniGameStartError(MiniGameStartRefusal.ALREADY_OPEN)
            new_run = open_run(user_id, mini_game_id, now, Random())
            await uow.mini_games.open(new_run)
            await uow.commit()
        return RunStarted(
            run_id=new_run.id,
            mini_game_id=mini_game_id,
            round_delays_ms=new_run.round_delays_ms,
            expires_at=new_run.expires_at,
        )

    async def finish_run(
        self, user_id: UUID, run_id: UUID, reactions_ms: Sequence[int]
    ) -> MiniGameFinishResult:
        """Raises ``MiniGameRunError`` for anything structurally wrong with
        the request (unknown run, wrong owner, already finished, expired,
        round-count mismatch). An implausible but structurally valid
        attempt is NOT an error: it returns normally with
        ``accepted=False``."""
        now = self._clock.now()
        async with self._unit_of_work() as uow:
            await uow.ledger.lock_wallet(user_id, now)
            run = await uow.mini_games.get(run_id)
            if run is None:
                raise MiniGameRunError(MiniGameRunRefusal.NOT_FOUND)
            check_can_finish(run, user_id, reactions_ms, now)
            assessment = assess_plausibility(
                run.round_delays_ms, reactions_ms, run.issued_at, now
            )
            status = (
                MiniGameRunStatus.ACCEPTED
                if assessment.plausible
                else MiniGameRunStatus.REJECTED
            )
            await uow.mini_games.finish(
                run.id, status, now, assessment.average_reaction_ms
            )
            if status is MiniGameRunStatus.REJECTED:
                await self._flag_if_abusive(uow, user_id, run.mini_game_id, now)
            await uow.commit()
        return MiniGameFinishResult(
            run_id=run.id,
            accepted=assessment.plausible,
            average_reaction_ms=assessment.average_reaction_ms,
            reason=assessment.reason,
        )

    async def _flag_if_abusive(
        self, uow: UnitOfWork, user_id: UUID, mini_game_id: MiniGameId, now: datetime
    ) -> None:
        since = tehran_day_start(now, self._zone)
        rejected_today = await uow.mini_games.count_rejected_since(user_id, since)
        if rejected_today < self._rejected_review_threshold:
            return
        # The flagged account is also the audit "actor": these are its own
        # runs under suspicion, not an admin-initiated change.
        await uow.audit.record(
            NewAuditEntry(
                actor_user_id=user_id,
                action=AuditAction.CREATE,
                entity="mini_game_run_abuse",
                entity_id=str(user_id),
                created_at=now,
                changes={
                    "mini_game_id": mini_game_id.value,
                    "rejected_today": rejected_today,
                },
            )
        )
