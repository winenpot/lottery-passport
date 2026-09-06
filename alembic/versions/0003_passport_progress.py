"""Create passport progress table.

Revision ID: 0003_passport_progress
Revises: 0002_identity_authentication
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_passport_progress"
down_revision: str | None = "0002_identity_authentication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "passport_progress",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign", sa.String(length=20), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "campaign", name="uq_passport_progress_user_campaign"
        ),
    )
    op.create_index("ix_passport_progress_user_id", "passport_progress", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_passport_progress_user_id", table_name="passport_progress")
    op.drop_table("passport_progress")
