from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

# Safe test defaults must exist before any app import reads settings.
os.environ.setdefault("UPSTREAM_API_KEY", "test-upstream-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://evren:evren@localhost:5433/evren")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("ENVIRONMENT", "dev")

import pytest
from alembic import command
from alembic.config import Config
from app.main import create_app
from app.models import Base
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def run_migrations() -> None:
    command.upgrade(alembic_config(), "head")


@pytest.fixture(scope="session")
def app() -> FastAPI:
    return create_app()


@pytest.fixture(scope="session")
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest.fixture(autouse=True)
async def clean_tables(app: FastAPI) -> AsyncIterator[None]:
    from app.services.circuit_breaker import CircuitBreaker

    yield
    database = app.state.database
    table_names = ", ".join(reversed(sorted(table.name for table in Base.metadata.sorted_tables)))
    async with database.session() as session:
        await session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        await session.commit()
    await app.state.redis.flushdb()
    app.state.circuit_breaker = CircuitBreaker()
