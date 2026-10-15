"""Challenges (C1, B17): automatic rewards computed from existing data.

Revision ID: 0015_challenges
Revises: 0014_profile_teams

* ``challenges``: the admin-tunable challenge catalogue (id slug, kind,
  period, target, reward_coins, active). No rows seeded: a challenge is
  data, added in /admin, same as venues (0010), avatars and reward rules
  (0013/0014). ``kind`` is restricted to the two this backend can check
  progress for today (app/domain/challenges.py); more kinds need a matching
  code path before the CHECK can widen.
* ``challenge_claims``: one row per user per challenge per period claimed.
  ``UNIQUE (challenge_id, user_id, period_key)`` is the idempotent-claim
  guard -- the same shape as ``team_memberships``' ``switch_no`` guard.
  ``challenge_id`` is ON DELETE RESTRICT: a challenge with claim history
  cannot be deleted (the admin panel does not expose delete either).

Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_challenges"
down_revision: str | None = "0014_profile_teams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "challenges",
        sa.Column("id", sa.String(length=60), primary_key=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("period", sa.String(length=10), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("reward_coins", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("target > 0", name="ck_challenges_target_positive"),
        sa.CheckConstraint(
            "reward_coins >= 0", name="ck_challenges_reward_coins_non_negative"
        ),
        sa.CheckConstraint(
            "kind IN ('team_choice', 'distinct_flavors')", name="ck_challenges_kind"
        ),
        sa.CheckConstraint(
            "period IN ('once', 'day', 'week', 'month')", name="ck_challenges_period"
        ),
    )
    op.create_table(
        "challenge_claims",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "challenge_id",
            sa.String(length=60),
            sa.ForeignKey("challenges.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_key", sa.String(length=20), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "challenge_id",
            "user_id",
            "period_key",
            name="uq_challenge_claims_challenge_user_period",
        ),
    )
    op.create_index("ix_challenge_claims_user", "challenge_claims", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_challenge_claims_user", table_name="challenge_claims")
    op.drop_table("challenge_claims")
    op.drop_table("challenges")
