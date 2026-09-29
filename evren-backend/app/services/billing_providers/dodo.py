"""Dodo Payments billing provider (Merchant of Record).

Docs: https://docs.dodopayments.com/ (see llms.txt for the full index).
* API base: `https://test.dodopayments.com` (test) / `https://live.dodopayments.com`
* Auth: `Authorization: Bearer <api key>`
* Webhooks: Standard Webhooks spec — `webhook-id`, `webhook-timestamp`,
  `webhook-signature` headers; signature is base64(HMAC-SHA256(secret,
  "{webhook-id}.{webhook-timestamp}.{body}")), listed as `v1,<sig>`.
* Turkey is on the merchant-acceptance list and individuals (no registered
  business) are supported — see miscellaneous/accepted-countries-and-territories
  and miscellaneous/faq (Q6).
"""

from __future__ import annotations

import base64
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

TEST_API_BASE = "https://test.dodopayments.com"
LIVE_API_BASE = "https://live.dodopayments.com"

#: Dodo event type -> normalized lifecycle event.
_EVENT_TYPES: dict[str, EventType] = {
    "subscription.active": EventType.SUBSCRIPTION_STARTED,
    "subscription.renewed": EventType.SUBSCRIPTION_RENEWED,
    "subscription.updated": EventType.SUBSCRIPTION_UPDATED,
    "subscription.plan_changed": EventType.SUBSCRIPTION_UPDATED,
    "subscription.cancelled": EventType.SUBSCRIPTION_CANCELLED,
    "subscription.expired": EventType.SUBSCRIPTION_CANCELLED,
    "payment.succeeded": EventType.PAYMENT_SUCCEEDED,
    "payment.failed": EventType.PAYMENT_FAILED,
}

#: Signature freshness window (seconds) per the Standard Webhooks spec.
_TOLERANCE_SECONDS = 5 * 60


class DodoProvider(PaymentProvider):
    name = "dodo"

    def __init__(self, *, live_mode: bool = False) -> None:
        self._base_url = LIVE_API_BASE if live_mode else TEST_API_BASE

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
            message = payload.get("message", response.text[:200])
            raise BillingError(f"Billing provider error: {message}", code="dodo_error")
        return payload

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
        # Dodo sells products (not bare prices): `provider_price_id` holds the
        # Dodo `pdt_...` product id for the plan's subscription product.
        session = await self._request(
            api_key,
            "POST",
            "/checkouts",
            {
                "product_cart": [{"product_id": provider_price_id, "quantity": 1}],
                "customer": {"email": user_email},
                "return_url": success_url,
                "metadata": {"ufuk_user_id": user_id},
            },
        )
        return CheckoutSession(
            url=session["checkout_url"], provider_session_id=session.get("session_id")
        )

    async def create_portal(
        self, *, api_key: str, provider_customer_id: str, return_url: str
    ) -> PortalSession:
        # Dodo's customer portal is a hosted URL derived from the customer id.
        return PortalSession(url=f"https://portal.dodopayments.com/{provider_customer_id}")

    async def find_customer_id(self, *, api_key: str, email: str) -> str | None:
        found = await self._request(api_key, "GET", f"/customers?email={email}&page_size=1")
        customers = found.get("items") or found.get("data") or []
        return customers[0]["customer_id"] if customers else None

    async def create_customer(self, *, api_key: str, email: str, user_id: str) -> str:
        created = await self._request(
            api_key,
            "POST",
            "/customers",
            {"email": email, "metadata": {"ufuk_user_id": user_id}},
        )
        return created["customer_id"]

    def verify_webhook(self, *, payload: bytes, headers: Any, secret: str) -> None:
        # Standard Webhooks: https://standardwebhooks.com/
        webhook_id = headers.get("webhook-id")
        timestamp = headers.get("webhook-timestamp")
        signature = headers.get("webhook-signature")
        if not webhook_id or not timestamp or not signature:
            raise WebhookVerificationError("Missing Standard Webhooks signature headers")
        try:
            ts = int(timestamp)
        except ValueError as exc:
            raise WebhookVerificationError("Malformed webhook timestamp") from exc

        if abs(time.time() - ts) > _TOLERANCE_SECONDS:
            raise WebhookVerificationError("Webhook timestamp outside tolerance")

        signed = f"{webhook_id}.{timestamp}.{payload.decode()}".encode()
        # The secret may arrive with a `whsec_` prefix; strip it before use.
        key = secret.removeprefix("whsec_")
        expected = base64.b64encode(
            hmac.new(key.encode(), signed, hashlib.sha256).digest()
        ).decode()

        # `webhook-signature` is a space-separated list of "v1,<sig>" entries.
        candidates = [part.split(",", 1)[1] for part in signature.split(" ") if "," in part]
        if not any(hmac.compare_digest(expected, candidate) for candidate in candidates):
            raise WebhookVerificationError("Invalid webhook signature")

    def parse_event(self, payload: bytes) -> NormalizedEvent | None:
        event = json.loads(payload.decode())
        event_type = event.get("type", "")
        normalized_type = _EVENT_TYPES.get(event_type)
        if normalized_type is None:
            return None

        data = event.get("data", {}) if isinstance(event.get("data"), dict) else {}
        customer = data.get("customer") if isinstance(data.get("customer"), dict) else {}

        # Subscription payloads carry `product_id`; payment payloads carry
        # `product_cart[].product_id`.
        price_id = data.get("product_id")
        if not price_id:
            cart = data.get("product_cart")
            if isinstance(cart, list) and cart and isinstance(cart[0], dict):
                price_id = cart[0].get("product_id")

        return NormalizedEvent(
            type=normalized_type,
            provider_event_id=event.get("event_id") or event.get("id"),
            provider_event_type=event_type,
            provider_price_id=price_id,
            provider_customer_id=customer.get("customer_id") or data.get("customer_id"),
            customer_email=customer.get("email") or data.get("email"),
            raw=event,
        )
