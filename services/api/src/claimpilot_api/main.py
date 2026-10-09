"""ClaimPilot API: uploads, claims, review actions. It stores files and enqueues jobs; every
model call happens in the worker."""

from fastapi import FastAPI
from sqlalchemy import text

from claimpilot_core.db.session import get_engine

app = FastAPI(title="ClaimPilot API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
    return {"status": "ok"}
