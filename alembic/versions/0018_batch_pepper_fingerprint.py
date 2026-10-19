"""Pepper guard: record which pepper signed a batch (readiness check).

Revision ID: 0018_batch_pepper_fingerprint
Revises: 0017_mini_game_runs

``code_batches`` gains ``pepper_fingerprint`` (nullable: existing rows and
batches generated without a pepper stay NULL and are never flagged -- see
``app.application.redemption_codes.find_pepper_mismatches``). Written by
``scripts.generate_codes`` from here on. At startup, and on every ``/ready``
poll, the app refuses to serve if an ACTIVE batch's stored fingerprint
differs from the pepper it is running with now: without this, a
misconfigured ``REDEMPTION_CODE_PEPPER`` (wrong value, stale secret,
staging's pepper copied by mistake) would reject every real redemption as
plain ``CODE_INVALID``, indistinguishable from a bad scan, until someone
diagnosed it from support tickets.

Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018_batch_pepper_fingerprint"
down_revision: str | None = "0017_mini_game_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "code_batches",
        sa.Column("pepper_fingerprint", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("code_batches", "pepper_fingerprint")
