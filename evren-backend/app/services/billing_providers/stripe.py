"""Stripe billing provider.

Preserves the pre-existing hand-rolled Stripe REST integration (form-encoded
requests, no SDK dependency) behind the provider interface, so existing
`STRIPE_*` configurations keep working unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
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

STRIPE_API_BASE = "https://api.stripe.com/v1"

#: Stripe event type -> normalized lifecycle event.
_EVENT_TYPES: dict[str, EventType] = {
    "checkout.session.completed": EventType.SUBSCRIPTION_STARTED,
    "customer.subscription.created": EventType.SUBSCRIPTION_STARTED,
    "customer.subscription.updated": EventType.SUBSCRIPTION_UPDATED,
    "customer.subscription.deleted": EventType.SUBSCRIPTION_CANCELLED,
    "invoice.paid": EventType.SUBSCRIPTION_RENEWED,
    "invoice.payment_failed": EventType.PAYMENT_FAILED,
}


def _flatten(params: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten nested dicts/lists into Stripe's bracket form: line_items[0][price]."""
    flat: dict[str, str] = {}
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, name))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    flat.update(_flatten(item, f"{name}[{index}]"))
                else:
                    flat[f"{name}[{index}]"] = str(item)
        elif value is not None:
            flat[name] = str(value)
    return flat


class StripeProvider(PaymentProvider):
    name = "stripe"

    def is_configured(self, api_key: str | None) -> bool:
        return bool(api_key)

    async def _request(
        self, secret_key: str, method: str, path: str, data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method,
                f"{STRIPE_API_BASE}{path}",
                data=data,
                auth=(secret_key, ""),
            )
        payload = response.json() if response.content else {}
        if response.status_code >= 400:
            message = payload.get("error", {}).get("message", response.text[:200])
            raise BillingError(f"Billing provider error: {message}", code="stripe_error")
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
        session_data = await self._request(
            api_key,
            "POST",
            "/checkout/sessions",
            _flatten(
                {
                    "mode": "subscription",
                    "client_reference_id": user_id,
                    "customer_email": user_email,
                    "line_items": [{"price": provider_price_id, "quantity": 1}],
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                }
            ),
        )
        return CheckoutSession(
            url=session_data["url"], provider_session_id=session_data.get("id")
        )

    async def create_portal(
        self, *, api_key: str, provider_customer_id: str, return_url: str
    ) -> PortalSession:
        portal = await self._request(
            api_key,
            "POST",
            "/billing_portal/sessions",
            _flatten({"customer": provider_customer_id, "return_url": return_url}),
        )
        return PortalSession(url=portal["url"])

    async def find_customer_id(self, *, api_key: str, email: str) -> str | None:
        found = await self._request(api_key, "GET", f"/customers?email={email}&limit=1")
        customers = found.get("data") or []
        return customers[0]["id"] if customers else None

    async def create_customer(self, *, api_key: str, email: str, user_id: str) -> str:
        created = await self._request(
            api_key,
            "POST",
            "/customers",
            _flatten({"email": email, "metadata": {"ufuk_user_id": user_id}}),
        )
        customer_id: str = created["id"]
        return customer_id

    def verify_webhook(self, *, payload: bytes, headers: Any, secret: str) -> None:
        signature = headers.get("stripe-signature")
        if not signature:
            raise WebhookVerificationError("Missing Stripe-Signature header")
        # Minimal Stripe signature check: HMAC-SHA256 of payload with webhook
        # secret. Stripe sends "t=...,v1=..." — we verify v1 against our secret.
        try:
            parts = dict(item.split("=", 1) for item in signature.split(",") if "=" in item)
            v1 = parts.get("v1", "")
            timestamp = parts.get("t", "")
            signed_payload = f"{timestamp}.{payload.decode()}".encode()
            expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        except Exception as exc:  # malformed header is a verification failure
            raise WebhookVerificationError("Malformed Stripe-Signature header") from exc
        if not hmac.compare_digest(expected, v1):
            raise WebhookVerificationError("Invalid Stripe signature")

    def parse_event(self, payload: bytes) -> NormalizedEvent | None:
        event = json.loads(payload.decode())
        event_type = event.get("type", "")
        normalized_type = _EVENT_TYPES.get(event_type)
        if normalized_type is None:
            return None

        data = (
            event.get("data", {}).get("object", {})
            if isinstance(event.get("data"), dict)
            else {}
        )
        customer_details = data.get("customer_details")
        customer_email = data.get("customer_email") or (
            customer_details.get("email") if isinstance(customer_details, dict) else None
        )

        # Extract price_id from various shapes (checkout session, subscription items).
        price_id = None
        items_obj = data.get("items")
        if isinstance(items_obj, dict):
            items = items_obj.get("data", [])
            if items and isinstance(items[0], dict):
                price_val = items[0].get("price")
                price_id = price_val.get("id") if isinstance(price_val, dict) else price_val
        if not price_id and isinstance(data.get("price"), dict):
            price_id = data["price"].get("id")
        if not price_id:
            price_id = data.get("price_id") or data.get("plan_price_id")

        return NormalizedEvent(
            type=normalized_type,
            provider_event_id=event.get("id"),
            provider_event_type=event_type,
            provider_price_id=price_id,
            provider_customer_id=data.get("customer"),
            customer_email=customer_email,
            raw=event,
        )
