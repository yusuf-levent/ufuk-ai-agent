from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.db import Database
from app.models import Plan, Subscription
from app.models.base import utcnow
from app.models.enums import SubscriptionStatus

PERIOD_DAYS = 30


class GrantMode(StrEnum):
    """How a subscription period is established.

    ASSIGN â€” admin plan change. Inherits the current period so a plan change
             can never reset usage mid-period (abuse vector: exhaust credits,
             re-assign, get a fresh period).
    START  â€” first paid purchase. Opens a fresh period immediately so the
             customer gets the quota they just paid for (a leftover free-trial
             period must not swallow it).
    RENEW  â€” paid renewal. Opens a fresh period anchored at the end of the
             latest known period, so an early-issued renewal never shortens
             the period already paid for, and two renewals chain instead of
             overlapping.
    """

    ASSIGN = "assign"
    START = "start"
    RENEW = "renew"


@dataclass(frozen=True, slots=True)
class BillingPeriod:
    """One billing window: the unit every quota resets against.

    Quotas (credits, images) never roll over between periods â€” the window and
    the ledger key both change, so leftovers simply stop existing.
    """

    key: str
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class ActiveSubscription:
    subscription_id: uuid.UUID
    user_id: uuid.UUID
    plan: Plan
    period_start: datetime
    period_end: datetime

    @property
    def period_key(self) -> str:
        return self.period_start.date().isoformat()

    @property
    def period(self) -> BillingPeriod:
        return BillingPeriod(
            key=self.period_key, start=self.period_start, end=self.period_end
        )


def is_free_plan(plan: Plan) -> bool:
    """Whether a plan is the free tier.

    Decided by PRICE, not ``is_default``: a paid plan mistakenly marked as the
    default must never qualify for free rolling quota (that would give away
    paid service). Plans without a price are not purchasable, so they behave
    like free.
    """
    return plan.price_usd is None or plan.price_usd == 0


def quota_hint(plan: Plan, period_end: datetime) -> dict[str, str]:
    """Extra fields for a 402 quota error.

    Every user gets ``reset_at`` so the UI can say when the quota returns.
    Free-plan users additionally get ``upgrade_to`` â€” the free tier is a
    conversion funnel (100 credits to try the product), not a usage tier, so
    exhaustion is the moment to offer Plus. Paid users never see an upsell
    hint; their quota simply resets next period (unused credits do NOT roll
    over â€” see docs/FIYATLANDIRMA-VE-MODEL-TASARIMI.md).
    """
    hint: dict[str, str] = {"reset_at": period_end.isoformat()}
    if is_free_plan(plan):
        hint["upgrade_to"] = "plus"
    return hint


async def get_active_subscription(db: Database, user_id: uuid.UUID) -> ActiveSubscription | None:
    now = utcnow()
    async with db.session() as session:
        row = await session.scalar(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.period_start <= now,
                Subscription.period_end > now,
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )
        if row is None:
            return None
        plan = await session.get(Plan, row.plan_id)
    if plan is None:
        return None
    return ActiveSubscription(
        subscription_id=row.id,
        user_id=row.user_id,
        plan=plan,
        period_start=row.period_start,
        period_end=row.period_end,
    )


async def get_active_or_rolled_subscription(
    db: Database, user_id: uuid.UUID
) -> ActiveSubscription | None:
    """Like `get_active_subscription`, but lazily rolls the FREE period forward.

    Free tier policy: a free account gets a fresh 100-credit window every
    period, forever â€” it is a conversion funnel, not a one-shot trial. Without
    this, an expired free account would hit `subscription_inactive` forever
    (nobody can come back to be converted).

    PAID accounts deliberately do NOT roll: no renewal payment, no service.
    Rolling them would give away paid quota for free.

    Concurrency: the user's latest subscription row is locked before deciding,
    so two simultaneous requests cannot both insert a rolled period (which
    would double the quota).
    """
    active = await get_active_subscription(db, user_id)
    if active is not None:
        return active

    now = utcnow()
    async with db.session() as session:
        last = await session.scalar(
            select(Subscription)
            .where(Subscription.user_id == user_id)
            .order_by(Subscription.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if last is None:
            return None
        # Re-check under the lock: a concurrent request may have just rolled.
        if last.status == SubscriptionStatus.ACTIVE and last.period_start <= now < last.period_end:
            plan = await session.get(Plan, last.plan_id)
            if plan is None:
                return None
            return ActiveSubscription(
                subscription_id=last.id,
                user_id=last.user_id,
                plan=plan,
                period_start=last.period_start,
                period_end=last.period_end,
            )
        plan = await session.get(Plan, last.plan_id)
        if plan is None or not is_free_plan(plan):
            # Paid plan (or orphaned row): never grant quota without payment.
            return None
        rolled = Subscription(
            user_id=user_id,
            plan_id=last.plan_id,
            period_start=now,
            period_end=now + timedelta(days=PERIOD_DAYS),
            status=SubscriptionStatus.ACTIVE,
        )
        session.add(rolled)
        await session.commit()
        await session.refresh(rolled)
        return ActiveSubscription(
            subscription_id=rolled.id,
            user_id=rolled.user_id,
            plan=plan,
            period_start=rolled.period_start,
            period_end=rolled.period_end,
        )


async def ensure_default_subscription(db: Database, user_id: uuid.UUID) -> bool:
    if await get_active_subscription(db, user_id) is not None:
        return False
    async with db.session() as session:
        plan = await session.scalar(select(Plan).where(Plan.is_default.is_(True)))
        if plan is None:
            return False
        now = utcnow()
        session.add(
            Subscription(
                user_id=user_id,
                plan_id=plan.id,
                period_start=now,
                period_end=now + timedelta(days=PERIOD_DAYS),
                status=SubscriptionStatus.ACTIVE,
            )
        )
        await session.commit()
    return True


async def assign_plan(
    db: Database,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    *,
    mode: GrantMode = GrantMode.ASSIGN,
    billing_event_id: str | None = None,
) -> Subscription:
    """Assign a plan to a user, establishing the billing period per `mode`.

    Billing-period rules (see `GrantMode`):
    * ASSIGN inherits the current period â€” a plan change can never reset usage
      mid-period (abuse vector: exhaust credits, re-assign a plan â€” even the
      same one â€” and get a fresh period). The Redis credit ledger is keyed by
      period_start.date(), so inheriting the period also keeps the ledger.
    * START opens a fresh period now â€” the customer just paid and must get the
      quota they bought, not whatever a leftover free-trial period had.
    * RENEW opens a fresh period anchored at the end of the latest known one.

    `billing_event_id` makes paid grants idempotent: a redelivered provider
    webhook carries the same event id and must never grant a second period
    (double-grant = free money). Rows without an event id (admin grants,
    grandfathered rows) are unaffected.
    """
    now = utcnow()
    async with db.session() as session:
        if billing_event_id is not None:
            existing = await session.scalar(
                select(Subscription).where(
                    Subscription.billing_event_id == billing_event_id
                )
            )
            if existing is not None:
                # Redelivery (or a forged replay): grant nothing new.
                return existing

        current = await session.scalar(
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.period_start <= now,
                Subscription.period_end > now,
            )
            .order_by(Subscription.created_at.desc())
            .limit(1)
        )

        if mode == GrantMode.RENEW:
            latest_end = await session.scalar(
                select(func.max(Subscription.period_end)).where(
                    Subscription.user_id == user_id
                )
            )
            anchor = max(now, latest_end) if latest_end is not None else now
            period_start = anchor
            period_end = anchor + timedelta(days=PERIOD_DAYS)
            # Existing rows stay as they are: the window filter in
            # `get_active_subscription` hands over from the old period to this
            # one automatically, so an early renewal never cuts a paid period
            # short and consecutive renewals chain instead of overlapping.
        elif mode == GrantMode.START:
            period_start = now
            period_end = now + timedelta(days=PERIOD_DAYS)
            await session.execute(
                update(Subscription)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                )
                .values(status=SubscriptionStatus.CANCELLED)
            )
        elif current is not None:
            period_start = current.period_start
            period_end = current.period_end
            current.status = SubscriptionStatus.CANCELLED
        else:
            period_start = now
            period_end = now + timedelta(days=PERIOD_DAYS)
            await session.execute(
                update(Subscription)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.status == SubscriptionStatus.ACTIVE,
                )
                .values(status=SubscriptionStatus.CANCELLED)
            )
        subscription = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            period_start=period_start,
            period_end=period_end,
            status=SubscriptionStatus.ACTIVE,
            billing_event_id=billing_event_id,
        )
        session.add(subscription)
        try:
            await session.commit()
        except IntegrityError:
            # Two identical webhook deliveries raced past the pre-check: the
            # unique constraint on billing_event_id is the real guard. Return
            # the winner's row and grant nothing.
            await session.rollback()
            if billing_event_id is None:
                raise
            existing = await session.scalar(
                select(Subscription).where(
                    Subscription.billing_event_id == billing_event_id
                )
            )
            if existing is None:
                raise
            return existing
        await session.refresh(subscription)
        return subscription
