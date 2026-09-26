from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from redis.asyncio import Redis
from sqlalchemy import func, select

from app.db import Database
from app.errors import ApiError
from app.models import UsageEvent
from app.models.enums import UsageStatus
from app.services.tiers import TierView

CREDIT_QUANTUM = Decimal("0.000001")


def quantize_credits(value: Decimal) -> Decimal:
    return value.quantize(CREDIT_QUANTUM, rounding=ROUND_HALF_UP)


def token_cost(tier: TierView, prompt_tokens: int, completion_tokens: int) -> Decimal:
    cost = (
        Decimal(prompt_tokens) * tier.input_credits_per_1k_tokens
        + Decimal(completion_tokens) * tier.output_credits_per_1k_tokens
    ) / Decimal(1000)
    return quantize_credits(cost)


def reserve_amount(tier: TierView, estimated_prompt_tokens: int, max_output_tokens: int) -> Decimal:
    amount = (
        Decimal(estimated_prompt_tokens) * tier.input_credits_per_1k_tokens
        + Decimal(max_output_tokens) * tier.output_credits_per_1k_tokens
    ) / Decimal(1000)
    return quantize_credits(amount)


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def estimate_messages_tokens(messages: list[dict[str, object]]) -> int:
    total_chars = 0
    for message in messages:
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content) if content is not None else ""
        total_chars += len(content)
    return max(1, (total_chars + 3) // 4 + 4 * len(messages))


class CreditLedger:
    """Atomic in-memory (Redis) reservation ledger for the current period.

    DB usage_events rows are the durable record; this ledger only prevents
    concurrent requests from overspending between reserve and settle.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def key(user_id: uuid.UUID, period_key: str) -> str:
        return f"credits:{user_id}:{period_key}"

    async def reserve(
        self,
        *,
        user_id: uuid.UUID,
        period_key: str,
        amount: Decimal,
        limit: Decimal,
    ) -> None:
        key = self.key(user_id, period_key)
        value = Decimal(str(await self._redis.incrbyfloat(key, float(amount))))
        if value > limit:
            await self._redis.incrbyfloat(key, -float(amount))
            raise ApiError(
                status_code=402,
                message="Credit quota exceeded for the current billing period",
                type="insufficient_quota",
                code="quota_exceeded",
            )

    async def adjust(self, *, user_id: uuid.UUID, period_key: str, delta: Decimal) -> None:
        if delta == 0:
            return
        await self._redis.incrbyfloat(self.key(user_id, period_key), float(delta))

    async def release(self, *, user_id: uuid.UUID, period_key: str, amount: Decimal) -> None:
        await self.adjust(user_id=user_id, period_key=period_key, delta=-amount)

    async def used(self, user_id: uuid.UUID, period_key: str) -> Decimal:
        value = await self._redis.get(self.key(user_id, period_key))
        if value is None:
            return Decimal(0)
        return quantize_credits(Decimal(str(value)))


async def ensure_ledger_synced(
    db: Database,
    redis: Redis,
    *,
    user_id: uuid.UUID,
    period_key: str,
    period_start: datetime,
    period_end: datetime,
    ttl_seconds: int,
) -> Decimal:
    """Rebuild the Redis ledger from durable rows if the key is missing."""
    key = CreditLedger.key(user_id, period_key)
    existing = await redis.get(key)
    if existing is not None:
        return Decimal(str(existing))
    async with db.session() as session:
        total = await session.scalar(
            select(func.coalesce(func.sum(UsageEvent.credits_charged), 0)).where(
                UsageEvent.user_id == user_id,
                UsageEvent.created_at >= period_start,
                UsageEvent.created_at < period_end,
                UsageEvent.status.in_([UsageStatus.RESERVED, UsageStatus.SETTLED]),
            )
        )
    value = quantize_credits(Decimal(total or 0))
    await redis.set(key, str(value), ex=ttl_seconds)
    return value
