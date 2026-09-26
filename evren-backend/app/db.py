from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine = create_async_engine(settings.database_url, pool_pre_ping=True)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    def session(self) -> AsyncSession:
        return self._session_factory()

    async def aclose(self) -> None:
        await self.engine.dispose()


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    async with database.session() as session:
        yield session
