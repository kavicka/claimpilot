"""hardening: claim version, reference sequence, document problems

Revision ID: b7e2d4c19a05
Revises: a41c0e9d2b7f
Create Date: 2026-10-10 03:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2d4c19a05"
down_revision: str | None = "a41c0e9d2b7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Optimistic lock for concurrent handler and worker writes.
    op.add_column("claims", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    # References came from count(*) + 1, which repeats after an erasure or under concurrent uploads.
    op.execute("CREATE SEQUENCE claim_reference_seq")
    op.execute(
        "SELECT setval('claim_reference_seq', COALESCE((SELECT max(CAST(substring(reference "
        "FROM '[0-9]+$') AS integer)) FROM claims), 0) + 1, false)"
    )
    # Why a document could not be read (password, damaged, no pages, too many pages).
    op.add_column("documents", sa.Column("problem", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "problem")
    op.execute("DROP SEQUENCE claim_reference_seq")
    op.drop_column("claims", "version")
