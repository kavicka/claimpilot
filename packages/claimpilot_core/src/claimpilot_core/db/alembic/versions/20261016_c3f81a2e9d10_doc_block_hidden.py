"""doc_blocks.hidden: text a reader of the document cannot see (prompt-injection defense)

Revision ID: c3f81a2e9d10
Revises: b7e2d4c19a05
Create Date: 2026-10-16 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f81a2e9d10"
down_revision: str | None = "b7e2d4c19a05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Why the text is hidden (low_contrast, tiny, off_page, invisible, transparent, covered).
    op.add_column("doc_blocks", sa.Column("hidden", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("doc_blocks", "hidden")
