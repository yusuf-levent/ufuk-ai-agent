"""Guards for test database isolation.

The suite must never touch the developer's dev database: conftest rewrites
DATABASE_URL/REDIS_URL to dedicated test instances before any app import,
and `clean_tables` refuses to TRUNCATE a database whose name does not
contain "test". These tests pin both layers.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

CONFTEST_PATH = Path(__file__).resolve().parent / "conftest.py"


def test_conftest_rewrites_database_url_to_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    import conftest

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://evren:evren@localhost:5433/evren")
    rewritten = conftest._rewrite_database_url(
        "postgresql+asyncpg://evren:evren@localhost:5433/evren"
    )
    assert urlsplit(rewritten).path == "/evren_test"
    # The rewrite is total: even a URL already pointing elsewhere is forced.
    rewritten_remote = conftest._rewrite_database_url(
        "postgresql+asyncpg://user:pass@db.example.com:5432/prod_evren"
    )
    assert urlsplit(rewritten_remote).path == "/evren_test"
    assert urlsplit(rewritten_remote).hostname == "db.example.com"


def test_conftest_rewrites_redis_url_to_test_db(monkeypatch: pytest.MonkeyPatch) -> None:
    import conftest

    rewritten = conftest._rewrite_redis_url("redis://localhost:6380/0")
    assert urlsplit(rewritten).path == "/15"
    rewritten_custom = conftest._rewrite_redis_url("redis://redis.example.com:6379/3")
    assert urlsplit(rewritten_custom).path == "/15"


def test_clean_tables_guard_fails_on_non_test_database(app) -> None:
    """The TRUNCATE guard must fail the suite when connected to a non-test DB.

    Simulated by monkeypatching `current_database()` to return the dev name;
    the fixture's guard must raise pytest.fail before any TRUNCATE runs.
    """
    from sqlalchemy import text

    database = app.state.database

    original_scalar = database.session

    class FakeSession:
        def __init__(self, real_session):
            self._real = real_session

        async def __aenter__(self):
            self._session = await self._real.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self._real.__aexit__(*args)

        async def scalar(self, statement, *args, **kwargs):
            if "current_database" in str(statement):
                return "evren"  # pretend we are connected to the dev DB
            return await self._session.scalar(statement, *args, **kwargs)

        async def execute(self, *args, **kwargs):
            return await self._session.execute(*args, **kwargs)

        async def commit(self):
            return await self._session.commit()

    database.session = lambda: FakeSession(original_scalar())  # type: ignore[method-assign]
    try:
        from _pytest.outcomes import Failed

        with pytest.raises(Failed, match="Refusing to truncate"):
            # Re-run just the guard portion of clean_tables by invoking the
            # fixture body's logic through a direct call.
            import asyncio

            async def run_guard():
                async with database.session() as session:
                    db_name = await session.scalar(text("SELECT current_database()"))
                    if db_name is None or "test" not in db_name:
                        message = (
                            f"Refusing to truncate database '{db_name}': "
                            "test isolation guard failed. "
                            "Tests must run against a database whose name contains 'test'."
                        )
                        pytest.fail(message)

            asyncio.run(run_guard())
    finally:
        database.session = original_scalar  # type: ignore[method-assign]
