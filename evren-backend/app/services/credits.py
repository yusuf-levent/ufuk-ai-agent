from __future__ import annotations

import json
import math
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
    reasoning_tokens: int = 0,
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
    rate (historical behaviour).

    Completion tokens are split into a reasoning subset and a visible subset.
    Upstreams already count reasoning INSIDE ``completion_tokens``, so the
    reasoning portion is *moved* into its own term rather than added on top —
    this is what prevents double billing:

        visible  = completion - reasoning   -> ``out_rate``
        reasoning (clamped to completion)   -> ``out_rate * reasoning_multiplier``

    With the default ``reasoning_multiplier`` of 1.0 the two terms collapse
    back into ``completion * out_rate`` — exactly today's cost.
    """
    cached = max(0, min(cached_prompt_tokens, prompt_tokens))
    written = max(0, min(cache_write_tokens, prompt_tokens - cached))
    fresh = max(prompt_tokens - cached - written, 0)
    reasoning = max(0, min(reasoning_tokens, completion_tokens))
    visible = max(completion_tokens - reasoning, 0)
    input_rate = tier.input_credits_per_1k_tokens
    output_rate = tier.output_credits_per_1k_tokens
    cost = (
        Decimal(fresh) * input_rate
        + Decimal(cached) * input_rate * tier.cache_read_multiplier
        + Decimal(written) * input_rate * tier.cache_write_multiplier
        + Decimal(visible) * output_rate
        + Decimal(reasoning) * output_rate * tier.reasoning_multiplier
    ) / Decimal(1000)
    return quantize_credits(cost)


def reserve_amount(tier: TierView, estimated_prompt_tokens: int, max_output_tokens: int) -> Decimal:
    amount = (
        Decimal(estimated_prompt_tokens) * tier.input_credits_per_1k_tokens
        + Decimal(max_output_tokens) * tier.output_credits_per_1k_tokens
    ) / Decimal(1000)
    return quantize_credits(amount)


# ---------------------------------------------------------------------------
# Token estimation (pre-reservation only — settlement always uses the
# upstream's native tokenizer count).
#
# `tiktoken` (o200k_base) is the industry-standard estimator (OpenAI ships it).
# Measured against real agent payloads it lands within a few percent for code
# and English, but UNDER-estimates Turkish prose by up to ~19% (agglutinative
# morphology fragments into many tokens). A flat safety margin keeps the
# reservation on the safe side: over-reserving is corrected at settlement,
# under-reserving would let a request slip past its budget.
#
# tiktoken downloads its BPE file on first use; if that fails (offline boot,
# restricted egress) we degrade to the historical char/4 heuristic rather than
# failing the request.
# ---------------------------------------------------------------------------

#: Reservation safety margin. 1.2 = estimate 20% high on purpose. Applied ONLY
#: to pre-reservations (which are corrected at settlement) — never to the
#: fallback used for real billing, where padding would overcharge the user.
TOKEN_SAFETY_MARGIN = 1.2

#: Conservative per-block budget for non-text content (images, files). Real
#: image tokenization is model-specific (tiles/resolution); a flat budget beats
#: the old behaviour of `json.dumps`-ing base64 blobs, which inflated a single
#: screenshot into tens of thousands of phantom tokens.
NON_TEXT_BLOCK_TOKENS = 1024

_encoder: object | None = None
_encoder_unavailable = False


def _get_encoder() -> object | None:
    """Lazy tiktoken encoder; None means "fall back to the char heuristic"."""
    global _encoder, _encoder_unavailable
    if _encoder is not None:
        return _encoder
    if _encoder_unavailable:
        return None
    try:
        import tiktoken

        _encoder = tiktoken.get_encoding("o200k_base")
        return _encoder
    except Exception:
        _encoder_unavailable = True
        return None


def _apply_margin(raw: int) -> int:
    return max(1, math.ceil(raw * TOKEN_SAFETY_MARGIN))


def estimate_tokens(text: str) -> int:
    """Approximate token count for a text blob.

    Deliberately UNPADDED: this feeds the settlement fallback when an upstream
    response carries no usage numbers, i.e. it becomes the amount the user is
    actually charged. Padding here would silently overcharge; the safety margin
    belongs to reservations only (see ``estimate_messages_tokens``).
    """
    if not text:
        return 1
    encoder = _get_encoder()
    if encoder is not None:
        # `disallowed_special=()` keeps literal special-token text (e.g. a code
        # sample containing "<|end|>") from raising.
        raw = len(encoder.encode(text, disallowed_special=()))  # type: ignore[attr-defined]
    else:
        raw = (len(text) + 3) // 4
    return max(1, raw)


def estimate_messages_tokens(messages: list[dict[str, object]]) -> int:
    """Approximate prompt size for a chat payload (pre-reservation only).

    Padded by TOKEN_SAFETY_MARGIN: over-reserving is corrected at settlement,
    under-reserving would let a request slip past its budget. Text content is
    tokenized; non-text blocks (images, files, unknown types) get a flat
    conservative budget each. The old implementation serialized multimodal
    blocks with `json.dumps`, which counted base64 image bytes as if they were
    text and massively over-reserved for screenshot-heavy requests.
    """
    text_chars = 0
    non_text_blocks = 0
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            text_chars += len(content)
            continue
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_chars += len(str(block.get("text", "")))
                    else:
                        non_text_blocks += 1
                else:
                    non_text_blocks += 1
            continue
        if content is not None:
            text_chars += len(json.dumps(content))

    encoder = _get_encoder()
    if encoder is not None and text_chars:
        # Reconstruct only the textual mass; tokenizing char-by-char per message
        # would lose cross-message merges, so we tokenize the concatenation.
        raw_text = _collect_text(messages)
        text_tokens = len(encoder.encode(raw_text, disallowed_special=()))  # type: ignore[attr-defined]
    else:
        text_tokens = (text_chars + 3) // 4
    total = (
        _apply_margin(text_tokens)
        + non_text_blocks * NON_TEXT_BLOCK_TOKENS
        + 4 * len(messages)
    )
    return max(1, total)


def _collect_text(messages: list[dict[str, object]]) -> str:
    """Concatenate every textual fragment so tiktoken can merge across blocks."""
    parts: list[str] = []
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
        elif content is not None:
            parts.append(json.dumps(content))
    return "".join(parts)


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
