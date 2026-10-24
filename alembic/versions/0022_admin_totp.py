"""Admin TOTP second factor (docs/launch-reports/2026-10-23-handoff.md
decision 8; docs/SECURITY.md T13; ADR-0013).

``users`` gains two nullable columns: ``totp_secret_encrypted`` (the
Fernet-encrypted base32 secret, NULL until enrollment starts) and
``totp_confirmed_at`` (NULL until the admin proves they can generate a real
code). The CHECK constraint mirrors the application invariant that an
unconfirmed secret is "pending" and must never gate a login.

Additive only: no existing row changes shape, no lock-worthy backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022_admin_totp"
down_revision: str | None = "0021_mini_game_challenges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_secret_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("totp_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_totp_confirmed_requires_secret",
        "users",
        "totp_confirmed_at IS NULL OR totp_secret_encrypted IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_totp_confirmed_requires_secret", "users", type_="check"
    )
    op.drop_column("users", "totp_confirmed_at")
    op.drop_column("users", "totp_secret_encrypted")
