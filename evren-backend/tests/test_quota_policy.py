"""Quota policy: free-tier rollover + no-carry-over + billing-event idempotency.

Madde 11 (free tier) ve Madde 15 (kota devri) politikalarÄ±nÄ±n finansal
garantileri:

* KullanÄ±lmayan krediler ASLA devrolmaz â€” her faturalama dÃ¶nemi planÄ±n tam
  limitiyle baÅŸlar (UI'a `rolls_over: false` olarak bildirilir).
* Ãœcretsiz plan kendiliÄŸinden yuvarlanÄ±r (dÃ¶nÃ¼ÅŸÃ¼m hunisi): dÃ¶nem bitince yeni
  bir 30 gÃ¼nlÃ¼k pencere aÃ§Ä±lÄ±r. Ãœcretli plan ASLA kendiliÄŸinden yuvarlanmaz â€”
  Ã¶deme yoksa hizmet yok.
* Ãœcretsizlik fiyata gÃ¶re belirlenir (`is_free_plan`), `is_default`'a gÃ¶re
  DEÄÄ°L: yanlÄ±ÅŸlÄ±kla default iÅŸaretlenmiÅŸ Ã¼cretli plan bedava daÄŸÄ±tÄ±lamaz.
* Ã–deme webhook'u idempotenttir: aynÄ± provider event id ile ikinci kez gelen
  yenileme, ikinci bir dÃ¶nem veremez (Ã§ift hibe = bedava para).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from app.models import Plan, Subscription
from app.models.base import utcnow
from app.services import subscriptions as subscription_service
from app.services.subscriptions import GrantMode, is_free_plan, quota_hint
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from tests.helpers import create_user
from tests.test_plans_admin import create_plan_direct, create_tier_direct

# ---------------------------------------------------------------------------
# Unit: free-plan predicate + quota hint
# ---------------------------------------------------------------------------


def _plan(price: str | None, *, is_default: bool = False) -> Plan:
    return Plan(
        name="p",
        monthly_credit_limit=Decimal("100"),
        max_output_tokens_per_request=1024,
        requests_per_minute=10,
        allowed_tier_aliases=["fast"],
        is_default=is_default,
        price_usd=Decimal(price) if price is not None else None,
    )


def test_free_plan_decided_by_price_not_default_flag() -> None:
    """A PAID plan wrongly flagged `is_default` must NOT count as free â€”
    otherwise it would hand out free rolling quota (paid service for free)."""
    assert is_free_plan(_plan("0")) is True
    assert is_free_plan(_plan(None)) is True  # not purchasable -> behaves like free
    assert is_free_plan(_plan("10")) is False
    assert is_free_plan(_plan("10", is_default=True)) is False


def test_quota_hint_targets_free_users_only() -> None:
    end = utcnow() + timedelta(days=10)
    free_hint = quota_hint(_plan("0"), end)
    assert free_hint["upgrade_to"] == "plus"
    assert free_hint["reset_at"] == end.isoformat()

    paid_hint = quota_hint(_plan("10"), end)
    assert "upgrade_to" not in paid_hint  # no upsell to paying customers
    assert paid_hint["reset_at"] == end.isoformat()


# ---------------------------------------------------------------------------
# Service: period rollover policy
# ---------------------------------------------------------------------------


async def _expire_latest(app: FastAPI, user_id: uuid.UUID) -> None:
    async with app.state.database.session() as session:
        rows = (
            await session.execute(
                select(Subscription)
                .where(Subscription.user_id == user_id)
                .order_by(Subscription.created_at.desc())
            )
        ).scalars().all()
        for row in rows:
            row.period_start = utcnow() - timedelta(days=60)
            row.period_end = utcnow() - timedelta(days=30)
        await session.commit()


async def test_free_period_rolls_forward(app: FastAPI) -> None:
    """An expired FREE account gets a fresh window (conversion funnel) â€” it must
    never be permanently locked out after its first period."""
    plan = await create_plan_direct(app, name="free", price_usd="0", is_default=True)
    user = await create_user(app, "roll-free@example.com")
    await subscription_service.ensure_default_subscription(app.state.database, user.id)
    await _expire_latest(app, user.id)

    active = await subscription_service.get_active_or_rolled_subscription(
        app.state.database, user.id
    )
    assert active is not None
    assert active.plan.id == plan.id
    now = utcnow()
    assert active.period_start <= now < active.period_end


async def test_paid_period_never_rolls_without_payment(app: FastAPI) -> None:
    """No renewal payment, no service: an expired PAID account stays inactive
    until a billing event grants a new period."""
    await create_plan_direct(app, name="free", price_usd="0", is_default=True)
    paid = await create_plan_direct(
        app, name="plus", price_usd="10", is_default=False
    )
    user = await create_user(app, "roll-paid@example.com")
    await subscription_service.assign_plan(app.state.database, user.id, paid.id)
    await _expire_latest(app, user.id)

    active = await subscription_service.get_active_or_rolled_subscription(
        app.state.database, user.id
    )
    assert active is None


async def test_renewal_grants_fresh_period_anchored_at_latest_end(app: FastAPI) -> None:
    """RENEW chains periods: an early-issued renewal must not shorten the period
    already paid for."""
    paid = await create_plan_direct(app, name="plus", price_usd="10", is_default=False)
    user = await create_user(app, "renew-anchor@example.com")
    first = await subscription_service.assign_plan(
        app.state.database, user.id, paid.id, mode=GrantMode.START
    )

    # Renewal arrives EARLY (10 days before the current period ends).
    renewed = await subscription_service.assign_plan(
        app.state.database,
        user.id,
        paid.id,
        mode=GrantMode.RENEW,
        billing_event_id="evt_renew_1",
    )
    assert renewed.period_start == first.period_end
    assert renewed.period_end == first.period_end + timedelta(days=30)

    # The active window is still the FIRST period (handover is automatic).
    active = await subscription_service.get_active_or_rolled_subscription(
        app.state.database, user.id
    )
    assert active is not None
    assert active.subscription_id == first.id


async def test_redelivered_webhook_event_grants_no_second_period(app: FastAPI) -> None:
    """Double-grant protection: the same provider event id can never open two
    periods (a redelivered webhook is free money otherwise)."""
    paid = await create_plan_direct(app, name="plus", price_usd="10", is_default=False)
    user = await create_user(app, "idem-renew@example.com")

    first = await subscription_service.assign_plan(
        app.state.database,
        user.id,
        paid.id,
        mode=GrantMode.RENEW,
        billing_event_id="evt_dup",
    )
    replay = await subscription_service.assign_plan(
        app.state.database,
        user.id,
        paid.id,
        mode=GrantMode.RENEW,
        billing_event_id="evt_dup",
    )
    assert replay.id == first.id
    assert replay.period_start == first.period_start

    async with app.state.database.session() as session:
        rows = (
            await session.execute(
                select(Subscription).where(Subscription.user_id == user.id)
            )
        ).scalars().all()
    # Exactly one row carries the event id â€” no duplicate grant. (Compare ids:
    # the reloaded row is a distinct ORM instance of the same DB row.)
    assert [r.id for r in rows if r.billing_event_id == "evt_dup"] == [first.id]


# ---------------------------------------------------------------------------
# API: quota never rolls over + reset_at surfaced to the UI
# ---------------------------------------------------------------------------


async def test_usage_reports_no_rollover_and_reset_time(
    client: AsyncClient, app: FastAPI
) -> None:
    await create_plan_direct(app, name="free", price_usd="0", is_default=True)
    await create_tier_direct(app)
    headers = await register_and_login_safe(client, "rollover-ui@example.com")

    data = (await client.get("/usage", headers=headers)).json()
    assert data["rolls_over"] is False
    assert data["reset_at"] is not None
    assert data["period_key"] is not None


async def test_free_user_survives_period_expiry_via_api(
    client: AsyncClient, app: FastAPI
) -> None:
    """End-to-end: after the free period expires, /usage still works (lazy roll)
    and reports a FRESH window with the full limit restored."""
    await create_plan_direct(app, name="free", price_usd="0", is_default=True)
    await create_tier_direct(app)
    headers = await register_and_login_safe(client, "roll-api@example.com")
    user_id = uuid.UUID((await client.get("/me", headers=headers)).json()["id"])

    before = (await client.get("/usage", headers=headers)).json()
    await _expire_latest(app, user_id)

    after = (await client.get("/usage", headers=headers)).json()
    assert after["credits_used"] == "0.000000"  # leftovers do NOT carry over
    assert after["credits_remaining"] == after["credit_limit"]
    assert after["period_start"] != before["period_start"]


async def register_and_login_safe(client: AsyncClient, email: str) -> dict[str, str]:
    from tests.helpers import register_and_login

    return await register_and_login(client, email)
