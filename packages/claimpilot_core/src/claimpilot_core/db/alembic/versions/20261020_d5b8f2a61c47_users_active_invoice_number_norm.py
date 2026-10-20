"""users.active; invoices.invoice_number_norm with an index for duplicate detection

Both columns are safe for code that does not know them: `active` defaults to true in the database,
`invoice_number_norm` is nullable.

Revision ID: d5b8f2a61c47
Revises: a7d2e9c41f53
Create Date: 2026-10-20 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5b8f2a61c47"
down_revision: str | None = "a7d2e9c41f53"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _norm(value: str | None) -> str | None:
    # The same rule as claimpilot_core.identifiers.normalize_invoice_number, copied so the
    # migration does not change when the application code does.
    return "".join(ch for ch in (value or "").upper() if ch.isalnum()) or None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    op.add_column("invoices", sa.Column("invoice_number_norm", sa.String(length=40), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, invoice_number FROM invoices WHERE invoice_number IS NOT NULL")
    ).all()
    for invoice_id, number in rows:
        bind.execute(
            sa.text("UPDATE invoices SET invoice_number_norm = :n WHERE id = :id"),
            {"n": _norm(number), "id": invoice_id},
        )
    op.create_index(
        "ix_invoices_supplier_number_norm", "invoices", ["supplier_ico", "invoice_number_norm"]
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_supplier_number_norm", table_name="invoices")
    op.drop_column("invoices", "invoice_number_norm")
    op.drop_column("users", "active")
