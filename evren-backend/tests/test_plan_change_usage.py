"""Regression tests: a plan change must not reset usage counters mid-period.

Rule (app/services/subscriptions.py assign_plan): assigning a plan while a
subscription is active now inherits its billing period; credits already used
in that period count against the new plan's limit. Only a user with no active
subscription gets a fresh 30-day period.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from app.models import Subscription, UsageEvent
from app.models.base import utcnow
from app.models.enums import SubscriptionStatus, UsageStatus
from app.services.upstream import UpstreamClient
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, update
from tests.helpers import create_user, login_headers, register_and_login
from tests.test_gateway import MESSAGES, completion_response
from tests.test_plans_admin import PLAN_BODY, admin_headers, create_plan_direct, create_tier_direct

CHAT_URL = "/v1/chat/completions"


@pytest.fixture
async def install_upstream(app: FastAPI):
    created: list[UpstreamClient] = []

    async def install(handler) -> UpstreamClient:
        client = UpstreamClient(app.state.settings, transport=httpx.MockTransport(handler))
        created.append(client)
        app.state.upstream = client
        return client

    yield install
    for client in created:
        await client.aclose()


async def _settle_usage(app: FastAPI, user_id: uuid.UUID, credits: str, tier: str = "fast") -> None:
    """Insert a settled usage row as if a request had been charged."""
    async with app.state.database.session() as session:
        session.add(
            UsageEvent(
                request_id=uuid.uuid4(),
                user_id=user_id,
                tier_alias=tier,
                upstream_model_id="dev-model-fast",
                prompt_tokens=1000,
                completion_tokens=500,
                credits_charged=Decimal(credits),
                estimated=False,
                status=UsageStatus.SETTLED,
                latency_ms=50,
            )
        )
        await session.commit()


async def _assign_plan(client: AsyncClient, admin: dict, user_id: str, plan_id: str):
    response = await client.post(
        f"/admin/users/{user_id}/subscriptions", json={"plan_id": plan_id}, headers=admin
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_plan_change_keeps_period_and_usage(client, app) -> None:
    admin = await admin_headers(app, client)
    await create_plan_direct(app)  # free, limit 100
    await create_tier_direct(app)
    user_headers = await register_and_login(client, "keep@example.com")
    user_id = (await client.get("/me", headers=user_headers)).json()["id"]

    before = (await client.get("/usage", headers=user_headers)).json()
    await _settle_usage(app, uuid.UUID(user_id), "4")

    pro = {**PLAN_BODY, "name": "pro", "is_default": False, "monthly_credit_limit": "5000"}
    response = await client.post("/admin/plans", json=pro, headers=admin)
    assert response.status_code == 201, response.text

    subscription = await _assign_plan(client, admin, user_id, response.json()["id"])
    assert subscription["period_start"] == before["period_start"]
    assert subscription["period_end"] == before["period_end"]

    after = (await client.get("/usage", headers=user_headers)).json()
    assert after["plan_name"] == "pro"
    assert after["period_start"] == before["period_start"]
    assert after["period_end"] == before["period_end"]
    assert after["credits_used"] == "4.000000"
    assert after["credit_limit"] == "5000.000000"
    assert after["credits_remaining"] == "4996.000000"


async def test_reassign_same_plan_does_not_reset_period(client, app) -> None:
    """Abuse vector: exhaust credits, re-assign the same plan, expect no reset."""
    admin = await admin_headers(app, client)
    free = await create_plan_direct(app)
    await create_tier_direct(app)
    user_headers = await register_and_login(client, "sameplan@example.com")
    user_id = (await client.get("/me", headers=user_headers)).json()["id"]

    before = (await client.get("/usage", headers=user_headers)).json()
    await _settle_usage(app, uuid.UUID(user_id), "4")

    subscription = await _assign_plan(client, admin, user_id, str(free.id))
    assert subscription["plan_id"] == str(free.id)
    assert subscription["period_start"] == before["period_start"]
    assert subscription["period_end"] == before["period_end"]

    after = (await client.get("/usage", headers=user_headers)).json()
    assert after["credits_used"] == "4.000000"
    assert after["credits_remaining"] == "96.000000"


async def test_downgrade_below_usage_blocks_next_request(client, app, install_upstream) -> None:
    """After downgrading to a limit below what was already used, the very next
    request is rejected with 402 (the Redis ledger carries over)."""
    admin = await admin_headers(app, client)
    await create_plan_direct(app)  # free, limit 100
    await create_tier_direct(app)
    user_headers = await register_and_login(client, "downgrade@example.com")
    user_id = (await client.get("/me", headers=user_headers)).json()["id"]

    # one real request settles 0.02 credits (10 prompt / 5 completion, 1.0/2.0 per 1k)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=completion_response())

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=user_headers
    )
    assert response.status_code == 200, response.text
    assert len(calls) == 1

    tiny = {**PLAN_BODY, "name": "tiny", "is_default": False, "monthly_credit_limit": "0.01"}
    response = await client.post("/admin/plans", json=tiny, headers=admin)
    assert response.status_code == 201, response.text
    await _assign_plan(client, admin, user_id, response.json()["id"])

    usage = (await client.get("/usage", headers=user_headers)).json()
    assert usage["credit_limit"] == "0.010000"
    assert usage["credits_used"] == "0.020000"
    assert usage["credits_remaining"] == "0"  # clamped: max(0.01 - 0.02, 0)

    def no_call(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("upstream must not be called when quota is exceeded")

    await install_upstream(no_call)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=user_headers
    )
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "quota_exceeded"
    assert len(calls) == 1


async def test_assignment_without_active_subscription_starts_fresh_period(client, app) -> None:
    admin = await admin_headers(app, client)
    free = await create_plan_direct(app)
    user_headers = await register_and_login(client, "expired@example.com")
    user_id = (await client.get("/me", headers=user_headers)).json()["id"]

    # expire the current subscription
    async with app.state.database.session() as session:
        await session.execute(
            update(Subscription)
            .where(Subscription.user_id == uuid.UUID(user_id))
            .values(period_end=utcnow() - timedelta(days=1))
        )
        await session.commit()

    subscription = await _assign_plan(client, admin, user_id, str(free.id))
    now = utcnow()
    assert subscription["period_start"] > (now - timedelta(minutes=1)).isoformat()
    assert subscription["period_end"] > now.isoformat()


async def test_assignment_to_user_without_subscription(client, app) -> None:
    """No default plan at registration -> no subscription; first assignment
    creates a fresh period."""
    admin = await admin_headers(app, client)
    free = await create_plan_direct(app, is_default=False)
    await create_user(app, "nosub-plan@example.com")
    admin_user_headers = await login_headers(client, "admin@example.com")
    admin_id = (await client.get("/me", headers=admin_user_headers)).json()["id"]

    # sanity: the admin itself has no subscription (default plan was not default)
    async with app.state.database.session() as session:
        subs = (
            (
                await session.execute(
                    select(Subscription).where(Subscription.user_id == uuid.UUID(admin_id))
                )
            )
            .scalars()
            .all()
        )
    assert subs == []

    subscription = await _assign_plan(client, admin, admin_id, str(free.id))
    assert subscription["status"] == SubscriptionStatus.ACTIVE.value
