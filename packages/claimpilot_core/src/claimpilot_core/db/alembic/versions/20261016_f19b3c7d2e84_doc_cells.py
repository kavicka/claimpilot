"""doc_cells: line-item table cells of invoices, each a grounding target

Revision ID: f19b3c7d2e84
Revises: e4a7c2d91b30
Create Date: 2026-10-16 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f19b3c7d2e84"
down_revision: str | None = "e4a7c2d91b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doc_cells",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("tbl", sa.Integer(), nullable=False),
        sa.Column("item", sa.Integer(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("col", sa.Integer(), nullable=False),
        sa.Column("header", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_redacted", sa.Text(), nullable=True),
        sa.Column("bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_doc_cells_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_doc_cells")),
    )
    op.create_index(op.f("ix_doc_cells_document_id"), "doc_cells", ["document_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_doc_cells_document_id"), table_name="doc_cells")
    op.drop_table("doc_cells")
