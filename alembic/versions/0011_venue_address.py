"""Street address of a venue (lounge).

Revision ID: 0011_venue_address
Revises: 0010_venues

Optional, free text in the lounge's own language (Persian), shown next to the
name in the profile picker. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011_venue_address"
down_revision: str | None = "0010_venues"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("venues", sa.Column("address", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("venues", "address")
