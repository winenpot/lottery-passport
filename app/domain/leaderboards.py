"""Leaderboard board definitions (L1): one registry, so a new leaderboard
is one new entry here, not a new service.

Only the mini-games leaderboard exists today (Tap Reflex, the only mini-game
wired to the database -- docs/vault/Decisions.md 2026-10-24). ``BestScore``
is why this is a registry and not a hardcoded comparison: Tap Reflex's score
is a reaction time in milliseconds, where the lowest number wins, but a
future mini-game (points, a combo counter) would want the opposite. Adding
one costs one ``MiniGameBoard`` entry below -- app/application/leaderboards.py
and the SQL reader are both already generic over "which mini_game_id, which
direction counts as best".
"""

from dataclasses import dataclass
from enum import StrEnum

from app.domain.mini_games import MiniGameId

__all__ = ["BestScore", "MINI_GAME_BOARDS", "MiniGameBoard"]


class BestScore(StrEnum):
    LOWEST = "lowest"  # e.g. reaction time: smaller is better
    HIGHEST = "highest"  # e.g. points, a combo counter: larger is better


@dataclass(frozen=True, slots=True)
class MiniGameBoard:
    mini_game_id: MiniGameId
    best: BestScore


MINI_GAME_BOARDS: dict[MiniGameId, MiniGameBoard] = {
    board.mini_game_id: board
    for board in (
        MiniGameBoard(mini_game_id=MiniGameId.TAP_REFLEX, best=BestScore.LOWEST),
    )
}
