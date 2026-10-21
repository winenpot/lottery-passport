"""Two challenge kinds from data that already exists (W12): ``first_mini_game``
and ``tap_reflex_fast``, both read from ``mini_game_runs`` (G1, migration 0017).

Revision ID: 0021_mini_game_challenges
Revises: 0020_legal_documents

* ``challenges.kind`` CHECK widens to add ``first_mini_game`` (once, any
  ACCEPTED mini-game run) and ``tap_reflex_fast`` (period, an ACCEPTED
  ``tap_reflex`` run under a fixed reaction-time threshold --
  ``app.domain.challenges.TAP_REFLEX_FAST_THRESHOLD_MS``, not a column).
  No new table: progress is computed from ``mini_game_runs`` directly, the
  same no-passive-tracking principle as ``distinct_flavors``.

Additive only: the CHECK widen only ADDS an allowed value, nothing already
stored becomes invalid.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_mini_game_challenges"
down_revision: str | None = "0020_legal_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KIND_CHECK = "kind IN ('team_choice', 'distinct_flavors', 'daily_checkin')"
_NEW_KIND_CHECK = (
    "kind IN ('team_choice', 'distinct_flavors', 'daily_checkin', "
    "'first_mini_game', 'tap_reflex_fast')"
)


def upgrade() -> None:
    op.drop_constraint("ck_challenges_kind", "challenges", type_="check")
    op.create_check_constraint("ck_challenges_kind", "challenges", _NEW_KIND_CHECK)


def downgrade() -> None:
    op.drop_constraint("ck_challenges_kind", "challenges", type_="check")
    op.create_check_constraint("ck_challenges_kind", "challenges", _OLD_KIND_CHECK)
