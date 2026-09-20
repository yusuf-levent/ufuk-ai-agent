from __future__ import annotations

import uuid
from decimal import Decimal

from app.models import ModelTier, Plan, Subscription
from app.models.enums import SubscriptionStatus
from sqlalchemy import select
from tests.helpers import create_user, login_headers, register_and_login, upgrade_to_admin

TIER_BODY = {
    "alias": "fast",
    "display_name": "Fast",
    "upstream_model_id": "dev-model-fast",
    "upstream_provider_name": "dev-provider",
    "input_credits_per_1k_tokens": "1.0",
    "output_credits_per_1k_tokens": "2.0",
    "max_output_tokens": 1024,
    "context_window": 128000,
    "enabled": True,
}

PLAN_BODY = {
    "name": "free",
    "monthly_credit_limit": "100",
    "max_output_tokens_per_request": 2048,
    "requests_per_minute": 10,
    "allowed_tier_aliases": ["fast"],
    "is_default": True,
}


async def create_plan_direct(app, **overrides) -> Plan:
    body = {**PLAN_BODY, **overrides}
    async with app.state.database.session() as session:
        plan = Plan(
            name=body["name"],
            monthly_credit_limit=Decimal(str(body["monthly_credit_limit"])),
            max_output_tokens_per_request=body["max_output_tokens_per_request"],
            requests_per_minute=body["requests_per_minute"],
            allowed_tier_aliases=body["allowed_tier_aliases"],
            is_default=body["is_default"],
        )
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
        return plan


async def create_tier_direct(app, **overrides) -> ModelTier:
    body = {**TIER_BODY, **overrides}
    async with app.state.database.session() as session:
        tier = ModelTier(
            alias=body["alias"],
            display_name=body["display_name"],
            upstream_model_id=body["upstream_model_id"],
            upstream_provider_name=body["upstream_provider_name"],
            input_credits_per_1k_tokens=Decimal(str(body["input_credits_per_1k_tokens"])),
            output_credits_per_1k_tokens=Decimal(str(body["output_credits_per_1k_tokens"])),
            max_output_tokens=body["max_output_tokens"],
            context_window=body["context_window"],
            enabled=body["enabled"],
        )
        session.add(tier)
        await session.commit()
        await session.refresh(tier)
        return tier


async def admin_headers(app, client) -> dict[str, str]:
    await create_user(app, "admin@example.com")
    await upgrade_to_admin(app, "admin@example.com")
    return await login_headers(client, "admin@example.com")


async def test_register_creates_default_subscription(client, app) -> None:
    await create_plan_direct(app)
    headers = await register_and_login(client, "sub@example.com")

    response = await client.get("/me", headers=headers)
    user_id = response.json()["id"]

    database = app.state.database
    async with database.session() as session:
        subs = (
            (await session.execute(select(Subscription).where(Subscription.user_id == user_id)))
            .scalars()
            .all()
        )
    assert len(subs) == 1
    assert subs[0].status == SubscriptionStatus.ACTIVE


async def test_register_without_default_plan(client, app) -> None:
    headers = await register_and_login(client, "nosub@example.com")
    response = await client.get("/me", headers=headers)
    user_id = response.json()["id"]
    async with app.state.database.session() as session:
        subs = (
            (await session.execute(select(Subscription).where(Subscription.user_id == user_id)))
            .scalars()
            .all()
        )
    assert subs == []


async def test_public_plans_listing(client, app) -> None:
    await create_plan_direct(app)
    response = await client.get("/plans")
    assert response.status_code == 200
    plans = response.json()
    assert len(plans) >= 1
    free = next(p for p in plans if p["name"] == "free")
    assert free["allowed_tier_aliases"] == ["fast"]
    assert free["is_default"] is True


async def test_admin_endpoints_require_admin(client, app) -> None:
    user_headers = await register_and_login(client, "plain@example.com")
    for method, path in [
        ("get", "/admin/plans"),
        ("get", "/admin/tiers"),
        ("get", "/admin/users"),
    ]:
        response = await getattr(client, method)(path, headers=user_headers)
        assert response.status_code == 403


async def test_admin_plan_crud(client, app) -> None:
    headers = await admin_headers(app, client)

    response = await client.post("/admin/plans", json=PLAN_BODY, headers=headers)
    assert response.status_code == 201, response.text
    plan = response.json()
    assert plan["name"] == "free"

    response = await client.patch(
        f"/admin/plans/{plan['id']}",
        json={"monthly_credit_limit": "250", "allowed_tier_aliases": ["fast", "balanced"]},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["monthly_credit_limit"] == "250.000000"
    assert response.json()["allowed_tier_aliases"] == ["fast", "balanced"]

    response = await client.get("/admin/plans", headers=headers)
    assert any(p["id"] == plan["id"] for p in response.json())


async def test_admin_tier_crud_and_cache_invalidation(client, app) -> None:
    headers = await admin_headers(app, client)
    redis = app.state.redis
    database = app.state.database

    response = await client.post("/admin/tiers", json=TIER_BODY, headers=headers)
    assert response.status_code == 201, response.text
    tier = response.json()

    from app.services.tiers import get_tier

    view = await get_tier(database, redis, "fast")
    assert view is not None
    assert view.upstream_model_id == "dev-model-fast"

    response = await client.patch(
        f"/admin/tiers/{tier['id']}",
        json={"upstream_model_id": "dev-model-fast-v2"},
        headers=headers,
    )
    assert response.status_code == 200

    view = await get_tier(database, redis, "fast")
    assert view is not None
    assert view.upstream_model_id == "dev-model-fast-v2"


async def test_admin_assign_plan(client, app) -> None:
    headers = await admin_headers(app, client)
    free = await create_plan_direct(app)
    user_headers = await register_and_login(client, "assignee@example.com")
    user_id = (await client.get("/me", headers=user_headers)).json()["id"]

    pro_body = {**PLAN_BODY, "name": "pro", "is_default": False, "monthly_credit_limit": "5000"}
    response = await client.post("/admin/plans", json=pro_body, headers=headers)
    pro = response.json()

    response = await client.post(
        f"/admin/users/{user_id}/subscriptions",
        json={"plan_id": pro["id"]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "active"

    async with app.state.database.session() as session:
        subs = (
            (await session.execute(select(Subscription).where(Subscription.user_id == user_id)))
            .scalars()
            .all()
        )
    assert len(subs) == 2
    active = [s for s in subs if s.status == SubscriptionStatus.ACTIVE]
    assert len(active) == 1
    assert str(active[0].plan_id) == pro["id"]
    assert str(free.id) != pro["id"]


async def test_admin_usage_endpoint(client, app) -> None:

    from app.models import UsageEvent
    from app.models.enums import UsageStatus

    headers = await admin_headers(app, client)
    await create_plan_direct(app)
    user_headers = await register_and_login(client, "spender@example.com")
    user_id = (await client.get("/me", headers=user_headers)).json()["id"]

    async with app.state.database.session() as session:
        for i in range(2):
            session.add(
                UsageEvent(
                    request_id=uuid.uuid4(),
                    user_id=user_id,
                    tier_alias="fast",
                    upstream_model_id="dev-model-fast",
                    prompt_tokens=1000,
                    completion_tokens=500,
                    credits_charged=Decimal("2.000000"),
                    estimated=False,
                    status=UsageStatus.SETTLED,
                    latency_ms=100 + i,
                )
            )
        await session.commit()

    response = await client.get(f"/admin/users/{user_id}/usage", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["credits_used"] == "4.000000"
    assert data["per_tier"][0]["tier_alias"] == "fast"
    assert data["per_tier"][0]["requests"] == 2
    assert data["per_tier"][0]["prompt_tokens"] == 2000
    assert data["per_tier"][0]["credits_charged"] == "4.000000"
