from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Safe test defaults must exist before any app import reads settings.
os.environ.setdefault("UPSTREAM_API_KEY", "test-upstream-key")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("ENVIRONMENT", "dev")

# ---------------------------------------------------------------------------
# Test database isolation.
#
# Tests MUST run against a dedicated database (evren_test) and a dedicated
# Redis logical DB - never the developer's dev database. The URLs are
# rewritten here (before any app import reads settings) so even a
# misconfigured DATABASE_URL/REDIS_URL in the environment cannot point the
# suite at dev data. `clean_tables` additionally refuses to TRUNCATE unless
# the connected database name contains "test" (defense in depth).
# ---------------------------------------------------------------------------

TEST_DATABASE_NAME = "evren_test"
TEST_REDIS_DB = "15"


def _rewrite_database_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{TEST_DATABASE_NAME}"))


def _rewrite_redis_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{TEST_REDIS_DB}"))


os.environ["DATABASE_URL"] = _rewrite_database_url(
    os.environ.get("DATABASE_URL", "postgresql+asyncpg://evren:evren@localhost:5433/evren")
)
os.environ["REDIS_URL"] = _rewrite_redis_url(
    os.environ.get("REDIS_URL", "redis://localhost:6380/0")
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


async def _ensure_test_database_exists() -> None:
    """Create the test database if it does not exist yet.

    Connects to the maintenance database on the same server (postgres) with
    the same credentials and issues an idempotent CREATE DATABASE.
    """
    settings = get_settings()
    parts = urlsplit(settings.database_url)
    admin_url = urlunsplit(parts._replace(path="/postgres"))
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DATABASE_NAME},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}"'))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def run_migrations() -> None:
    import asyncio

    asyncio.run(_ensure_test_database_exists())
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
    # Defense in depth: never TRUNCATE unless connected to a test database.
    async with database.session() as session:
        db_name = await session.scalar(text("SELECT current_database()"))
        if db_name is None or "test" not in db_name:
            pytest.fail(
                f"Refusing to truncate database '{db_name}': test isolation guard failed. "
                "Tests must run against a database whose name contains 'test'."
            )
        table_names = ", ".join(
            reversed(sorted(table.name for table in Base.metadata.sorted_tables))
        )
        await session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        await session.commit()
    await app.state.redis.flushdb()
    app.state.circuit_breaker = CircuitBreaker()
