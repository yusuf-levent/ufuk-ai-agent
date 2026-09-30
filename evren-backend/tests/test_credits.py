from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal

import pytest
from app.errors import ApiError
from app.services.credits import (
    CreditLedger,
    estimate_messages_tokens,
    estimate_tokens,
    quantize_credits,
    reserve_amount,
    token_cost,
)
from app.services.tiers import TierView
from fastapi import FastAPI


def make_tier() -> TierView:
    return TierView(
        alias="fast",
        display_name="Fast",
        upstream_model_id="model-x",
        upstream_provider_name="provider",
        input_credits_per_1k_tokens=Decimal("1.000000"),
        output_credits_per_1k_tokens=Decimal("2.000000"),
        max_output_tokens=1024,
        context_window=128000,
    )


def test_tier_view_cache_multipliers_default_neutral() -> None:
    tier = make_tier()
    assert tier.cache_read_multiplier == Decimal("1.0")
    assert tier.cache_write_multiplier == Decimal("1.0")


def test_tier_view_cache_multipliers_roundtrip() -> None:
    tier = replace(
        make_tier(),
        cache_read_multiplier=Decimal("0.1"),
        cache_write_multiplier=Decimal("1.25"),
    )
    restored = TierView.from_dict(tier.as_dict())
    assert restored.cache_read_multiplier == Decimal("0.1")
    assert restored.cache_write_multiplier == Decimal("1.25")


def test_tier_view_from_dict_tolerates_stale_cache_entry() -> None:
    """Older Redis cache entries predate the cache multipliers; loading one
    must fall back to neutral values instead of raising."""
    data = make_tier().as_dict()
    del data["cache_read_multiplier"]
    del data["cache_write_multiplier"]
    restored = TierView.from_dict(data)
    assert restored.cache_read_multiplier == Decimal("1.0")
    assert restored.cache_write_multiplier == Decimal("1.0")


def test_token_cost_math() -> None:
    tier = make_tier()
    # 1000 prompt tokens * 1/1000 + 500 completion * 2/1000 = 1 + 1 = 2
    assert token_cost(tier, 1000, 500) == Decimal("2.000000")
    # fractional: 123 prompt * 1/1000 + 45 * 2/1000
    assert token_cost(tier, 123, 45) == Decimal("0.213000")


def test_token_cost_without_cache_info_is_unchanged() -> None:
    """A provider that reports no cache buckets bills the whole prompt at the
    plain input rate (historical behaviour)."""
    tier = make_tier()
    assert token_cost(tier, 1000, 500) == token_cost(
        tier, 1000, 500, cached_prompt_tokens=0, cache_write_tokens=0
    )


def test_token_cost_cached_reads_use_read_multiplier() -> None:
    tier = replace(make_tier(), cache_read_multiplier=Decimal("0.1"))
    # 1000 prompt: 500 cached @ 0.1x + 500 fresh @ 1x
    #   = (500 * 1 * 0.1 + 500 * 1) / 1000 = 0.55
    # completion 500 * 2/1000 = 1  -> total 1.55
    cost = token_cost(tier, 1000, 500, cached_prompt_tokens=500)
    assert cost == Decimal("1.550000")


def test_token_cost_cache_writes_use_write_multiplier() -> None:
    tier = replace(make_tier(), cache_write_multiplier=Decimal("1.25"))
    # 1000 prompt: 200 written @ 1.25x + 800 fresh @ 1x
    #   = (200 * 1 * 1.25 + 800 * 1) / 1000 = 1.05
    # completion 500 * 2/1000 = 1  -> total 2.05
    cost = token_cost(tier, 1000, 500, cache_write_tokens=200)
    assert cost == Decimal("2.050000")


def test_token_cost_all_three_buckets() -> None:
    tier = replace(
        make_tier(),
        cache_read_multiplier=Decimal("0.1"),
        cache_write_multiplier=Decimal("1.25"),
    )
    # 1000 prompt: 300 cached @ 0.1x + 200 written @ 1.25x + 500 fresh @ 1x
    #   = (300 * 0.1 + 200 * 1.25 + 500 * 1) / 1000 = 0.78
    # completion 500 * 2/1000 = 1  -> total 1.78
    cost = token_cost(
        tier, 1000, 500, cached_prompt_tokens=300, cache_write_tokens=200
    )
    assert cost == Decimal("1.780000")


def test_token_cost_buckets_clamped_to_prompt_total() -> None:
    """Over-reported cache buckets must never bill more than the prompt total."""
    tier = replace(
        make_tier(),
        cache_read_multiplier=Decimal("0.1"),
        cache_write_multiplier=Decimal("1.25"),
    )
    # cached=800 + written=800 > prompt=1000 -> clamp: cached=800, written=200
    cost = token_cost(
        tier, 1000, 500, cached_prompt_tokens=800, cache_write_tokens=800
    )
    expected = token_cost(tier, 1000, 500, cached_prompt_tokens=800, cache_write_tokens=200)
    assert cost == expected


def test_token_cost_negative_buckets_treated_as_zero() -> None:
    tier = make_tier()
    cost = token_cost(tier, 1000, 500, cached_prompt_tokens=-5, cache_write_tokens=-5)
    assert cost == token_cost(tier, 1000, 500)


def test_token_cost_quantized_to_six_decimals() -> None:
    tier = make_tier()
    cost = token_cost(tier, 1, 1)
    assert cost == Decimal("0.003000")
    assert -cost.as_tuple().exponent <= 6


def test_reserve_amount_uses_max_output() -> None:
    tier = make_tier()
    # est prompt 100 * 1/1000 + 1024 * 2/1000 = 0.1 + 2.048
    assert reserve_amount(tier, 100, 1024) == Decimal("2.148000")


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("x" * 400) == 100


def test_estimate_messages_tokens() -> None:
    messages = [
        {"role": "system", "content": "y" * 40},
        {"role": "user", "content": "z" * 60},
    ]
    estimated = estimate_messages_tokens(messages)
    assert estimated >= 25
    multimodal = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    assert estimate_messages_tokens(multimodal) >= 1


def test_sse_scanner_captures_cache_details() -> None:
    from app.routers.gateway import SseUsageScanner

    scanner = SseUsageScanner()
    scanner.feed_line(
        b'data: {"usage": {"prompt_tokens": 100, "completion_tokens": 10, '
        b'"prompt_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 20}}}'
    )
    assert scanner.prompt_tokens == 100
    assert scanner.completion_tokens == 10
    assert scanner.cached_prompt_tokens == 60
    assert scanner.cache_write_tokens == 20
    assert scanner.usage_seen is True


def test_sse_scanner_cache_details_default_zero() -> None:
    from app.routers.gateway import SseUsageScanner

    scanner = SseUsageScanner()
    scanner.feed_line(b'data: {"usage": {"prompt_tokens": 5, "completion_tokens": 2}}')
    assert scanner.cached_prompt_tokens == 0
    assert scanner.cache_write_tokens == 0


async def test_ledger_reserve_and_quota(app: FastAPI) -> None:
    ledger = CreditLedger(app.state.redis)
    user_id = uuid.uuid4()
    period = "2026-09-01"

    await ledger.reserve(
        user_id=user_id, period_key=period, amount=Decimal("5"), limit=Decimal("10")
    )
    assert await ledger.used(user_id, period) == Decimal("5.000000")

    with pytest.raises(ApiError) as excinfo:
        await ledger.reserve(
            user_id=user_id, period_key=period, amount=Decimal("6"), limit=Decimal("10")
        )
    assert excinfo.value.status_code == 402
    assert excinfo.value.code == "quota_exceeded"
    assert await ledger.used(user_id, period) == Decimal("5.000000")


async def test_ledger_release_and_adjust(app: FastAPI) -> None:
    ledger = CreditLedger(app.state.redis)
    user_id = uuid.uuid4()
    period = "2026-09-02"

    await ledger.reserve(
        user_id=user_id, period_key=period, amount=Decimal("5"), limit=Decimal("10")
    )
    await ledger.release(user_id=user_id, period_key=period, amount=Decimal("2"))
    assert await ledger.used(user_id, period) == Decimal("3.000000")
    await ledger.adjust(user_id=user_id, period_key=period, delta=Decimal("0.5"))
    assert await ledger.used(user_id, period) == Decimal("3.500000")


async def test_ledger_missing_key_is_zero(app: FastAPI) -> None:
    ledger = CreditLedger(app.state.redis)
    assert await ledger.used(uuid.uuid4(), "2026-09-03") == Decimal("0.000000")


async def test_ensure_ledger_synced_rebuilds_from_db(app: FastAPI) -> None:
    from datetime import UTC, datetime, timedelta

    from app.services.credits import ensure_ledger_synced

    database = app.state.database
    from app.models import UsageEvent
    from app.models.enums import UsageStatus

    user_id = uuid.uuid4()
    from tests.helpers import create_user

    db_user = await create_user(app, "ledger@example.com")
    user_id = db_user.id
    period_start = datetime.now(UTC) - timedelta(minutes=1)
    period_end = period_start + timedelta(days=30)
    async with database.session() as session:
        session.add(
            UsageEvent(
                request_id=uuid.uuid4(),
                user_id=user_id,
                tier_alias="fast",
                upstream_model_id="model-x",
                prompt_tokens=1000,
                completion_tokens=500,
                credits_charged=Decimal("2.000000"),
                status=UsageStatus.SETTLED,
            )
        )
        await session.commit()

    period_key = period_start.date().isoformat()
    value = await ensure_ledger_synced(
        database,
        app.state.redis,
        user_id=user_id,
        period_key=period_key,
        period_start=period_start,
        period_end=period_end,
        ttl_seconds=3600,
    )
    assert value == Decimal("2.000000")
    ledger = CreditLedger(app.state.redis)
    assert await ledger.used(user_id, period_key) == Decimal("2.000000")


def test_quantize_credits_rounds_half_up() -> None:
    assert quantize_credits(Decimal("1.0000005")) == Decimal("1.000001")
    assert quantize_credits(Decimal("1.0000004")) == Decimal("1.000000")
