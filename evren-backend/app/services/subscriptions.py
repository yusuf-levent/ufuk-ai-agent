from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update

from app.db import Database
from app.models import Plan, Subscription
from app.models.base import utcnow
from app.models.enums import SubscriptionStatus

PERIOD_DAYS = 30


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
            .order_by(Subscription.period_start.desc())
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


async def assign_plan(db: Database, user_id: uuid.UUID, plan_id: uuid.UUID) -> Subscription:
    now = utcnow()
    async with db.session() as session:
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
            period_start=now,
            period_end=now + timedelta(days=PERIOD_DAYS),
            status=SubscriptionStatus.ACTIVE,
        )
        session.add(subscription)
        await session.commit()
        await session.refresh(subscription)
        return subscription
