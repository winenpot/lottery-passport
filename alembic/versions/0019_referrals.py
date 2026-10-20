"""Referrals (RF1): a stable per-user code, and who invited whom.

Revision ID: 0019_referrals
Revises: 0018_batch_pepper_fingerprint

``users.referral_code``: unique, nullable (generated lazily on first read,
app/application/referrals.py ``ReferralService.ensure_code``, not backfilled
for existing users by this migration).

``referrals``: one row per invitee, PK on ``invitee_user_id`` (one inviter
per user, enforced structurally, not just by application logic -- a second
``POST``/``PATCH`` bind attempt cannot create a second row). ``CHECK
invitee_user_id <> inviter_user_id`` blocks a self-referral at the database
too, belt-and-suspenders with ``app.domain.referrals.check_can_bind``.

Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_referrals"
down_revision: str | None = "0018_batch_pepper_fingerprint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("referral_code", sa.String(length=8), nullable=True),
    )
    op.create_unique_constraint("uq_users_referral_code", "users", ["referral_code"])
    op.create_table(
        "referrals",
        sa.Column("invitee_user_id", sa.Uuid(), primary_key=True),
        sa.Column("inviter_user_id", sa.Uuid(), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invitee_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["inviter_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "invitee_user_id <> inviter_user_id", name="ck_referrals_no_self"
        ),
    )
    op.create_index("ix_referrals_inviter", "referrals", ["inviter_user_id"])


def downgrade() -> None:
    op.drop_index("ix_referrals_inviter", table_name="referrals")
    op.drop_table("referrals")
    op.drop_constraint("uq_users_referral_code", "users", type_="unique")
    op.drop_column("users", "referral_code")
