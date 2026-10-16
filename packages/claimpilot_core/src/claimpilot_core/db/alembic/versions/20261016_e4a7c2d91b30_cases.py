"""cases: claims become one kind of case; generic tables point at cases

Revision ID: e4a7c2d91b30
Revises: c3f81a2e9d10
Create Date: 2026-10-16 18:00:00.000000

Joined-table inheritance (ADR-013): `cases` holds what the pipeline and the review screens need
for any kind (reference, status, queue, lock version); `claims` keeps the claim-only columns and
shares the primary key; `invoices` starts empty and gets its columns in later stages. Documents, extracted fields, step runs, the audit log and the vault move
from claim_id to case_id. A claim's case id is its old claim id, so no row changes its key.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4a7c2d91b30"
down_revision: str | None = "c3f81a2e9d10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# table -> ON DELETE of its link to the case
_GENERIC = {
    "documents": "CASCADE",
    "extracted_fields": "CASCADE",
    "pipeline_steps": "CASCADE",
    "audit_log": "SET NULL",
}
_INDEXED = ["extracted_fields", "pipeline_steps", "audit_log"]
_MOVED = [
    "reference",
    "status",
    "queue",
    "scenario_id",
    "error",
    "created_at",
    "updated_at",
    "version",
]


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("reference", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("queue", sa.String(length=16), nullable=True),
        sa.Column("scenario_id", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cases")),
        sa.UniqueConstraint("reference", name=op.f("uq_cases_reference")),
    )
    for col in ("kind", "queue", "scenario_id", "status"):
        op.create_index(op.f(f"ix_cases_{col}"), "cases", [col], unique=False)
    op.execute(
        "INSERT INTO cases (id, kind, reference, status, queue, scenario_id, error, created_at, "
        "updated_at, version) SELECT id, 'claim', reference, status, queue, scenario_id, error, "
        "created_at, updated_at, version FROM claims"
    )

    for table, ondelete in _GENERIC.items():
        op.drop_constraint(f"fk_{table}_claim_id_claims", table, type_="foreignkey")
        op.alter_column(table, "claim_id", new_column_name="case_id")
        op.create_foreign_key(
            op.f(f"fk_{table}_case_id_cases"),
            table,
            "cases",
            ["case_id"],
            ["id"],
            ondelete=ondelete,
        )
    for table in _INDEXED:
        op.execute(f"ALTER INDEX ix_{table}_claim_id RENAME TO ix_{table}_case_id")
    op.alter_column("vault", "claim_id", new_column_name="case_id", schema="pii")

    for col in ("queue", "scenario_id", "status"):
        op.drop_index(f"ix_claims_{col}", table_name="claims")
    op.drop_constraint("uq_claims_reference", "claims", type_="unique")
    for col in _MOVED:
        op.drop_column("claims", col)
    op.create_foreign_key(
        op.f("fk_claims_id_cases"), "claims", "cases", ["id"], ["id"], ondelete="CASCADE"
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["id"], ["cases.id"], name=op.f("fk_invoices_id_cases"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
    )


def downgrade() -> None:
    # Invoices have no place in the old schema.
    op.execute("DELETE FROM cases WHERE kind <> 'claim'")
    op.drop_table("invoices")
    op.drop_constraint("fk_claims_id_cases", "claims", type_="foreignkey")
    op.add_column("claims", sa.Column("reference", sa.String(length=32), nullable=True))
    op.add_column("claims", sa.Column("status", sa.String(length=16), nullable=True))
    op.add_column("claims", sa.Column("queue", sa.String(length=16), nullable=True))
    op.add_column("claims", sa.Column("scenario_id", sa.String(length=64), nullable=True))
    op.add_column("claims", sa.Column("error", sa.Text(), nullable=True))
    for col in ("created_at", "updated_at"):
        op.add_column(
            "claims",
            sa.Column(col, sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
    op.add_column("claims", sa.Column("version", sa.Integer(), server_default="1"))
    op.execute(
        "UPDATE claims SET (reference, status, queue, scenario_id, error, created_at, updated_at, "
        "version) = (SELECT reference, status, queue, scenario_id, error, created_at, updated_at, "
        "version FROM cases WHERE cases.id = claims.id)"
    )
    for col in ("reference", "status", "created_at", "updated_at", "version"):
        op.alter_column("claims", col, nullable=False)
    op.create_unique_constraint("uq_claims_reference", "claims", ["reference"])
    for col in ("queue", "scenario_id", "status"):
        op.create_index(f"ix_claims_{col}", "claims", [col], unique=False)

    op.alter_column("vault", "case_id", new_column_name="claim_id", schema="pii")
    for table in _INDEXED:
        op.execute(f"ALTER INDEX ix_{table}_case_id RENAME TO ix_{table}_claim_id")
    for table, ondelete in _GENERIC.items():
        op.drop_constraint(f"fk_{table}_case_id_cases", table, type_="foreignkey")
        op.alter_column(table, "case_id", new_column_name="claim_id")
        op.create_foreign_key(
            f"fk_{table}_claim_id_claims", table, "claims", ["claim_id"], ["id"], ondelete=ondelete
        )
    op.drop_table("cases")
