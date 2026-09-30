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


def token_cost(
    tier: TierView,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    cached_prompt_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """Credit cost for a settled request.

    Prompt tokens are billed in three disjoint buckets so prompt caching is
    priced accurately (and the user only pays the discounted rate for cached
    reads):

    * ``cached_prompt_tokens``  read from cache  -> ``in_rate * cache_read_multiplier``
    * ``cache_write_tokens``    written to cache -> ``in_rate * cache_write_multiplier``
    * the remainder (fresh)                      -> ``in_rate``

    Buckets are clamped so they never sum above ``prompt_tokens``; a provider
    that reports no cache info simply bills the whole prompt at the plain input
    rate (historical behaviour). Completion tokens are always billed at the
    plain output rate.
    """
    cached = max(0, min(cached_prompt_tokens, prompt_tokens))
    written = max(0, min(cache_write_tokens, prompt_tokens - cached))
    fresh = max(prompt_tokens - cached - written, 0)
    input_rate = tier.input_credits_per_1k_tokens
    cost = (
        Decimal(fresh) * input_rate
        + Decimal(cached) * input_rate * tier.cache_read_multiplier
        + Decimal(written) * input_rate * tier.cache_write_multiplier
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


class BudgetLedger:
    """Rolling-window credit budget — the sub-agent cost kill-switch.

    A nested sub-agent chain fires many LLM calls in a short burst. Each call
    is individually under ``max_credits_per_request``, so only a *window*
    budget stops the exponential blow-up. Fixed windows keyed by
    ``floor(now / window_seconds)``; the counter expires shortly after the
    window ends so memory stays bounded.
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def key(user_id: uuid.UUID, window_start: int) -> str:
        return f"budget:{user_id}:{window_start}"

    @staticmethod
    def window_start(window_seconds: int, *, now: float | None = None) -> int:
        import time

        moment = time.time() if now is None else now
        return int(moment // window_seconds) * window_seconds

    async def consume(
        self,
        *,
        user_id: uuid.UUID,
        amount: Decimal,
        limit: Decimal,
        window_seconds: int,
        now: float | None = None,
    ) -> None:
        """Atomically add ``amount`` to the current window; roll back and raise
        when the window budget would be exceeded."""
        start = self.window_start(window_seconds, now=now)
        key = self.key(user_id, start)
        value = Decimal(str(await self._redis.incrbyfloat(key, float(amount))))
        # Expire just after the window rolls over so a quiet user does not leak
        # keys; +5s grace avoids racing the boundary.
        await self._redis.expire(key, window_seconds + 5)
        if value > limit:
            await self._redis.incrbyfloat(key, -float(amount))
            raise ApiError(
                status_code=402,
                message="Burst budget exceeded — too many credits in a short window",
                type="insufficient_quota",
                code="window_budget_exceeded",
            )

    async def used(
        self, user_id: uuid.UUID, window_seconds: int, *, now: float | None = None
    ) -> Decimal:
        start = self.window_start(window_seconds, now=now)
        value = await self._redis.get(self.key(user_id, start))
        if value is None:
            return Decimal(0)
        return quantize_credits(Decimal(str(value)))
