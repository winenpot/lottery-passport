"""Economy core: ledger ``asset`` column, ``reward_rules`` table (ADR 0010).

Revision ID: 0013_economy_core
Revises: 0012_audit_log

* ``coin_ledger_entries.asset``: ``NOT NULL DEFAULT 'coin'``, so every
  existing row backfills without a data migration step. ``CHECK (asset =
  'coin')`` for now, tightened deliberately: a future diamond currency
  widens this constraint instead of changing the column.
* ``reward_rules``: admin-tunable reward amounts (key, amount, cadence,
  active, note). Additive only, no rows seeded here — same rule as venues
  (migration 0010): a missing row means "use the service's configured
  default", added later via the admin panel.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_economy_core"
down_revision: str | None = "0012_audit_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "coin_ledger_entries",
        sa.Column(
            "asset",
            sa.String(length=20),
            nullable=False,
            server_default="coin",
        ),
    )
    op.create_check_constraint(
        "ck_coin_ledger_entries_asset_coin_only",
        "coin_ledger_entries",
        "asset = 'coin'",
    )

    op.create_table(
        "reward_rules",
        sa.Column("key", sa.String(length=60), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("cadence", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
        sa.CheckConstraint("amount > 0", name="ck_reward_rules_amount_positive"),
        sa.CheckConstraint(
            "cadence IN ('once', 'daily', 'weekly', 'monthly')",
            name="ck_reward_rules_cadence",
        ),
    )


def downgrade() -> None:
    op.drop_table("reward_rules")
    op.drop_constraint(
        "ck_coin_ledger_entries_asset_coin_only",
        "coin_ledger_entries",
        type_="check",
    )
    op.drop_column("coin_ledger_entries", "asset")
