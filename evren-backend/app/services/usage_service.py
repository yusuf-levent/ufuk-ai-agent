from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update

from app.db import Database
from app.models import UsageEvent
from app.models.enums import UsageStatus
from app.services.credits import quantize_credits


@dataclass(frozen=True, slots=True)
class TierUsage:
    tier_alias: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    credits_charged: Decimal


async def period_usage(
    db: Database, user_id: uuid.UUID, period_start: datetime, period_end: datetime
) -> list[TierUsage]:
    async with db.session() as session:
        rows = (
            await session.execute(
                select(
                    UsageEvent.tier_alias,
                    func.count(UsageEvent.id),
                    func.coalesce(func.sum(UsageEvent.prompt_tokens), 0),
                    func.coalesce(func.sum(UsageEvent.completion_tokens), 0),
                    func.coalesce(func.sum(UsageEvent.credits_charged), 0),
                )
                .where(
                    UsageEvent.user_id == user_id,
                    UsageEvent.created_at >= period_start,
                    UsageEvent.created_at < period_end,
                    UsageEvent.status.in_([UsageStatus.RESERVED, UsageStatus.SETTLED]),
                )
                .group_by(UsageEvent.tier_alias)
                .order_by(UsageEvent.tier_alias)
            )
        ).all()
    return [
        TierUsage(
            tier_alias=row[0],
            requests=row[1],
            prompt_tokens=row[2],
            completion_tokens=row[3],
            credits_charged=quantize_credits(Decimal(row[4])),
        )
        for row in rows
    ]


def total_credits(usage: list[TierUsage]) -> Decimal:
    return quantize_credits(sum((item.credits_charged for item in usage), Decimal(0)))


async def settle_usage_event(
    db: Database,
    *,
    event_id: uuid.UUID,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    credits: Decimal | None,
    estimated: bool,
    latency_ms: int | None,
    status: UsageStatus,
) -> bool:
    """Move a reserved event to a terminal state. Idempotent: only the first
    transition from `reserved` wins, so usage is never double-charged."""
    values: dict[str, object] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated": estimated,
        "status": status,
        "latency_ms": latency_ms,
    }
    if credits is not None:
        values["credits_charged"] = quantize_credits(credits)
    async with db.session() as session:
        result = await session.execute(
            update(UsageEvent)
            .where(UsageEvent.id == event_id, UsageEvent.status == UsageStatus.RESERVED)
            .values(**values)
        )
        await session.commit()
        rowcount: int = result.rowcount  # type: ignore[attr-defined]
        return rowcount == 1
