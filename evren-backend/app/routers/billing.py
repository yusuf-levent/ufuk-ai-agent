from __future__ import annotations

import hashlib
import hmac
import json

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.errors import ApiError
from app.models import Plan
from app.services import subscriptions as subscription_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _verify_stripe_signature(payload: bytes, signature: str, secret: str) -> bool:
    # Minimal Stripe signature check: HMAC-SHA256 of payload with webhook secret.
    # Stripe sends "t=...,v1=..." — we verify v1 against our secret.
    try:
        parts = dict(item.split("=", 1) for item in signature.split(",") if "=" in item)
        v1 = parts.get("v1", "")
        timestamp = parts.get("t", "")
        signed_payload = f"{timestamp}.{payload.decode()}".encode()
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> JSONResponse:
    settings = request.app.state.settings
    secret = (
        settings.stripe_webhook_secret.get_secret_value()
        if settings.stripe_webhook_secret
        else None
    )
    body = await request.body()

    if secret and stripe_signature and not _verify_stripe_signature(
        body, stripe_signature, secret
    ):
        raise ApiError(
            status_code=400,
            message="Invalid Stripe signature",
            type="invalid_request_error",
            code="invalid_signature",
        )

    try:
        event = json.loads(body.decode())
    except Exception as exc:
        raise ApiError(
            status_code=400,
            message="Invalid webhook payload",
            type="invalid_request_error",
            code="invalid_payload",
        ) from exc

    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {}) if isinstance(event.get("data"), dict) else {}

    # We map Stripe price -> Plan via stripe_price_id
    price_id = None
    customer_details = data.get("customer_details")
    customer_email = data.get("customer_email") or (
        customer_details.get("email") if isinstance(customer_details, dict) else None
    )
    # For checkout.session.completed, line items contain price
    if event_type in (
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
    ):
        # Try to extract price_id from various shapes
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

    if not price_id or not customer_email:
        logger.info(
            "billing_webhook_ignored",
            event_type=event_type,
            has_price=bool(price_id),
            has_email=bool(customer_email),
        )
        return JSONResponse(content={"received": True, "ignored": True})

    database = request.app.state.database
    async with database.session() as session:
        plan = await session.scalar(select(Plan).where(Plan.stripe_price_id == price_id))
        if plan is None:
            logger.warning("billing_webhook_unknown_price", price_id=price_id)
            return JSONResponse(
                content={"received": True, "ignored": True, "reason": "unknown_price"}
            )
        from app.models import User

        user = await session.scalar(select(User).where(User.email == customer_email))
        if user is None:
            logger.warning("billing_webhook_unknown_user", email=customer_email)
            return JSONResponse(
                content={"received": True, "ignored": True, "reason": "unknown_user"}
            )

    await subscription_service.assign_plan(database, user.id, plan.id)
    logger.info("billing_webhook_assigned", email=customer_email, plan=plan.name, price_id=price_id)
    return JSONResponse(content={"received": True, "plan": plan.name})


@router.get("/portal")
async def billing_portal(request: Request) -> JSONResponse:
    # Placeholder — returns Stripe Customer Portal URL if configured, else 501
    # Real implementation would create a portal session via Stripe API.
    return JSONResponse(
        status_code=501,
        content={"error": {"message": "Billing portal not configured", "code": "not_configured"}},
    )
