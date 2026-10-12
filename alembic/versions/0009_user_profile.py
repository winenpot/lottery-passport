"""Profile columns on users: nickname and terms consent (B15).

Revision ID: 0009_user_profile
Revises: 0008_user_roles

* ``nickname`` is what players see; ``nickname_key`` is its case/variant-folded
  form with a unique constraint, so ``Ali`` and ``ALI`` are one name. Both are
  NULL until the player picks one (Postgres allows many NULLs under UNIQUE).
* ``terms_version`` / ``terms_accepted_at`` record which terms the player
  accepted and when.

Additive only: ``display_name`` and every other column stay as they are.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_user_profile"
down_revision: str | None = "0008_user_roles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.String(length=32), nullable=True))
    op.add_column(
        "users", sa.Column("nickname_key", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "users", sa.Column("terms_version", sa.String(length=20), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint("uq_users_nickname_key", "users", ["nickname_key"])


def downgrade() -> None:
    op.drop_constraint("uq_users_nickname_key", "users", type_="unique")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_version")
    op.drop_column("users", "nickname_key")
    op.drop_column("users", "nickname")
