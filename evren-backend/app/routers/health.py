from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.db import Database

router = APIRouter(tags=["health"])


async def _check_components(request: Request) -> tuple[bool, bool]:
    database: Database = request.app.state.database
    redis: Redis = request.app.state.redis
    try:
        async with database.session() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    try:
        redis_ok = bool(await redis.ping())
    except Exception:
        redis_ok = False
    return db_ok, redis_ok


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    db_ok, redis_ok = await _check_components(request)
    ok = db_ok and redis_ok
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ok" if ok else "degraded",
            "components": {"database": db_ok, "redis": redis_ok},
        },
    )


@router.get("/health/ready")
async def ready(request: Request) -> JSONResponse:
    db_ok, redis_ok = await _check_components(request)
    ok = db_ok and redis_ok
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ready" if ok else "not_ready",
            "components": {"database": db_ok, "redis": redis_ok},
        },
    )
