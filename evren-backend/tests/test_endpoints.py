from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from app.models import RefreshToken, Subscription, UsageEvent, User
from app.models.enums import UsageStatus
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from tests.helpers import register_and_login
from tests.test_plans_admin import create_plan_direct, create_tier_direct

PASSWORD = "Passw0rd!123"


@pytest.fixture
async def setup_user(client: AsyncClient, app: FastAPI):
    await create_plan_direct(
        app,
        name="free",
        monthly_credit_limit="100",
        allowed_tier_aliases=["fast", "balanced"],
        is_default=True,
    )
    await create_tier_direct(app)
    await create_tier_direct(
        app,
        alias="balanced",
        display_name="Balanced",
        upstream_model_id="dev-model-balanced",
        input_credits_per_1k_tokens="2.0",
        output_credits_per_1k_tokens="4.0",
        max_output_tokens=2048,
    )
    headers = await register_and_login(client, "endpoints@example.com")
    user_id = uuid.UUID((await client.get("/me", headers=headers)).json()["id"])
    return headers, user_id


async def test_v1_models_lists_plan_tiers_with_details(
    client: AsyncClient, app: FastAPI, setup_user
) -> None:
    headers, _ = setup_user
    response = await client.get("/v1/models", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["object"] == "list"
    aliases = [m["id"] for m in data["data"]]
    assert sorted(aliases) == ["balanced", "fast"]
    fast = next(m for m in data["data"] if m["id"] == "fast")
    assert fast["object"] == "model"
    assert fast["owned_by"] == "dev-provider"
    assert fast["details"]["upstream_model"] == "dev-model-fast"
    assert fast["details"]["display_name"] == "Fast"
    assert fast["details"]["context_window"] == 128000
    # Picker fields: absent when the tier row carries no curated hints.
    assert "price_note" in fast["details"]
    assert "price_note_tr" in fast["details"]
    assert "speed_hint" in fast["details"]
    assert "quality_hint" in fast["details"]
    assert fast["details"]["price_note"] is None
    assert fast["details"]["price_note_tr"] is None
    assert fast["details"]["speed_hint"] is None
    assert fast["details"]["quality_hint"] is None


async def test_v1_models_returns_curated_picker_fields(
    client: AsyncClient, app: FastAPI, setup_user
) -> None:
    headers, _ = setup_user
    await create_tier_direct(
        app,
        alias="curated",
        display_name="Curated Model",
        upstream_model_id="dev-model-curated",
        price_note="Cheap and fast",
        price_note_tr="Ucuz ve hızlı",
        speed_hint=5,
        quality_hint=2,
    )
    # Widen the user's plan so the curated tier is allowed for them.
    async with app.state.database.session() as session:
        from app.models import Plan
        from sqlalchemy import update

        await session.execute(
            update(Plan)
            .where(Plan.name == "free")
            .values(allowed_tier_aliases=["fast", "balanced", "curated"])
        )
        await session.commit()
    response = await client.get("/v1/models", headers=headers)
    assert response.status_code == 200
    curated = next(m for m in response.json()["data"] if m["id"] == "curated")
    assert curated["details"]["display_name"] == "Curated Model"
    assert curated["details"]["price_note"] == "Cheap and fast"
    assert curated["details"]["price_note_tr"] == "Ucuz ve hızlı"
    assert curated["details"]["speed_hint"] == 5
    assert curated["details"]["quality_hint"] == 2


async def test_v1_models_requires_subscription(client: AsyncClient, app: FastAPI) -> None:
    await create_tier_direct(app)
    headers = await register_and_login(client, "nomodels@example.com")
    response = await client.get("/v1/models", headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "subscription_inactive"


async def test_usage_endpoint_aggregates_current_period(
    client: AsyncClient, app: FastAPI, setup_user
) -> None:
    headers, user_id = setup_user
    async with app.state.database.session() as session:
        session.add(
            UsageEvent(
                request_id=uuid.uuid4(),
                user_id=user_id,
                tier_alias="fast",
                upstream_model_id="dev-model-fast",
                prompt_tokens=1000,
                completion_tokens=500,
                reasoning_tokens=150,
                credits_charged=Decimal("2.000000"),
                estimated=False,
                status=UsageStatus.SETTLED,
                latency_ms=100,
            )
        )
        session.add(
            UsageEvent(
                request_id=uuid.uuid4(),
                user_id=user_id,
                tier_alias="fast",
                upstream_model_id="dev-model-fast",
                prompt_tokens=2000,
                completion_tokens=0,
                reasoning_tokens=50,
                credits_charged=Decimal("2.000000"),
                estimated=False,
                status=UsageStatus.SETTLED,
                latency_ms=50,
            )
        )
        await session.commit()

    response = await client.get("/usage", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["plan_name"] == "free"
    assert data["credits_used"] == "4.000000"
    assert data["credits_remaining"] == "96.000000"
    assert data["credit_limit"] == "100.000000"
    per_tier = {t["tier_alias"]: t for t in data["per_tier"]}
    assert per_tier["fast"]["requests"] == 2
    assert per_tier["fast"]["prompt_tokens"] == 3000
    assert per_tier["fast"]["completion_tokens"] == 500
    # Financial transparency: reasoning tokens are surfaced so the user can
    # see WHY a short answer cost what it cost ("thought for N tokens").
    assert per_tier["fast"]["reasoning_tokens"] == 200
    assert per_tier["fast"]["credits_charged"] == "4.000000"
    assert data["period_start"] is not None
    assert data["period_end"] is not None


async def test_usage_requires_subscription(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "nousage@example.com")
    response = await client.get("/usage", headers=headers)
    assert response.status_code == 403


async def test_privacy_info(client: AsyncClient, app: FastAPI) -> None:
    await create_tier_direct(app)
    response = await client.get("/privacy/info")
    assert response.status_code == 200
    data = response.json()
    assert "dev-provider" in data["upstream_providers"]
    assert data["upstream_base_url_host"] == "evren-llmapi.ssyz.org.tr"
    assert "never stored" in data["data_handling"]


async def test_delete_me_anonymizes_usage_and_removes_user(
    client: AsyncClient, app: FastAPI, setup_user
) -> None:
    headers, user_id = setup_user
    async with app.state.database.session() as session:
        session.add(
            UsageEvent(
                request_id=uuid.uuid4(),
                user_id=user_id,
                tier_alias="fast",
                upstream_model_id="dev-model-fast",
                prompt_tokens=10,
                completion_tokens=5,
                credits_charged=Decimal("0.020000"),
                estimated=False,
                status=UsageStatus.SETTLED,
            )
        )
        await session.commit()

    response = await client.request("DELETE", "/me", json={"password": "wrong"}, headers=headers)
    assert response.status_code == 401

    response = await client.request("DELETE", "/me", json={"password": PASSWORD}, headers=headers)
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    response = await client.get("/me", headers=headers)
    assert response.status_code == 401

    login = await client.post(
        "/auth/login", json={"email": "endpoints@example.com", "password": PASSWORD}
    )
    assert login.status_code == 401

    async with app.state.database.session() as session:
        users = (await session.execute(select(User).where(User.id == user_id))).scalars().all()
        tokens = (
            (await session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id)))
            .scalars()
            .all()
        )
        subs = (
            (await session.execute(select(Subscription).where(Subscription.user_id == user_id)))
            .scalars()
            .all()
        )
        events = (
            (await session.execute(select(UsageEvent).where(UsageEvent.tier_alias == "fast")))
            .scalars()
            .all()
        )
    assert users == []
    assert tokens == []
    assert subs == []
    assert len(events) == 1
    assert events[0].user_id is None
    assert events[0].credits_charged == Decimal("0.020000")


async def test_delete_me_clears_all_user_redis_keys(
    client: AsyncClient, app: FastAPI, setup_user
) -> None:
    """Privacy guarantee: every Redis key referencing the user is removed on
    account deletion — including the newer budget/inflight/anomaly keys."""
    headers, user_id = setup_user
    redis = app.state.redis
    await redis.set(f"credits:{user_id}:2026-09-01", "1.5")
    await redis.set(f"rpm:{user_id}:2026-09-01", "3")
    await redis.set(f"budget:{user_id}:1700000000", "2.5")
    await redis.set(f"inflight:{user_id}", "1")
    await redis.sadd(f"anomaly:{user_id}:1700000000:clients", "deadbeef")
    await redis.set(f"anomaly:{user_id}:1700000000:count", "7")

    response = await client.request("DELETE", "/me", json={"password": PASSWORD}, headers=headers)
    assert response.status_code == 200

    for key in (
        f"credits:{user_id}:2026-09-01",
        f"rpm:{user_id}:2026-09-01",
        f"budget:{user_id}:1700000000",
        f"inflight:{user_id}",
        f"anomaly:{user_id}:1700000000:clients",
        f"anomaly:{user_id}:1700000000:count",
    ):
        assert await redis.get(key) is None, f"key survived account deletion: {key}"
