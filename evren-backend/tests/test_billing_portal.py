"""Billing portal + checkout endpoints (ADIM 8.1).

The active provider (Stripe by default, or Dodo Payments / Paddle via
`BILLING_PROVIDER`) is mocked at the `PaymentProvider` method boundary so
these tests never touch the network and never need a real API key.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.models import User
from app.services.billing_providers.stripe import StripeProvider
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from tests.helpers import register_and_login
from tests.test_plans_admin import create_plan_direct


def _stripe_mock(responses: dict[str, dict]) -> AsyncMock:
    """Return a fake provider whose `_request` is keyed by `METHOD /path`."""

    async def _fake(secret_key: str, method: str, path: str, data=None):
        key = f"{method} {path.split('?')[0]}"
        if key not in responses:
            raise AssertionError(f"unexpected Stripe call: {key}")
        return responses[key]

    return AsyncMock(side_effect=_fake)


@pytest.fixture(autouse=True)
def _isolate_stripe_settings(app: FastAPI):
    """Settings are shared across tests; keep billing credentials from leaking."""
    settings = app.state.settings
    original = settings.stripe_secret_key
    original_provider = settings.billing_provider
    original_api_key = settings.billing_api_key
    settings.stripe_secret_key = None
    settings.billing_provider = "stripe"
    settings.billing_api_key = None
    yield
    settings.stripe_secret_key = original
    settings.billing_provider = original_provider
    settings.billing_api_key = original_api_key


async def _stripe_customer_id(app: FastAPI, email: str) -> str | None:
    async with app.state.database.session() as session:
        user = await session.scalar(select(User).where(User.email == email))
        return user.provider_customer_id if user else None


# ---- GET /billing/portal ----------------------------------------------------


async def test_portal_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/billing/portal")
    assert response.status_code == 401


async def test_portal_not_configured(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "portal-nc@example.com")
    response = await client.get("/billing/portal", headers=headers)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_configured"


async def test_portal_creates_customer_and_returns_url(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "portal-new@example.com")
    app.state.settings.billing_api_key = SecretStr("sk_test_dummy")

    fake = _stripe_mock(
        {
            "GET /customers": {"data": []},
            "POST /customers": {"id": "cus_new123"},
            "POST /billing_portal/sessions": {"url": "https://billing.stripe.com/session/test"},
        }
    )
    with patch.object(StripeProvider, "_request", fake):
        response = await client.get("/billing/portal", headers=headers)

    assert response.status_code == 200
    assert response.json()["url"] == "https://billing.stripe.com/session/test"
    # Customer id is persisted for next time.
    assert await _stripe_customer_id(app, "portal-new@example.com") == "cus_new123"


async def test_portal_reuses_existing_customer(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "portal-reuse@example.com")
    app.state.settings.billing_api_key = SecretStr("sk_test_dummy")

    fake = _stripe_mock(
        {
            "GET /customers": {"data": [{"id": "cus_existing"}]},
            "POST /billing_portal/sessions": {"url": "https://billing.stripe.com/session/reuse"},
        }
    )
    with patch.object(StripeProvider, "_request", fake):
        response = await client.get("/billing/portal", headers=headers)

    assert response.status_code == 200
    assert await _stripe_customer_id(app, "portal-reuse@example.com") == "cus_existing"
    # No POST /customers call happened — only GET + portal session.
    assert fake.call_count == 2


# ---- POST /billing/checkout -------------------------------------------------


async def test_checkout_requires_plan_id(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "checkout-noplan@example.com")
    response = await client.post("/billing/checkout", json={}, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "missing_plan"


async def test_checkout_plan_not_found(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "checkout-404@example.com")
    response = await client.post(
        "/billing/checkout",
        json={"plan_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "plan_not_found"


async def test_checkout_plan_not_purchasable(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "checkout-np@example.com")
    plan = await create_plan_direct(
        app, name="nostripe", stripe_price_id=None, provider_price_id=None
    )
    response = await client.post(
        "/billing/checkout", json={"plan_id": str(plan.id)}, headers=headers
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "plan_not_purchasable"


async def test_checkout_creates_session(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "checkout-ok@example.com")
    app.state.settings.billing_api_key = SecretStr("sk_test_dummy")
    plan = await create_plan_direct(
        app,
        name="pro-checkout",
        stripe_price_id="price_pro123",
        provider_price_id="price_pro123",
        price_usd="20",
    )

    fake = _stripe_mock(
        {"POST /checkout/sessions": {"url": "https://checkout.stripe.com/session/test"}}
    )
    with patch.object(StripeProvider, "_request", fake):
        response = await client.post(
            "/billing/checkout", json={"plan_id": str(plan.id)}, headers=headers
        )

    assert response.status_code == 200
    assert response.json()["url"] == "https://checkout.stripe.com/session/test"


async def test_checkout_not_configured(client: AsyncClient, app: FastAPI) -> None:
    headers = await register_and_login(client, "checkout-nc@example.com")
    plan = await create_plan_direct(
        app, name="pro-nc", stripe_price_id="price_x", provider_price_id="price_x"
    )
    response = await client.post(
        "/billing/checkout", json={"plan_id": str(plan.id)}, headers=headers
    )
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "not_configured"


# ---- GET /plans exposes price_usd -------------------------------------------


async def test_plans_include_price_usd(client: AsyncClient, app: FastAPI) -> None:
    await create_plan_direct(
        app,
        name="priced",
        price_usd="20",
        stripe_price_id="price_p",
        provider_price_id="price_p",
    )
    response = await client.get("/plans")
    assert response.status_code == 200
    priced = next(p for p in response.json() if p["name"] == "priced")
    assert Decimal(priced["price_usd"]) == Decimal("20")
    assert priced["stripe_price_id"] == "price_p"
    assert priced["provider_price_id"] == "price_p"
