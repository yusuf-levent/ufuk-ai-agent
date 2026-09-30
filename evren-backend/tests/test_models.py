from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.models import CostDailyRollup, UsageEvent, User
from app.models.enums import UsageStatus, UserRole
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from tests.helpers import create_user


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
        assert loaded.reasoning_multiplier == Decimal("1.0")


async def test_model_tier_reasoning_multiplier_roundtrip(app: FastAPI) -> None:
    from decimal import Decimal

    from app.models import ModelTier

    database = app.state.database
    async with database.session() as session:
        session.add(
            ModelTier(
                alias="reasoning-test",
                display_name="Reasoning Test",
                upstream_model_id="model-z",
                upstream_provider_name="provider",
                input_credits_per_1k_tokens=Decimal("1.0"),
                output_credits_per_1k_tokens=Decimal("2.0"),
                reasoning_multiplier=Decimal("1.5"),
                max_output_tokens=1024,
                context_window=128000,
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(
            select(ModelTier).where(ModelTier.alias == "reasoning-test")
        )
        assert loaded is not None
        assert loaded.reasoning_multiplier == Decimal("1.5")


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
        assert loaded.max_concurrent_requests is None


async def test_user_terms_acceptance_roundtrip(app: FastAPI) -> None:
    """Contractual sharing clause: acceptance is recorded and auditable."""
    from app.models.base import utcnow

    database = app.state.database
    accepted_at = utcnow()
    async with database.session() as session:
        session.add(
            User(
                email="terms@example.com",
                password_hash="hash",
                terms_accepted_at=accepted_at,
                terms_version="2026-09",
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(select(User).where(User.email == "terms@example.com"))
        assert loaded is not None
        assert loaded.terms_accepted_at is not None
        assert loaded.terms_version == "2026-09"
        assert loaded.security_flagged is False


async def test_user_security_flag_roundtrip(app: FastAPI) -> None:
    database = app.state.database
    async with database.session() as session:
        session.add(
            User(
                email="flagged@example.com",
                password_hash="hash",
                security_flagged=True,
                security_flag_reason="distinct_clients:6",
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(select(User).where(User.email == "flagged@example.com"))
        assert loaded is not None
        assert loaded.security_flagged is True
        assert loaded.security_flag_reason == "distinct_clients:6"


async def test_usage_event_cost_fields_roundtrip(app: FastAPI) -> None:
    """The eight cost-accounting columns persist alongside the billing data."""
    import uuid as uuid_mod
    from decimal import Decimal

    database = app.state.database
    user = await create_user(app, "cost-fields@example.com")
    request_id = uuid_mod.uuid4()
    parent_id = uuid_mod.uuid4()
    async with database.session() as session:
        session.add(
            UsageEvent(
                request_id=request_id,
                user_id=user.id,
                tier_alias="fast",
                upstream_model_id="model-x",
                prompt_tokens=100,
                completion_tokens=50,
                credits_charged=Decimal("1.5"),
                status=UsageStatus.SETTLED,
                upstream_cost_usd=Decimal("0.0025"),
                cached_prompt_tokens=60,
                cache_write_tokens=20,
                reasoning_tokens=15,
                selected_model_id="the-actual-model",
                parent_request_id=parent_id,
                session_id="conv-42",
                finish_reason="tool_calls",
            )
        )
        await session.commit()

    async with database.session() as session:
        loaded = await session.scalar(
            select(UsageEvent).where(UsageEvent.request_id == request_id)
        )
        assert loaded is not None
        assert loaded.upstream_cost_usd == Decimal("0.0025")
        assert loaded.cached_prompt_tokens == 60
        assert loaded.cache_write_tokens == 20
        assert loaded.reasoning_tokens == 15
        assert loaded.selected_model_id == "the-actual-model"
        assert loaded.parent_request_id == parent_id
        assert loaded.session_id == "conv-42"
        assert loaded.finish_reason == "tool_calls"


async def test_cost_daily_rollup_upsert_accumulates(app: FastAPI) -> None:
    """Two settled events on the same day/tier/model fold into ONE rollup row
    whose counters are the sum of both."""
    import uuid as uuid_mod
    from decimal import Decimal

    from app.services import usage_service

    database = app.state.database
    user = await create_user(app, "rollup@example.com")

    for _ in range(2):
        request_id = uuid_mod.uuid4()
        async with database.session() as session:
            event = UsageEvent(
                request_id=request_id,
                user_id=user.id,
                tier_alias="fast",
                upstream_model_id="model-x",
                credits_charged=Decimal("0"),
                estimated=True,
                status=UsageStatus.RESERVED,
            )
            session.add(event)
            await session.commit()
            event_id = event.id
        settled = await usage_service.settle_usage_event(
            database,
            event_id=event_id,
            prompt_tokens=100,
            completion_tokens=50,
            credits=Decimal("1.5"),
            estimated=False,
            latency_ms=10,
            status=UsageStatus.SETTLED,
            upstream_cost_usd=Decimal("0.002"),
            cached_prompt_tokens=40,
            cache_write_tokens=10,
            reasoning_tokens=5,
            selected_model_id="the-actual-model",
            session_id="conv-7",
            finish_reason="stop",
        )
        assert settled is True

    async with database.session() as session:
        rows = (await session.execute(select(CostDailyRollup))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.requests == 2
        assert row.prompt_tokens == 200
        assert row.completion_tokens == 100
        assert row.cached_prompt_tokens == 80
        assert row.cache_write_tokens == 20
        assert row.reasoning_tokens == 10
        assert row.credits_charged == Decimal("3.0")
        assert row.upstream_cost_usd == Decimal("0.004")
        assert row.selected_model_id == "the-actual-model"
        assert row.user_id == user.id


async def test_cost_daily_rollup_separates_models(app: FastAPI) -> None:
    """Different selected models land in different rollup rows (auto tiers
    report the concrete model per request)."""
    import uuid as uuid_mod
    from decimal import Decimal

    from app.services import usage_service

    database = app.state.database
    user = await create_user(app, "rollup-models@example.com")

    for model in ("model-a", "model-b"):
        request_id = uuid_mod.uuid4()
        async with database.session() as session:
            event = UsageEvent(
                request_id=request_id,
                user_id=user.id,
                tier_alias="auto",
                upstream_model_id="openrouter/auto",
                credits_charged=Decimal("0"),
                estimated=True,
                status=UsageStatus.RESERVED,
            )
            session.add(event)
            await session.commit()
            event_id = event.id
        await usage_service.settle_usage_event(
            database,
            event_id=event_id,
            prompt_tokens=10,
            completion_tokens=5,
            credits=Decimal("0.1"),
            estimated=False,
            latency_ms=5,
            status=UsageStatus.SETTLED,
            selected_model_id=model,
        )

    async with database.session() as session:
        rows = (await session.execute(select(CostDailyRollup))).scalars().all()
        assert sorted(r.selected_model_id for r in rows) == ["model-a", "model-b"]
        assert all(r.requests == 1 for r in rows)


async def test_settle_is_idempotent_no_double_rollup(app: FastAPI) -> None:
    """Settling twice must not double-charge nor double-rollup."""
    import uuid as uuid_mod
    from decimal import Decimal

    from app.services import usage_service

    database = app.state.database
    user = await create_user(app, "idem@example.com")
    request_id = uuid_mod.uuid4()
    async with database.session() as session:
        event = UsageEvent(
            request_id=request_id,
            user_id=user.id,
            tier_alias="fast",
            upstream_model_id="model-x",
            credits_charged=Decimal("0"),
            estimated=True,
            status=UsageStatus.RESERVED,
        )
        session.add(event)
        await session.commit()
        event_id = event.id

    kwargs = dict(
        event_id=event_id,
        prompt_tokens=10,
        completion_tokens=5,
        credits=Decimal("0.1"),
        estimated=False,
        latency_ms=1,
        status=UsageStatus.SETTLED,
    )
    assert await usage_service.settle_usage_event(database, **kwargs) is True
    assert await usage_service.settle_usage_event(database, **kwargs) is False

    async with database.session() as session:
        rows = (await session.execute(select(CostDailyRollup))).scalars().all()
        assert len(rows) == 1
        assert rows[0].requests == 1
