import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from relay.api import router
from relay.database import migration_engine
from relay.security import BodyLimitMiddleware, SecuritySettings


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["webhook-relay"] = "webhook-relay"


async def health() -> HealthResponse:
    """Liveness only; database readiness arrives with persistence."""
    return HealthResponse()


def create_app(engine=None, security=None):
    @asynccontextmanager
    async def lifespan(application):
        owned_engine = engine is None and bool(os.environ.get("RELAY_DB_PASSWORD_FILE"))
        application.state.engine = migration_engine() if owned_engine else engine
        try:
            yield
        finally:
            if owned_engine:
                application.state.engine.dispose()

    application = FastAPI(title="Webhook Relay", version="0.2.0", lifespan=lifespan)
    application.state.security = security or SecuritySettings.from_environment()
    application.add_middleware(BodyLimitMiddleware)
    application.include_router(router)
    application.add_api_route(
        "/api/health", health, response_model=HealthResponse, tags=["health"]
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Validation errors must never echo supplied passwords or cookies.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": item["loc"], "msg": item["msg"], "type": item["type"]}
                    for item in error.errors()
                ]
            },
        )

    @application.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            response.headers["Cache-Control"] = "no-store"
        return response

    return application


app = create_app()
