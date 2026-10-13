from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Webhook Relay", version="0.1.0")


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["webhook-relay"] = "webhook-relay"


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health() -> HealthResponse:
    """Liveness only; database readiness arrives with persistence."""
    return HealthResponse()
