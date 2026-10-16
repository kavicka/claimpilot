"""SQLAlchemy models.

Every extracted value keeps its source (document, page, bbox, quote), the model and the prompt
version, so any number in the UI can be traced back to where it came from.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

EMBEDDING_DIM = 1024  # bge-m3

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB}  # noqa: RUF012


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16))  # handler | senior
    password_hash: Mapped[str] = mapped_column(String(256))


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    reference: Mapped[str] = mapped_column(String(32), unique=True)
    policy_id: Mapped[str | None] = mapped_column(String(64))
    product: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    queue: Mapped[str | None] = mapped_column(String(16), index=True)
    claim_type: Mapped[str | None] = mapped_column(String(16))
    straight_through: Mapped[bool] = mapped_column(Boolean, default=False)
    scenario_id: Mapped[str | None] = mapped_column(String(64), index=True)
    error: Mapped[str | None] = mapped_column(Text)
    # Snapshot of what routing looked at, and the payout breakdown with its explanation.
    facts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    assessment: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    core_claim_id: Mapped[str | None] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Optimistic lock: every UPDATE checks and bumps it, so two writers (two handlers, or a
    # handler and the worker) cannot both win; the loser gets StaleDataError. The UI sends the
    # version it showed, so nobody approves a payout they have not seen.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    documents: Mapped[list["Document"]] = relationship(back_populates="claim")

    __mapper_args__ = {"version_id_col": version}  # noqa: RUF012


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    claim_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(256))
    mime_type: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(512))
    problem: Mapped[str | None] = mapped_column(String(200))  # set when it cannot be read
    page_count: Mapped[int | None] = mapped_column(Integer)
    doc_type: Mapped[str | None] = mapped_column(String(32))
    doc_type_confidence: Mapped[float | None] = mapped_column(Float)
    doc_type_method: Mapped[str | None] = mapped_column(String(16))
    language: Mapped[str | None] = mapped_column(String(8))
    needs_vision: Mapped[bool] = mapped_column(Boolean, default=False)

    claim: Mapped[Claim] = relationship(back_populates="documents")


class DocBlock(Base):
    """One text block from the parser: the grounding target for extracted values."""

    __tablename__ = "doc_blocks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    page: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    text_redacted: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    # Why a reader cannot see this text (ingest/hidden_text.py); such blocks never reach a model.
    hidden: Mapped[str | None] = mapped_column(String(16))


class ExtractedField(TimestampMixin, Base):
    __tablename__ = "extracted_fields"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    field: Mapped[str] = mapped_column(String(64))
    value_raw: Mapped[str | None] = mapped_column(Text)
    value_norm: Mapped[str | None] = mapped_column(Text)
    source_quote: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    grounded: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    checks: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    method: Mapped[str] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(64))
    corrected: Mapped[bool] = mapped_column(Boolean, default=False)


class Correction(TimestampMixin, Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    field_id: Mapped[int] = mapped_column(ForeignKey("extracted_fields.id", ondelete="CASCADE"))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))


class RoutingDecision(TimestampMixin, Base):
    __tablename__ = "routing_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    queue: Mapped[str] = mapped_column(String(16))
    rule_hits: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    rationale: Mapped[str | None] = mapped_column(Text)


class CoverageDecision(TimestampMixin, Base):
    __tablename__ = "coverage_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    item_ref: Mapped[str] = mapped_column(String(64))
    item_description: Mapped[str] = mapped_column(Text)
    coverage: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str] = mapped_column(String(16))
    clause_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    # None when the document's amount or currency could not be read (the item needs review)
    claimed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    claimed_currency: Mapped[str | None] = mapped_column(String(3))
    payout_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    deductible_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    rationale: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class Summary(TimestampMixin, Base):
    __tablename__ = "summaries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))  # handler | client_letter | group | info_request
    language: Mapped[str] = mapped_column(String(2))
    text: Mapped[str] = mapped_column(Text)
    fact_violations: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    model: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(64))


class PipelineStepRun(Base):
    __tablename__ = "pipeline_steps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # running | ok | error
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[Decimal] = mapped_column(Numeric(10, 5), default=Decimal(0))
    models: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)


class AuditLog(TimestampMixin, Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class VaultEntry(TimestampMixin, Base):
    """Encrypted PII values behind the tokens the models see. Lives in its own schema."""

    __tablename__ = "vault"
    __table_args__ = ({"schema": "pii"},)

    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary)


class PolicyChunk(Base):
    """One paragraph (odsek) of the policy terms (VPP): the coverage RAG index."""

    __tablename__ = "policy_chunks"
    __table_args__ = (
        Index("ix_policy_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_policy_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    clause_id: Mapped[str] = mapped_column(String(32), unique=True)
    products: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    article: Mapped[int] = mapped_column(Integer)
    paragraph: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(256))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    tsv: Mapped[str | None] = mapped_column(TSVECTOR)
