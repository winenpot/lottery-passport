"""Daily check-in + achievements (C1 extension / AC1 MVP slice).

Revision ID: 0016_checkin_achievements
Revises: 0015_challenges

* ``challenges.kind`` CHECK widens to include ``daily_checkin``: the
  check-in challenge supersedes the sheet's "5-day login"/"5-day activity"
  items (vault Decisions 2026-10-15) -- the player's own daily-checkin
  claim IS the login signal, no new tracking table needed.
* ``achievements``: admin-tunable achievement catalogue (id slug, fact,
  threshold, reward_coins, active). No rows seeded -- same empty-start
  pattern as challenges/avatars/reward_rules. ``fact`` is restricted by
  CHECK to the one this backend can check today (``checkin_streak``).
* ``user_achievements``: one row per player per achievement ever unlocked.
  ``UNIQUE (achievement_id, user_id)`` is the only-once guard, the same
  shape as ``challenge_claims``. ``achievement_id`` is ON DELETE RESTRICT:
  an achievement with unlock history cannot be deleted.

Additive only: the CHECK widen only ADDS an allowed value, nothing already
stored becomes invalid.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016_checkin_achievements"
down_revision: str | None = "0015_challenges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KIND_CHECK = "kind IN ('team_choice', 'distinct_flavors')"
_NEW_KIND_CHECK = "kind IN ('team_choice', 'distinct_flavors', 'daily_checkin')"


def upgrade() -> None:
    op.drop_constraint("ck_challenges_kind", "challenges", type_="check")
    op.create_check_constraint("ck_challenges_kind", "challenges", _NEW_KIND_CHECK)

    op.create_table(
        "achievements",
        sa.Column("id", sa.String(length=60), primary_key=True),
        sa.Column("fact", sa.String(length=30), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("reward_coins", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("threshold > 0", name="ck_achievements_threshold_positive"),
        sa.CheckConstraint(
            "reward_coins >= 0", name="ck_achievements_reward_coins_non_negative"
        ),
        sa.CheckConstraint("fact IN ('checkin_streak')", name="ck_achievements_fact"),
    )
    op.create_table(
        "user_achievements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "achievement_id",
            sa.String(length=60),
            sa.ForeignKey("achievements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "achievement_id",
            "user_id",
            name="uq_user_achievements_achievement_user",
        ),
    )
    op.create_index("ix_user_achievements_user", "user_achievements", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_achievements_user", table_name="user_achievements")
    op.drop_table("user_achievements")
    op.drop_table("achievements")
    op.drop_constraint("ck_challenges_kind", "challenges", type_="check")
    op.create_check_constraint("ck_challenges_kind", "challenges", _OLD_KIND_CHECK)
