"""ClaimPilot API: uploads, claims, review actions. It stores files and enqueues jobs; every
model call happens in the worker."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from claimpilot_api.auth import Intake, User_, ensure_demo_users
from claimpilot_api.invoices import router as invoices_router
from claimpilot_api.limits import enforce_rate_limit, reject_oversized, store_and_commit
from claimpilot_api.ready import router as ready_router
from claimpilot_api.retention import router as retention_router
from claimpilot_api.review import enqueue
from claimpilot_api.review import router as review_router
from claimpilot_core.db.models import Claim, Document, Invoice, PipelineStepRun
from claimpilot_core.db.session import get_engine, get_sessionmaker
from claimpilot_core.domain import ClaimStatus, InvoiceStatus
from claimpilot_core.settings import get_settings

ALLOWED = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.arq = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    async with get_sessionmaker()() as session:
        await ensure_demo_users(session)
        await session.commit()
    yield
    await app.state.arq.aclose()


app = FastAPI(title="ClaimPilot API", version="0.1.0", lifespan=lifespan)
app.middleware("http")(reject_oversized)
app.include_router(review_router)
app.include_router(invoices_router)
app.include_router(retention_router)
app.include_router(ready_router)


@app.exception_handler(StaleDataError)
async def concurrent_change(_request: Request, _exc: StaleDataError) -> JSONResponse:
    """Two writers on one claim (two handlers, or a handler and the worker): the second UPDATE
    matches no row because the first one bumped the version. Its whole change is rolled back."""
    return JSONResponse(
        status_code=409,
        content={"detail": "someone else changed the claim at the same time; reload"},
    )


async def db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


Session = Annotated[AsyncSession, Depends(db)]


@app.get("/health")
async def health() -> dict[str, str]:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}


class ClaimOut(BaseModel):
    id: uuid.UUID
    reference: str
    status: str
    queue: str | None
    claim_type: str | None
    scenario_id: str | None
    documents: int


MAX_FILES = 20
# What each accepted type starts with; a PDF may carry a few bytes before its header.
MAGIC = {
    ".pdf": lambda d: b"%PDF-" in d[:1024],
    ".jpg": lambda d: d.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda d: d.startswith(b"\xff\xd8\xff"),
    ".png": lambda d: d.startswith(b"\x89PNG\r\n\x1a\n"),
}
REJECTED_HINTS = {
    ".heic": "HEIC photos from an iPhone are not accepted; export them as JPG",
    ".heif": "HEIF photos are not accepted; export them as JPG",
    ".docx": "Word files are not accepted; save them as PDF",
}


def safe_filename(name: str | None, suffix: str) -> str:
    """The name to show the handler: no directories, no control characters, at most 200 chars."""
    base = Path((name or "").replace("\\", "/")).name
    base = "".join(ch for ch in base if ch.isprintable()).strip() or f"document{suffix}"
    return base if len(base) <= 200 else base[: 200 - len(suffix)] + suffix


@app.post("/api/claims", status_code=201)
async def create_claim(
    request: Request,
    session: Session,
    source: Intake,
    files: Annotated[list[UploadFile], File(description="Claim documents: PDF, JPG or PNG")],
    scenario_id: Annotated[str | None, Form(max_length=64)] = None,
) -> ClaimOut:
    await enforce_rate_limit(request, source)
    if not files:
        raise HTTPException(422, "at least one document is required")
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"at most {MAX_FILES} documents per claim")
    # Check every file before anything is stored, so a bad file leaves nothing behind.
    accepted: list[tuple[str, str, bytes]] = []
    max_mb = get_settings().max_upload_mb
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        shown = safe_filename(upload.filename, suffix)
        if suffix not in ALLOWED:
            hint = REJECTED_HINTS.get(suffix, "only PDF, JPG and PNG are accepted")
            raise HTTPException(415, f"{shown}: {hint}")
        data = await upload.read(max_mb * 1024 * 1024 + 1)
        if len(data) > max_mb * 1024 * 1024:
            raise HTTPException(413, f"{shown}: larger than {max_mb} MB")
        if not data:
            raise HTTPException(422, f"{shown}: the file is empty")
        if not MAGIC[suffix](data):
            raise HTTPException(415, f"{shown}: the content is not a {suffix[1:].upper()} file")
        accepted.append((suffix, shown, data))
    number = await session.scalar(text("SELECT nextval('claim_reference_seq')"))
    claim = Claim(
        reference=f"{get_settings().claim_reference_prefix}{number:06d}",
        status=ClaimStatus.RECEIVED.value,
        scenario_id=scenario_id,
    )
    session.add(claim)
    await session.flush()
    to_store: list[tuple[str, bytes]] = []
    for suffix, shown, data in accepted:
        doc_id = uuid.uuid4()
        relative = f"claims/{claim.id}/{doc_id}{suffix}"
        to_store.append((relative, data))
        session.add(
            Document(
                id=doc_id,
                case_id=claim.id,
                filename=shown,
                mime_type=ALLOWED[suffix],
                sha256=hashlib.sha256(data).hexdigest(),
                storage_path=relative,
            )
        )
    await store_and_commit(session, get_settings().storage_dir, to_store)
    await enqueue(request, claim.id)
    return ClaimOut(
        id=claim.id,
        reference=claim.reference,
        status=claim.status,
        queue=None,
        claim_type=None,
        scenario_id=scenario_id,
        documents=len(accepted),
    )


class InvoiceOut(BaseModel):
    id: uuid.UUID
    reference: str
    status: str


@app.post("/api/invoices", status_code=201)
async def create_invoice(
    request: Request,
    session: Session,
    source: Intake,
    file: Annotated[
        UploadFile, File(description="The invoice, credit note or proforma: PDF, JPG or PNG")
    ],
) -> InvoiceOut:
    """One supplier document per case; its pages are read as one invoice."""
    await enforce_rate_limit(request, source)
    suffix = Path(file.filename or "").suffix.lower()
    shown = safe_filename(file.filename, suffix)
    if suffix not in ALLOWED:
        raise HTTPException(
            415, f"{shown}: {REJECTED_HINTS.get(suffix, 'only PDF, JPG and PNG are accepted')}"
        )
    max_mb = get_settings().max_upload_mb
    data = await file.read(max_mb * 1024 * 1024 + 1)
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"{shown}: larger than {max_mb} MB")
    if not data or not MAGIC[suffix](data):
        raise HTTPException(415, f"{shown}: the content is not a {suffix[1:].upper()} file")
    number = await session.scalar(text("SELECT nextval('invoice_reference_seq')"))
    invoice = Invoice(
        reference=f"{get_settings().invoice_reference_prefix}{number:06d}",
        status=InvoiceStatus.RECEIVED.value,
    )
    session.add(invoice)
    await session.flush()
    doc_id = uuid.uuid4()
    relative = f"invoices/{invoice.id}/{doc_id}{suffix}"
    session.add(
        Document(
            id=doc_id,
            case_id=invoice.id,
            filename=shown,
            mime_type=ALLOWED[suffix],
            sha256=hashlib.sha256(data).hexdigest(),
            storage_path=relative,
        )
    )
    await store_and_commit(session, get_settings().storage_dir, [(relative, data)])
    await enqueue(request, invoice.id)
    return InvoiceOut(id=invoice.id, reference=invoice.reference, status=invoice.status)


@app.get("/api/claims")
async def list_claims(
    session: Session, user: User_, status: str | None = None, queue: str | None = None
) -> list[ClaimOut]:
    q = (
        select(Claim, func.count(Document.id))
        .outerjoin(Document)
        .group_by(Claim.id)
        .order_by(Claim.created_at)
    )
    if status:
        q = q.where(Claim.status == status)
    if queue:
        q = q.where(Claim.queue == queue)
    rows = (await session.execute(q)).all()
    return [
        ClaimOut(
            id=c.id,
            reference=c.reference,
            status=c.status,
            queue=c.queue,
            claim_type=c.claim_type,
            scenario_id=c.scenario_id,
            documents=n,
        )
        for c, n in rows
    ]


@app.get("/api/claims/{claim_id}/steps")
async def claim_steps(claim_id: uuid.UUID, session: Session, user: User_) -> list[dict]:
    rows = await session.scalars(
        select(PipelineStepRun)
        .where(PipelineStepRun.case_id == claim_id)
        .order_by(PipelineStepRun.id)
    )
    return [
        {
            "step": r.step,
            "status": r.status,
            "attempt": r.attempt,
            "latency_ms": r.latency_ms,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "models": r.models,
            "error": r.error,
        }
        for r in rows
    ]
