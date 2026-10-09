"""claimed amount nullable

Revision ID: a41c0e9d2b7f
Revises: 5c920057ed3c
Create Date: 2026-10-09 22:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a41c0e9d2b7f"
down_revision: str | None = "5c920057ed3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # An unreadable amount or currency is stored as unknown, never as 0 or EUR.
    op.alter_column(
        "coverage_decisions",
        "claimed_amount",
        existing_type=sa.Numeric(12, 2),
        nullable=True,
    )
    op.alter_column(
        "coverage_decisions",
        "claimed_currency",
        existing_type=sa.String(length=3),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("UPDATE coverage_decisions SET claimed_amount = 0 WHERE claimed_amount IS NULL")
    op.execute(
        "UPDATE coverage_decisions SET claimed_currency = 'EUR' WHERE claimed_currency IS NULL"
    )
    op.alter_column(
        "coverage_decisions", "claimed_amount", existing_type=sa.Numeric(12, 2), nullable=False
    )
    op.alter_column(
        "coverage_decisions", "claimed_currency", existing_type=sa.String(length=3), nullable=False
    )
