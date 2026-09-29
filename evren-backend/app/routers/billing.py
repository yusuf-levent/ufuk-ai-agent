"""Billing endpoints: checkout, customer portal, and provider webhooks.

Provider-agnostic: the active backend (Stripe, Dodo Payments, Paddle) is
selected with `BILLING_PROVIDER` and every provider-specific concern (API
shape, auth, webhook signature) lives in `app.services.billing_providers`.
This router only maps normalized events onto `assign_plan()`.

Endpoints:
* `POST /billing/checkout` -- hosted checkout session for a plan
* `GET  /billing/portal`  -- customer self-service billing portal
* `POST /billing/webhook` -- provider webhook (signature-verified)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select, update

from app.dependencies import get_current_user
from app.errors import ApiError
from app.models import Plan, User
from app.services import subscriptions as subscription_service
from app.services.billing_providers import (
    BillingError,
    EventType,
    WebhookVerificationError,
    get_provider,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


def _resolve(settings):
    """Return (provider, api_key, webhook_secret, success_url, cancel_url)."""
    provider = get_provider(settings.billing_provider)
    api_key = (
        settings.billing_api_key.get_secret_value()
        if settings.billing_api_key
        else (settings.stripe_secret_key.get_secret_value() if settings.stripe_secret_key else None)
    )
    webhook_secret = (
        settings.billing_webhook_secret.get_secret_value()
        if settings.billing_webhook_secret
        else (
            settings.stripe_webhook_secret.get_secret_value()
            if settings.stripe_webhook_secret
            else None
        )
    )
    success_url = settings.billing_success_url or settings.stripe_success_url
    cancel_url = settings.billing_cancel_url or settings.stripe_cancel_url
    return provider, api_key, webhook_secret, success_url, cancel_url


def _billing_error(exc: BillingError) -> ApiError:
    return ApiError(status_code=502, message=exc.message, type="api_error", code=exc.code)


@router.post("/webhook")
async def billing_webhook(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    try:
        provider, _, webhook_secret, _, _ = _resolve(settings)
    except BillingError as exc:
        raise _billing_error(exc) from exc

    body = await request.body()

    if webhook_secret:
        try:
            provider.verify_webhook(payload=body, headers=request.headers, secret=webhook_secret)
        except WebhookVerificationError as exc:
            raise ApiError(
                status_code=400,
                message=str(exc),
                type="invalid_request_error",
                code="invalid_signature",
            ) from exc

    try:
        event = provider.parse_event(body)
    except Exception as exc:
        raise ApiError(
            status_code=400,
            message="Invalid webhook payload",
            type="invalid_request_error",
            code="invalid_payload",
        ) from exc

    if event is None:
        return JSONResponse(content={"received": True, "ignored": True})

    # Only lifecycle events that grant or extend access trigger assign_plan().
    if event.type not in (EventType.SUBSCRIPTION_STARTED, EventType.SUBSCRIPTION_RENEWED):
        logger.info(
            "billing_webhook_ignored",
            provider=provider.name,
            event_type=event.provider_event_type,
            normalized=event.type.value,
        )
        return JSONResponse(content={"received": True, "ignored": True})

    price_id = event.provider_price_id
    customer_email = event.customer_email
    if not price_id or not customer_email:
        logger.info(
            "billing_webhook_ignored",
            event_type=event.provider_event_type,
            has_price=bool(price_id),
            has_email=bool(customer_email),
        )
        return JSONResponse(content={"received": True, "ignored": True})

    database = request.app.state.database
    async with database.session() as session:
        plan = await session.scalar(
            select(Plan).where(
                or_(Plan.provider_price_id == price_id, Plan.stripe_price_id == price_id)
            )
        )
        if plan is None:
            logger.warning("billing_webhook_unknown_price", price_id=price_id)
            return JSONResponse(
                content={"received": True, "ignored": True, "reason": "unknown_price"}
            )

        user = await session.scalar(select(User).where(User.email == customer_email))
        if user is None:
            logger.warning("billing_webhook_unknown_user", email=customer_email)
            return JSONResponse(
                content={"received": True, "ignored": True, "reason": "unknown_user"}
            )

    await subscription_service.assign_plan(database, user.id, plan.id)
    logger.info(
        "billing_webhook_assigned",
        provider=provider.name,
        email=customer_email,
        plan=plan.name,
        price_id=price_id,
    )
    return JSONResponse(content={"received": True, "plan": plan.name})


@router.get("/portal")
async def billing_portal(
    request: Request, user: User = Depends(get_current_user)
) -> JSONResponse:
    settings = request.app.state.settings
    try:
        provider, api_key, _, success_url, _ = _resolve(settings)
    except BillingError as exc:
        raise _billing_error(exc) from exc
    if not provider.is_configured(api_key):
        raise ApiError(
            status_code=501,
            message="Billing portal not configured",
            type="invalid_request_error",
            code="not_configured",
        )

    database = request.app.state.database
    customer_id = user.provider_customer_id or user.stripe_customer_id
    if not customer_id:
        # First time opening the portal: find (or create) the provider
        # customer for this account and remember the id for next time.
        try:
            customer_id = await provider.find_customer_id(api_key=api_key, email=user.email)
            if not customer_id:
                customer_id = await provider.create_customer(
                    api_key=api_key, email=user.email, user_id=str(user.id)
                )
        except BillingError as exc:
            raise _billing_error(exc) from exc
        async with database.session() as session:
            await session.execute(
                update(User).where(User.id == user.id).values(provider_customer_id=customer_id)
            )
            await session.commit()

    try:
        portal = await provider.create_portal(
            api_key=api_key, provider_customer_id=customer_id, return_url=success_url
        )
    except BillingError as exc:
        raise _billing_error(exc) from exc
    return JSONResponse(content={"url": portal.url})


@router.post("/checkout")
async def billing_checkout(
    request: Request, user: User = Depends(get_current_user)
) -> JSONResponse:
    body = await request.json()
    plan_id = body.get("plan_id")
    if not plan_id:
        raise ApiError(
            status_code=400,
            message="plan_id is required",
            type="invalid_request_error",
            code="missing_plan",
        )

    settings = request.app.state.settings
    try:
        provider, api_key, _, success_url, cancel_url = _resolve(settings)
    except BillingError as exc:
        raise _billing_error(exc) from exc

    database = request.app.state.database
    async with database.session() as session:
        plan = await session.scalar(select(Plan).where(Plan.id == plan_id))
    if plan is None:
        raise ApiError(
            status_code=404,
            message="Plan not found",
            type="invalid_request_error",
            code="plan_not_found",
        )
    price_id = plan.provider_price_id or plan.stripe_price_id
    if not price_id:
        raise ApiError(
            status_code=400,
            message="Plan is not purchasable yet",
            type="invalid_request_error",
            code="plan_not_purchasable",
        )
    if not provider.is_configured(api_key):
        raise ApiError(
            status_code=501,
            message="Billing is not configured",
            type="invalid_request_error",
            code="not_configured",
        )

    try:
        session_data = await provider.create_checkout(
            api_key=api_key,
            provider_price_id=price_id,
            user_id=str(user.id),
            user_email=user.email,
            success_url=success_url,
            cancel_url=cancel_url,
        )
    except BillingError as exc:
        raise _billing_error(exc) from exc
    return JSONResponse(content={"url": session_data.url})
