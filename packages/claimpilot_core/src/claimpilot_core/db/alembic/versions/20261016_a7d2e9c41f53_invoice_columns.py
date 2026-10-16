"""invoices: the keys validation and matching use, their results, the ERP export

Revision ID: a7d2e9c41f53
Revises: f19b3c7d2e84
Create Date: 2026-10-16 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7d2e9c41f53"
down_revision: str | None = "f19b3c7d2e84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("doc_kind", sa.String(length=16), nullable=True))
    op.add_column("invoices", sa.Column("invoice_number", sa.String(length=40), nullable=True))
    op.add_column("invoices", sa.Column("supplier_ico", sa.String(length=16), nullable=True))
    op.add_column("invoices", sa.Column("supplier_vat_id", sa.String(length=20), nullable=True))
    op.add_column("invoices", sa.Column("total", sa.Numeric(14, 2), nullable=True))
    op.add_column("invoices", sa.Column("currency", sa.String(length=3), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("matching", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "invoices",
        sa.Column("routing", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("invoices", sa.Column("erp_id", sa.String(length=32), nullable=True))
    op.add_column(
        "invoices",
        sa.Column("export", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(op.f("ix_invoices_invoice_number"), "invoices", ["invoice_number"])
    op.execute("CREATE SEQUENCE invoice_reference_seq")  # FA-2026-000001
    op.execute(
        "SELECT setval('invoice_reference_seq', COALESCE((SELECT max(CAST(substring(reference "
        "FROM '[0-9]+$') AS integer)) FROM cases WHERE reference LIKE 'FA-%'), 0) + 1, false)"
    )
    op.create_index(op.f("ix_invoices_supplier_ico"), "invoices", ["supplier_ico"])


def downgrade() -> None:
    op.execute("DROP SEQUENCE invoice_reference_seq")
    op.drop_index(op.f("ix_invoices_supplier_ico"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_invoice_number"), table_name="invoices")
    for col in (
        "export",
        "erp_id",
        "routing",
        "matching",
        "validation", "currency", "total", "supplier_vat_id", "supplier_ico", "invoice_number",
        "doc_kind",
    ):  # fmt: skip
        op.drop_column("invoices", col)
