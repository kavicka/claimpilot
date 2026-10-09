"""Mock core claims system. Built out in stage 1.6."""

from fastapi import FastAPI

app = FastAPI(title="Core Claims System (mock)", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
