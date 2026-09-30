from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import Database
from app.models import CostDailyRollup, UsageEvent
from app.models.enums import UsageStatus
from app.services.credits import quantize_credits


@dataclass(frozen=True, slots=True)
class TierUsage:
    tier_alias: str
    requests: int
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
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
                    func.coalesce(func.sum(UsageEvent.reasoning_tokens), 0),
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
            reasoning_tokens=row[4],
            credits_charged=quantize_credits(Decimal(row[5])),
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
    upstream_cost_usd: Decimal | None = None,
    cached_prompt_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    selected_model_id: str | None = None,
    parent_request_id: uuid.UUID | None = None,
    session_id: str | None = None,
    finish_reason: str | None = None,
) -> bool:
    """Move a reserved event to a terminal state. Idempotent: only the first
    transition from `reserved` wins, so usage is never double-charged."""
    values: dict[str, object] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated": estimated,
        "status": status,
        "latency_ms": latency_ms,
        "cached_prompt_tokens": cached_prompt_tokens,
        "cache_write_tokens": cache_write_tokens,
        "reasoning_tokens": reasoning_tokens,
    }
    if credits is not None:
        values["credits_charged"] = quantize_credits(credits)
    if upstream_cost_usd is not None:
        values["upstream_cost_usd"] = quantize_credits(upstream_cost_usd)
    if selected_model_id is not None:
        values["selected_model_id"] = selected_model_id
    if parent_request_id is not None:
        values["parent_request_id"] = parent_request_id
    if session_id is not None:
        values["session_id"] = session_id
    if finish_reason is not None:
        values["finish_reason"] = finish_reason
    async with db.session() as session:
        result = await session.execute(
            update(UsageEvent)
            .where(UsageEvent.id == event_id, UsageEvent.status == UsageStatus.RESERVED)
            .values(**values)
        )
        rowcount: int = result.rowcount  # type: ignore[attr-defined]
        if rowcount == 1 and status == UsageStatus.SETTLED:
            await _rollup_settled_event(
                session,
                event_id=event_id,
                prompt_tokens=prompt_tokens or 0,
                completion_tokens=completion_tokens or 0,
                cached_prompt_tokens=cached_prompt_tokens,
                cache_write_tokens=cache_write_tokens,
                reasoning_tokens=reasoning_tokens,
                credits=quantize_credits(credits) if credits is not None else Decimal(0),
                upstream_cost_usd=(
                    quantize_credits(upstream_cost_usd)
                    if upstream_cost_usd is not None
                    else Decimal(0)
                ),
                selected_model_id=selected_model_id,
            )
        await session.commit()
        return rowcount == 1


async def _rollup_settled_event(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    prompt_tokens: int,
    completion_tokens: int,
    cached_prompt_tokens: int,
    cache_write_tokens: int,
    reasoning_tokens: int,
    credits: Decimal,
    upstream_cost_usd: Decimal,
    selected_model_id: str | None,
) -> None:
    """Fold a freshly settled event into the daily cost rollup (upsert).

    Called inside the settle transaction so the rollup can never drift ahead of
    (or behind) the durable usage row.
    """
    event = await session.get(UsageEvent, event_id)
    if event is None:
        return
    day = event.created_at.date()
    stmt = pg_insert(CostDailyRollup).values(
        id=uuid.uuid4(),
        day=day,
        user_id=event.user_id,
        tier_alias=event.tier_alias,
        selected_model_id=selected_model_id,
        requests=1,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_prompt_tokens=cached_prompt_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        credits_charged=credits,
        upstream_cost_usd=upstream_cost_usd,
    )
    update_stmt = stmt.on_conflict_do_update(
        index_elements=["day", "user_id", "tier_alias", "selected_model_id"],
        set_={
            "requests": CostDailyRollup.requests + 1,
            "prompt_tokens": CostDailyRollup.prompt_tokens + prompt_tokens,
            "completion_tokens": CostDailyRollup.completion_tokens + completion_tokens,
            "cached_prompt_tokens": CostDailyRollup.cached_prompt_tokens
            + cached_prompt_tokens,
            "cache_write_tokens": CostDailyRollup.cache_write_tokens + cache_write_tokens,
            "reasoning_tokens": CostDailyRollup.reasoning_tokens + reasoning_tokens,
            "credits_charged": CostDailyRollup.credits_charged + credits,
            "upstream_cost_usd": CostDailyRollup.upstream_cost_usd + upstream_cost_usd,
        },
    )
    await session.execute(update_stmt)
