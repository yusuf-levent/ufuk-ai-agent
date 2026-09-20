from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.db import Database
from app.errors import ApiError, api_error_handler, error_body
from app.logging import configure_logging
from app.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.routers import admin, auth, gateway, health, me, plans, privacy, usage
from app.services.circuit_breaker import CircuitBreaker
from app.services.email import ConsoleEmailSender
from app.services.upstream import UpstreamClient

logger = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.redis.aclose()
        await app.state.database.aclose()
        await app.state.upstream.aclose()

    app = FastAPI(title="Evren Agent Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.database = Database(settings)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.email_sender = ConsoleEmailSender()
    app.state.upstream = UpstreamClient(settings)
    app.state.circuit_breaker = CircuitBreaker()

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.request_max_body_bytes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.environment == "prod")

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(me.router)
    app.include_router(plans.router)
    app.include_router(admin.router)
    app.include_router(gateway.router)
    app.include_router(usage.router)
    app.include_router(privacy.router)

    app.add_exception_handler(ApiError, api_error_handler)  # type: ignore[arg-type]

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500, content=error_body("Internal server error", "server_error")
        )

    return app


app = create_app()
