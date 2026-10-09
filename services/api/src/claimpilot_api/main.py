"""ClaimPilot API: uploads, claims, review actions. It stores files and enqueues jobs; every
model call happens in the worker."""

import hashlib
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from claimpilot_api.auth import Intake, User_, ensure_demo_users
from claimpilot_api.review import router as review_router
from claimpilot_core.db.models import Claim, Document, PipelineStepRun
from claimpilot_core.db.session import get_engine, get_sessionmaker
from claimpilot_core.domain import ClaimStatus
from claimpilot_core.settings import get_settings

ALLOWED = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
MAX_BYTES = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.arq = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    async with get_sessionmaker()() as session:
        await ensure_demo_users(session)
        await session.commit()
    yield
    await app.state.arq.aclose()


app = FastAPI(title="ClaimPilot API", version="0.1.0", lifespan=lifespan)
app.include_router(review_router)


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


@app.post("/api/claims", status_code=201)
async def create_claim(
    session: Session,
    source: Intake,
    files: Annotated[list[UploadFile], File(description="Claim documents: PDF, JPG or PNG")],
    scenario_id: Annotated[str | None, Form()] = None,
) -> ClaimOut:
    if not files:
        raise HTTPException(422, "at least one document is required")
    count = await session.scalar(select(func.count()).select_from(Claim)) or 0
    claim = Claim(
        reference=f"CP-2026-{count + 1:06d}",
        status=ClaimStatus.RECEIVED.value,
        scenario_id=scenario_id,
    )
    session.add(claim)
    await session.flush()
    storage = get_settings().storage_dir
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED:
            raise HTTPException(415, f"{upload.filename}: only PDF, JPG and PNG are accepted")
        data = await upload.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, f"{upload.filename}: larger than 20 MB")
        doc_id = uuid.uuid4()
        relative = f"claims/{claim.id}/{doc_id}{suffix}"
        (storage / relative).parent.mkdir(parents=True, exist_ok=True)
        (storage / relative).write_bytes(data)
        session.add(
            Document(
                id=doc_id,
                claim_id=claim.id,
                filename=upload.filename or relative,
                mime_type=ALLOWED[suffix],
                sha256=hashlib.sha256(data).hexdigest(),
                storage_path=relative,
            )
        )
    await session.commit()
    arq: ArqRedis = app.state.arq
    await arq.enqueue_job("advance", str(claim.id))
    return ClaimOut(
        id=claim.id,
        reference=claim.reference,
        status=claim.status,
        queue=None,
        claim_type=None,
        scenario_id=scenario_id,
        documents=len(files),
    )


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
        .where(PipelineStepRun.claim_id == claim_id)
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
