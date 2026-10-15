"""Profile + teams (P1): avatars catalogue, location city, team history.

Revision ID: 0014_profile_teams
Revises: 0013_economy_core

* ``avatars``: the server-side avatar catalogue (slug id, image URL,
  ``locked`` for avatars unlocked later, ``unlock_rule`` free text until
  unlocks exist, ``sort``, ``active``). No rows seeded: avatars are data,
  added in /admin, same as venues (0010) and reward rules (0013).
* ``users.avatar_id``: FK to ``avatars`` with ON DELETE SET NULL, so
  removing an avatar clears the pick instead of failing.
* ``users.location_city``: the player's real home city (tehran, ahvaz, ...),
  never a flavor. No CHECK, same as ``venues.city``: the application
  validates it against ``SUPPORTED_CITY_IDS``.
* ``team_memberships``: flavor team history (app/domain/teams.py), one row
  per join or switch. ``UNIQUE (user_id, switch_no)`` is the race guard:
  two concurrent team changes of one player cannot both commit. Its index
  also serves "current team = highest switch_no for this user". The
  ``flavor`` CHECK lists the seven printed flavors, which are frozen.

Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_profile_teams"
down_revision: str | None = "0013_economy_core"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "avatars",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unlock_rule", sa.String(length=200), nullable=True),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column("users", sa.Column("avatar_id", sa.String(length=40), nullable=True))
    op.create_foreign_key(
        "fk_users_avatar_id",
        "users",
        "avatars",
        ["avatar_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "users", sa.Column("location_city", sa.String(length=40), nullable=True)
    )

    op.create_table(
        "team_memberships",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("flavor", sa.String(length=2), nullable=False),
        sa.Column("switch_no", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "switch_no", name="uq_team_memberships_user_switch"
        ),
        sa.CheckConstraint("switch_no >= 0", name="ck_team_memberships_switch_no"),
        sa.CheckConstraint(
            "flavor IN ('PR', 'BE', 'PA', 'ME', 'MA', 'TO', 'MO')",
            name="ck_team_memberships_flavor",
        ),
    )


def downgrade() -> None:
    op.drop_table("team_memberships")
    op.drop_column("users", "location_city")
    op.drop_constraint("fk_users_avatar_id", "users", type_="foreignkey")
    op.drop_column("users", "avatar_id")
    op.drop_table("avatars")
