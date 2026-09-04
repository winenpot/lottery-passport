"""Create the initial empty schema baseline.

Revision ID: 0001_phase1_foundation
Revises:
"""

from collections.abc import Sequence

revision: str = "0001_phase1_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    return


def downgrade() -> None:
    return
