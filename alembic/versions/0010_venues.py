"""Venues (partner lounges) and a player's home lounge (B16).

Revision ID: 0010_venues
Revises: 0009_user_profile

* ``venues.id`` is a short stable slug (``parsa``), the id the API exposes.
* ``public_ip`` is optional, for the later "is the scan from a lounge" check.
* ``users.home_venue_id`` is the lounge the player picked in profile setup;
  deactivating or renaming a venue never loses it. Deleting a venue row
  clears the pick instead of failing (ON DELETE SET NULL).

Additive only. No rows are seeded here: the real lounges are data, added
with ``scripts.venues add`` (or the admin panel).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010_venues"
down_revision: str | None = "0009_user_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "venues",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("city", sa.String(length=40), nullable=False),
        sa.Column("public_ip", sa.String(length=45), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "users", sa.Column("home_venue_id", sa.String(length=40), nullable=True)
    )
    op.create_foreign_key(
        "fk_users_home_venue_id",
        "users",
        "venues",
        ["home_venue_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_home_venue_id", "users", type_="foreignkey")
    op.drop_column("users", "home_venue_id")
    op.drop_table("venues")
