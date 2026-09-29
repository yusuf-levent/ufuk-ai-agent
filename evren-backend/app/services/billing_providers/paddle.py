"""Paddle billing provider (Merchant of Record).

Docs: https://developer.paddle.com/ (see llms.txt for the full index).
* API base: `https://sandbox-api.paddle.com` (sandbox) /
  `https://api.paddle.com` (production), JSON over REST.
* Auth: `Authorization: Bearer <api key>` (API key created per environment).
* Webhooks: `Paddle-Signature` header formatted `ts=<unix>;h1=<hex>` where
  `h1 = HMAC_SHA256(secret, "{ts}:{raw_body}")` (hex digest).
* Paddle prices support `TRY` (Turkish Lira) as a transaction currency.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.services.billing_providers.base import (
    BillingError,
    CheckoutSession,
    EventType,
    NormalizedEvent,
    PaymentProvider,
    PortalSession,
    WebhookVerificationError,
)

SANDBOX_API_BASE = "https://sandbox-api.paddle.com"
LIVE_API_BASE = "https://api.paddle.com"

#: Paddle event type -> normalized lifecycle event.
_EVENT_TYPES: dict[str, EventType] = {
    "subscription.activated": EventType.SUBSCRIPTION_STARTED,
    "subscription.created": EventType.SUBSCRIPTION_STARTED,
    "subscription.renewed": EventType.SUBSCRIPTION_RENEWED,
    "subscription.updated": EventType.SUBSCRIPTION_UPDATED,
    "subscription.canceled": EventType.SUBSCRIPTION_CANCELLED,
    "transaction.completed": EventType.PAYMENT_SUCCEEDED,
    "transaction.payment_failed": EventType.PAYMENT_FAILED,
}

#: Signature freshness window (seconds) — Paddle recommends a small window.
_TOLERANCE_SECONDS = 5 * 60


class PaddleProvider(PaymentProvider):
    name = "paddle"

    def __init__(self, *, live_mode: bool = False) -> None:
        self._base_url = LIVE_API_BASE if live_mode else SANDBOX_API_BASE

    def is_configured(self, api_key: str | None) -> bool:
        return bool(api_key)

    async def _request(
        self, api_key: str, method: str, path: str, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                json=json_body,
                headers={
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                },
            )
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            error = payload.get("error", {})
            message = error.get("detail", response.text[:200])
            raise BillingError(f"Billing provider error: {message}", code="paddle_error")
        return payload.get("data", payload)

    async def create_checkout(
        self,
        *,
        api_key: str,
        provider_price_id: str,
        user_id: str,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        # Paddle Billing: create a transaction for the price, then open a
        # checkout on it. `provider_price_id` holds the Paddle `pri_...` id.
        transaction = await self._request(
            api_key,
            "POST",
            "/transactions",
            {
                "items": [{"price_id": provider_price_id, "quantity": 1}],
                "custom_data": {"ufuk_user_id": user_id},
            },
        )
        checkout = transaction.get("checkout") or {}
        url = checkout.get("url")
        if not url:
            raise BillingError("Paddle returned no checkout URL", code="paddle_error")
        return CheckoutSession(url=url, provider_session_id=transaction.get("id"))

    async def create_portal(
        self, *, api_key: str, provider_customer_id: str, return_url: str
    ) -> PortalSession:
        # Paddle's customer portal is a hosted URL derived from the customer id.
        host = (
            "https://sandbox-customer.paddle.com"
            if self._base_url == SANDBOX_API_BASE
            else "https://customer.paddle.com"
        )
        return PortalSession(url=f"{host}/{provider_customer_id}")

    async def find_customer_id(self, *, api_key: str, email: str) -> str | None:
        found = await self._request(api_key, "GET", f"/customers?email={email}&per_page=1")
        customers = found if isinstance(found, list) else []
        return customers[0]["id"] if customers else None

    async def create_customer(self, *, api_key: str, email: str, user_id: str) -> str:
        created = await self._request(
            api_key,
            "POST",
            "/customers",
            {"email": email, "custom_data": {"ufuk_user_id": user_id}},
        )
        return created["id"]

    def verify_webhook(self, *, payload: bytes, headers: Any, secret: str) -> None:
        signature = headers.get("paddle-signature")
        if not signature:
            raise WebhookVerificationError("Missing Paddle-Signature header")
        # Format: "ts=<unix>;h1=<hex hmac of '{ts}:{body}'>"
        parts = dict(item.split("=", 1) for item in signature.split(";") if "=" in item)
        ts = parts.get("ts", "")
        h1 = parts.get("h1", "")
        if not ts or not h1:
            raise WebhookVerificationError("Malformed Paddle-Signature header")
        try:
            ts_int = int(ts)
        except ValueError as exc:
            raise WebhookVerificationError("Malformed Paddle-Signature timestamp") from exc
        if abs(time.time() - ts_int) > _TOLERANCE_SECONDS:
            raise WebhookVerificationError("Webhook timestamp outside tolerance")

        signed = f"{ts}:{payload.decode()}".encode()
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, h1):
            raise WebhookVerificationError("Invalid Paddle signature")

    def parse_event(self, payload: bytes) -> NormalizedEvent | None:
        event = json.loads(payload.decode())
        event_type = event.get("event_type", "")
        normalized_type = _EVENT_TYPES.get(event_type)
        if normalized_type is None:
            return None

        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        custom_data = data.get("custom_data") if isinstance(data.get("custom_data"), dict) else {}

        # Paddle subscriptions carry `items[].price.id`; transactions carry
        # `items[].price_id`.
        price_id = None
        items = data.get("items") if isinstance(data.get("items"), list) else []
        if items and isinstance(items[0], dict):
            first = items[0]
            price_val = first.get("price")
            price_id = (
                price_val.get("id") if isinstance(price_val, dict) else first.get("price_id")
            )

        return NormalizedEvent(
            type=normalized_type,
            provider_event_id=event.get("event_id"),
            provider_event_type=event_type,
            provider_price_id=price_id,
            provider_customer_id=data.get("customer_id"),
            customer_email=custom_data.get("email") or data.get("email"),
            raw=event,
        )
