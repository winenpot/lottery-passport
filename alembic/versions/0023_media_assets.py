"""Admin image upload (W10): ``media_assets``, content-addressed, stored in
Postgres -- no new volume, no new vendor, backed up by L15's `pg_dump`
with no extra step (same as every other table). First caller: the admin
"Images" page; reusable later for badges and prize art
(app/domain/achievements.py's "no badge/image field yet" note).

Revision ID: 0023_media_assets
Revises: 0022_admin_totp

Renumbered from 0022 on 2026-10-25: written on the office machine on 21 Oct
and never pushed, while 0022_admin_totp (laptop, 24 Oct) shipped to staging
and production first. Same table, same SQL; only the chain position moved.

SVG is refused on purpose (app/domain/media.py): an SVG can carry a
<script> tag, so admin image upload would otherwise be a stored-XSS
vector. ``content_type`` and ``byte_size`` are CHECK-enforced; the sha256
primary key makes "upload the same bytes twice" a no-op read, not a
duplicate row.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_media_assets"
down_revision: str | None = "0022_admin_totp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("sha256", sa.String(length=64), primary_key=True),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("bytes", sa.LargeBinary(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "content_type IN ('image/png', 'image/jpeg', 'image/webp')",
            name="ck_media_assets_content_type",
        ),
        sa.CheckConstraint(
            "byte_size > 0 AND byte_size <= 524288", name="ck_media_assets_byte_size"
        ),
    )


def downgrade() -> None:
    op.drop_table("media_assets")
