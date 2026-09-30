"""Provider webhook verification + normalization tests (no network, no keys).

Each provider's signature scheme is exercised end-to-end: a payload is signed
with the *real* algorithm (Standard Webhooks for Dodo, `Paddle-Signature`
HMAC-SHA256 for Paddle, `Stripe-Signature` HMAC-SHA256 for Stripe), posted to
`POST /billing/webhook`, and `assign_plan()` is asserted to fire. A tampered
payload must be rejected. This verifies the crypto, not a stub.

Real hosted-checkout creation against test.dodopayments.com /
sandbox-api.paddle.com is intentionally NOT tested here: it needs a real test
account + API key. Marked "waiting" in the README until those arrive.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from app.models import Plan
from app.services.billing_providers.dodo import DodoProvider
from app.services.billing_providers.paddle import PaddleProvider
from app.services.billing_providers.stripe import StripeProvider
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import SecretStr
from tests.helpers import register_and_login

DODO_SECRET = "whsec_" + base64.b64encode(b"d" * 24).decode()
PADDLE_SECRET = "pds_" + "p" * 32
STRIPE_SECRET = "whsec_" + "s" * 32


@pytest.fixture(autouse=True)
def _isolate_billing_settings(app: FastAPI):
    """Keep provider settings from leaking across tests."""
    settings = app.state.settings
    saved = (
        settings.billing_provider,
        settings.billing_api_key,
        settings.billing_webhook_secret,
    )
    settings.billing_provider = "dodo"
    settings.billing_api_key = SecretStr("dodo_test_key")
    settings.billing_webhook_secret = SecretStr(DODO_SECRET)
    yield
    (
        settings.billing_provider,
        settings.billing_api_key,
        settings.billing_webhook_secret,
    ) = saved


async def _seed_plan(app: FastAPI, price_id: str) -> Plan:
    async with app.state.database.session() as session:
        plan = Plan(
            name="webhook-plan",
            monthly_credit_limit=Decimal("100"),
            max_output_tokens_per_request=2048,
            requests_per_minute=10,
            allowed_tier_aliases=["fast"],
            is_default=False,
            provider_price_id=price_id,
        )
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
        return plan


def _sign_dodo(payload: bytes, secret: str, *, webhook_id: str = "msg_test") -> dict[str, str]:
    ts = str(int(time.time()))
    signed = f"{webhook_id}.{ts}.{payload.decode()}".encode()
    key = base64.b64decode(secret.removeprefix("whsec_"))
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {
        "webhook-id": webhook_id,
        "webhook-timestamp": ts,
        "webhook-signature": f"v1,{sig}",
    }


def _sign_paddle(payload: bytes, secret: str) -> dict[str, str]:
    ts = str(int(time.time()))
    h1 = hmac.new(secret.encode(), f"{ts}:{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return {"Paddle-Signature": f"ts={ts};h1={h1}"}


def _sign_stripe(payload: bytes, secret: str) -> dict[str, str]:
    ts = str(int(time.time()))
    v1 = hmac.new(secret.encode(), f"{ts}.{payload.decode()}".encode(), hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={ts},v1={v1}"}


# ---- Dodo Payments (Standard Webhooks) -------------------------------------


async def test_dodo_webhook_assigns_plan(client: AsyncClient, app: FastAPI) -> None:
    await register_and_login(client, "dodo-wh@example.com")
    await _seed_plan(app, "pdt_plan123")

    payload = json.dumps(
        {
            "event_id": "evt_1",
            "type": "subscription.active",
            "data": {
                "subscription_id": "sub_1",
                "product_id": "pdt_plan123",
                "customer": {"customer_id": "cus_1", "email": "dodo-wh@example.com"},
            },
        }
    ).encode()

    with patch("app.services.subscriptions.assign_plan", new_callable=AsyncMock) as assign:
        response = await client.post(
            "/billing/webhook", content=payload, headers=_sign_dodo(payload, DODO_SECRET)
        )

    assert response.status_code == 200
    assert response.json()["plan"] == "webhook-plan"
    assign.assert_awaited_once()


async def test_dodo_webhook_rejects_bad_signature(client: AsyncClient, app: FastAPI) -> None:
    payload = json.dumps({"type": "subscription.active", "data": {}}).encode()
    headers = _sign_dodo(payload, DODO_SECRET)
    headers["webhook-signature"] = "v1," + "A" * 43
    response = await client.post("/billing/webhook", content=payload, headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_signature"


async def test_dodo_webhook_rejects_tampered_payload(client: AsyncClient, app: FastAPI) -> None:
    payload = json.dumps({"type": "subscription.active", "data": {}}).encode()
    headers = _sign_dodo(payload, DODO_SECRET)
    tampered = payload.replace(b"subscription.active", b"subscription.renewedx")
    response = await client.post("/billing/webhook", content=tampered, headers=headers)
    assert response.status_code == 400


# ---- Paddle (Paddle-Signature) ---------------------------------------------


async def test_paddle_webhook_assigns_plan(client: AsyncClient, app: FastAPI) -> None:
    app.state.settings.billing_provider = "paddle"
    app.state.settings.billing_webhook_secret = SecretStr(PADDLE_SECRET)
    await register_and_login(client, "paddle-wh@example.com")
    await _seed_plan(app, "pri_plan123")

    payload = json.dumps(
        {
            "event_id": "evt_2",
            "event_type": "subscription.activated",
            "data": {
                "subscription_id": "sub_2",
                "items": [{"price": {"id": "pri_plan123"}, "quantity": 1}],
                "custom_data": {"email": "paddle-wh@example.com"},
            },
        }
    ).encode()

    with patch("app.services.subscriptions.assign_plan", new_callable=AsyncMock) as assign:
        response = await client.post(
            "/billing/webhook", content=payload, headers=_sign_paddle(payload, PADDLE_SECRET)
        )

    assert response.status_code == 200
    assert response.json()["plan"] == "webhook-plan"
    assign.assert_awaited_once()


async def test_paddle_webhook_rejects_bad_signature(client: AsyncClient, app: FastAPI) -> None:
    app.state.settings.billing_provider = "paddle"
    app.state.settings.billing_webhook_secret = SecretStr(PADDLE_SECRET)
    payload = json.dumps({"event_type": "subscription.activated", "data": {}}).encode()
    headers = _sign_paddle(payload, PADDLE_SECRET)
    headers["Paddle-Signature"] = headers["Paddle-Signature"].replace("h1=", "h1=0")
    response = await client.post("/billing/webhook", content=payload, headers=headers)
    assert response.status_code == 400


# ---- Stripe (regression: existing behaviour) -------------------------------


async def test_stripe_webhook_assigns_plan(client: AsyncClient, app: FastAPI) -> None:
    app.state.settings.billing_provider = "stripe"
    app.state.settings.billing_webhook_secret = SecretStr(STRIPE_SECRET)
    await register_and_login(client, "stripe-wh@example.com")
    await _seed_plan(app, "price_plan123")

    payload = json.dumps(
        {
            "id": "evt_3",
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "customer": "cus_3",
                    "customer_email": "stripe-wh@example.com",
                    "items": {"data": [{"price": {"id": "price_plan123"}}]},
                }
            },
        }
    ).encode()

    with patch("app.services.subscriptions.assign_plan", new_callable=AsyncMock) as assign:
        response = await client.post(
            "/billing/webhook", content=payload, headers=_sign_stripe(payload, STRIPE_SECRET)
        )

    assert response.status_code == 200
    assert response.json()["plan"] == "webhook-plan"
    assign.assert_awaited_once()


# ---- Unit: parse_event normalization ---------------------------------------


def test_dodo_parse_event_normalizes() -> None:
    provider = DodoProvider()
    payload = json.dumps(
        {
            "type": "subscription.renewed",
            "data": {
                "product_id": "pdt_x",
                "customer": {"customer_id": "cus_x", "email": "a@b.co"},
            },
        }
    ).encode()
    event = provider.parse_event(payload)
    assert event is not None
    assert event.type.value == "subscription.renewed"
    assert event.provider_price_id == "pdt_x"
    assert event.customer_email == "a@b.co"


def test_paddle_parse_event_normalizes() -> None:
    provider = PaddleProvider()
    payload = json.dumps(
        {
            "event_type": "subscription.canceled",
            "data": {
                "items": [{"price": {"id": "pri_y"}}],
                "customer_id": "ctm_y",
                "custom_data": {"email": "c@d.co"},
            },
        }
    ).encode()
    event = provider.parse_event(payload)
    assert event is not None
    assert event.type.value == "subscription.cancelled"
    assert event.provider_price_id == "pri_y"
    assert event.customer_email == "c@d.co"


def test_stripe_parse_event_ignores_unknown_type() -> None:
    provider = StripeProvider()
    payload = json.dumps({"type": "customer.created", "data": {"object": {}}}).encode()
    assert provider.parse_event(payload) is None
