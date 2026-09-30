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


async def test_model_tier_cache_multipliers_roundtrip(app: FastAPI) -> None:
    from decimal import Decimal

    from app.models import ModelTier

    database = app.state.database
    async with database.session() as session:
        session.add(
            ModelTier(
                alias="cache-test",
                display_name="Cache Test",
                upstream_model_id="model-x",
                upstream_provider_name="provider",
                input_credits_per_1k_tokens=Decimal("1.0"),
                output_credits_per_1k_tokens=Decimal("2.0"),
                cache_read_multiplier=Decimal("0.1"),
                cache_write_multiplier=Decimal("1.25"),
                max_output_tokens=1024,
                context_window=128000,
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(
            select(ModelTier).where(ModelTier.alias == "cache-test")
        )
        assert loaded is not None
        assert loaded.cache_read_multiplier == Decimal("0.1")
        assert loaded.cache_write_multiplier == Decimal("1.25")


async def test_model_tier_cache_multipliers_default_neutral(app: FastAPI) -> None:
    from decimal import Decimal

    from app.models import ModelTier

    database = app.state.database
    async with database.session() as session:
        session.add(
            ModelTier(
                alias="cache-default",
                display_name="Cache Default",
                upstream_model_id="model-y",
                upstream_provider_name="provider",
                input_credits_per_1k_tokens=Decimal("1.0"),
                output_credits_per_1k_tokens=Decimal("2.0"),
                max_output_tokens=1024,
                context_window=128000,
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(
            select(ModelTier).where(ModelTier.alias == "cache-default")
        )
        assert loaded is not None
        assert loaded.cache_read_multiplier == Decimal("1.0")
        assert loaded.cache_write_multiplier == Decimal("1.0")


async def test_plan_budget_fields_roundtrip(app: FastAPI) -> None:
    from decimal import Decimal

    from app.models import Plan

    database = app.state.database
    async with database.session() as session:
        session.add(
            Plan(
                name="budget-plan",
                monthly_credit_limit=Decimal("1000"),
                max_output_tokens_per_request=2048,
                requests_per_minute=60,
                max_credits_per_request=Decimal("50"),
                max_credits_per_window=Decimal("200"),
                budget_window_seconds=600,
                allowed_tier_aliases=["fast"],
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(select(Plan).where(Plan.name == "budget-plan"))
        assert loaded is not None
        assert loaded.max_credits_per_request == Decimal("50")
        assert loaded.max_credits_per_window == Decimal("200")
        assert loaded.budget_window_seconds == 600


async def test_plan_budget_fields_default_unlimited(app: FastAPI) -> None:
    from decimal import Decimal

    from app.models import Plan

    database = app.state.database
    async with database.session() as session:
        session.add(
            Plan(
                name="no-budget-plan",
                monthly_credit_limit=Decimal("1000"),
                max_output_tokens_per_request=2048,
                requests_per_minute=60,
                allowed_tier_aliases=["fast"],
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(select(Plan).where(Plan.name == "no-budget-plan"))
        assert loaded is not None
        assert loaded.max_credits_per_request is None
        assert loaded.max_credits_per_window is None
        assert loaded.budget_window_seconds == 300
