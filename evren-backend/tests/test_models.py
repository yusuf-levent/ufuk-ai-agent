from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.models import UsageEvent, User
from app.models.enums import UsageStatus, UserRole
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


async def test_user_roundtrip(app: FastAPI) -> None:
    database = app.state.database
    async with database.session() as session:
        session.add(User(email="user@example.com", password_hash="hash"))
        await session.commit()

    async with database.session() as session:
        result = await session.execute(select(User).where(User.email == "user@example.com"))
        loaded = result.scalar_one()
        assert loaded.role == UserRole.USER
        assert loaded.email_verified is False
        assert loaded.is_active is True
        assert loaded.created_at is not None


async def test_user_email_unique(app: FastAPI) -> None:
    database = app.state.database
    async with database.session() as session:
        session.add(User(email="dup@example.com", password_hash="hash"))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with database.session() as session:
            session.add(User(email="dup@example.com", password_hash="hash2"))
            await session.commit()


def _usage_event(request_id: uuid.UUID) -> UsageEvent:
    return UsageEvent(
        request_id=request_id,
        tier_alias="fast",
        upstream_model_id="some-upstream-model",
        prompt_tokens=100,
        completion_tokens=50,
        credits_charged=Decimal("1.500000"),
        estimated=False,
        status=UsageStatus.SETTLED,
        latency_ms=250,
    )


async def test_usage_event_request_id_unique(app: FastAPI) -> None:
    database = app.state.database
    request_id = uuid.uuid4()
    async with database.session() as session:
        session.add(_usage_event(request_id))
        await session.commit()

    with pytest.raises(IntegrityError):
        async with database.session() as session:
            session.add(_usage_event(request_id))
            await session.commit()
