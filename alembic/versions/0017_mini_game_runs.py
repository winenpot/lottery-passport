"""Mini-game runs (G1): server-issued, server-verified Tap Reflex attempts.

Revision ID: 0017_mini_game_runs
Revises: 0016_checkin_achievements

Named "mini game" throughout (table, columns, domain, JSON), not "game":
this is our own in-app reaction mini-game, not the physical arcade machines
at the OxinGame lounges (see docs/GLOSSARY.md "Lounge"). If a real-machine
integration is ever built it gets its own `RealGame`/`real_game` naming,
kept clearly apart from this one.

* ``mini_game_runs``: one row per issued run. ``round_delays_ms`` is the
  server-chosen per-round delay array handed to the client at issue time
  (so the client cannot know the signal timing in advance, but the server
  can re-check the wall-clock math at finish time). ``mini_game_id`` and
  ``status`` are restricted to the closed sets app/domain/mini_games.py
  knows about today (only ``tap_reflex``; only one mini-game ships in G1).
* A partial unique index enforces "one OPEN run per user" as a database
  guarantee, not just an application check -- the same belt-and-suspenders
  pattern as ``team_memberships``' ``switch_no`` guard and
  ``challenge_claims``' period guard: the caller still locks the wallet row
  first to serialize per-user, but a race can never land two open rows.

Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017_mini_game_runs"
down_revision: str | None = "0016_checkin_achievements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mini_game_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mini_game_id", sa.String(length=20), nullable=False),
        sa.Column("round_delays_ms", postgresql.ARRAY(sa.Integer()), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("average_reaction_ms", sa.Float(), nullable=True),
        sa.CheckConstraint(
            "mini_game_id IN ('tap_reflex')", name="ck_mini_game_runs_mini_game_id"
        ),
        sa.CheckConstraint(
            "status IN ('open', 'accepted', 'rejected', 'expired')",
            name="ck_mini_game_runs_status",
        ),
    )
    op.create_index(
        "uq_mini_game_runs_user_open",
        "mini_game_runs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_mini_game_runs_user_status",
        "mini_game_runs",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_mini_game_runs_user_status", table_name="mini_game_runs")
    op.drop_index("uq_mini_game_runs_user_open", table_name="mini_game_runs")
    op.drop_table("mini_game_runs")
