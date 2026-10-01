from __future__ import annotations

import math
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


# ---------------------------------------------------------------------------
# Reasoning pricing — the anti-double-billing guarantee
#
# Upstreams count reasoning INSIDE completion_tokens, so reasoning is already
# billed at the plain output rate. The multiplier must therefore be a RELATIVE
# weight on that subset, never an extra charge on top of it.
# ---------------------------------------------------------------------------


def test_reasoning_default_multiplier_does_not_double_bill() -> None:
    """THE critical financial guarantee: with reasoning_multiplier=1.0 the cost
    must be byte-identical to ignoring reasoning entirely. If this ever fails,
    users are being charged twice for the same tokens."""
    tier = make_tier()  # reasoning_multiplier defaults to 1.0
    without = token_cost(tier, 1000, 500)
    with_reasoning = token_cost(tier, 1000, 500, reasoning_tokens=500)
    assert with_reasoning == without
    # Partial reasoning must also collapse to the same total.
    assert token_cost(tier, 1000, 500, reasoning_tokens=123) == without


def test_reasoning_premium_applies_only_to_reasoning_subset() -> None:
    tier = replace(make_tier(), reasoning_multiplier=Decimal("1.5"))
    # completion 500 = 300 visible + 200 reasoning
    #   visible  300 * 2/1000 = 0.6
    #   reasoning 200 * 2 * 1.5 / 1000 = 0.6
    #   prompt 1000 * 1/1000 = 1.0   -> total 2.2
    cost = token_cost(tier, 1000, 500, reasoning_tokens=200)
    assert cost == Decimal("2.200000")
    # Sanity: the premium is exactly (200 * 2 * 0.5)/1000 = 0.2 over the base.
    base = token_cost(make_tier(), 1000, 500, reasoning_tokens=200)
    assert cost - base == Decimal("0.200000")


def test_reasoning_clamped_to_completion_tokens() -> None:
    """Over-reported reasoning must never bill more than the completion total."""
    tier = replace(make_tier(), reasoning_multiplier=Decimal("2.0"))
    clamped = token_cost(tier, 1000, 500, reasoning_tokens=9999)
    full = token_cost(tier, 1000, 500, reasoning_tokens=500)
    assert clamped == full


def test_reasoning_negative_treated_as_zero() -> None:
    tier = replace(make_tier(), reasoning_multiplier=Decimal("2.0"))
    cost = token_cost(tier, 1000, 500, reasoning_tokens=-100)
    assert cost == token_cost(make_tier(), 1000, 500)


def test_reasoning_all_completion_is_reasoning() -> None:
    tier = replace(make_tier(), reasoning_multiplier=Decimal("1.5"))
    # completion 500, all reasoning: 500 * 2 * 1.5 / 1000 = 1.5
    # prompt 1000 * 1/1000 = 1.0  -> total 2.5
    cost = token_cost(tier, 1000, 500, reasoning_tokens=500)
    assert cost == Decimal("2.500000")


def test_reasoning_combined_with_cache_buckets() -> None:
    """Cache discounts and the reasoning premium compose without interfering."""
    tier = replace(
        make_tier(),
        cache_read_multiplier=Decimal("0.1"),
        cache_write_multiplier=Decimal("1.25"),
        reasoning_multiplier=Decimal("1.5"),
    )
    # prompt 1000 = 300 cached @0.1x + 200 written @1.25x + 500 fresh @1x
    #   = (30 + 250 + 500) / 1000 = 0.78
    # completion 500 = 300 visible + 200 reasoning @1.5x
    #   = (600 + 600) / 1000 = 1.2   -> total 1.98
    cost = token_cost(
        tier,
        1000,
        500,
        cached_prompt_tokens=300,
        cache_write_tokens=200,
        reasoning_tokens=200,
    )
    assert cost == Decimal("1.980000")


def test_tier_view_reasoning_multiplier_roundtrip() -> None:
    tier = replace(make_tier(), reasoning_multiplier=Decimal("1.5"))
    restored = TierView.from_dict(tier.as_dict())
    assert restored.reasoning_multiplier == Decimal("1.5")


def test_tier_view_reasoning_multiplier_stale_cache_defaults_neutral() -> None:
    data = make_tier().as_dict()
    del data["reasoning_multiplier"]
    restored = TierView.from_dict(data)
    assert restored.reasoning_multiplier == Decimal("1.0")


def test_tier_view_capability_fields_roundtrip() -> None:
    tier = replace(
        make_tier(),
        input_modalities=("text", "image"),
        output_modalities=("text", "image"),
        supports_tools=False,
        pricing_unit="image",
        max_images_per_request=4,
        is_internal=True,
    )
    restored = TierView.from_dict(tier.as_dict())
    assert restored.input_modalities == ("text", "image")
    assert restored.output_modalities == ("text", "image")
    assert restored.supports_tools is False
    assert restored.pricing_unit == "image"
    assert restored.max_images_per_request == 4
    assert restored.is_internal is True


def test_tier_view_capability_stale_cache_defaults() -> None:
    """Older Redis cache entries predate the capability columns; loading one
    must fall back to safe defaults (text output, tools on, token billing,
    public) instead of raising."""
    data = make_tier().as_dict()
    for key in (
        "input_modalities",
        "output_modalities",
        "supports_tools",
        "pricing_unit",
        "max_images_per_request",
        "is_internal",
    ):
        del data[key]
    restored = TierView.from_dict(data)
    assert restored.input_modalities == ("text",)
    assert restored.output_modalities == ("text",)
    assert restored.supports_tools is True
    assert restored.pricing_unit == "token"
    assert restored.max_images_per_request is None
    assert restored.is_internal is False


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
    # Unpadded tiktoken counts (o200k_base): this feeds real billing fallback,
    # so it must NOT carry the reservation safety margin.
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    # Repetitive runs compress hard under BPE (400 x's -> 50 tokens), which is
    # exactly why char/4 was the wrong estimator.
    assert estimate_tokens("x" * 400) == 50


def test_estimate_tokens_matches_tiktoken_without_margin() -> None:
    """Double-check: estimate_tokens == raw tiktoken count (no padding)."""
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    for text in ("hello world", "Merhaba dünya, bu bir test mesajıdır.", "x" * 400):
        assert estimate_tokens(text) == len(enc.encode(text, disallowed_special=()))


def test_estimate_messages_tokens_pads_reservation() -> None:
    """Double-check: the RESERVATION estimate carries the safety margin."""
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    text = "Merhaba dünya, bu bir test mesajıdır."
    messages = [{"role": "user", "content": text}]
    raw = len(enc.encode(text, disallowed_special=()))
    estimated = estimate_messages_tokens(messages)
    # margin + 4 tokens/message overhead
    assert estimated >= math.ceil(raw * 1.2)
    assert estimated <= math.ceil(raw * 1.2) + 4


def test_estimate_messages_tokens_turkish_underestimate_fixed() -> None:
    """Regression guard for the Turkish prose underestimate.

    The old char/4 heuristic under-counted Turkish by up to ~19%, so
    reservations came up short. The padded tiktoken estimate must land ABOVE
    the true token count for representative Turkish prose.
    """
    import tiktoken

    enc = tiktoken.get_encoding("o200k_base")
    tr = (
        "Uygulama katmani, kullanicinin istedigi gorevleri yerine getirmek icin bir dizi "
        "adimdan olusur. Ilk adimda baglam toplanir: proje dosyalari okunur, bagimliliklar "
        "incelenir ve kullanici talimatlari analiz edilir. Ikinci adimda model secimi "
        "yapilir; ucuz Cinli modeller varsayilandir ancak karmasik gorevler icin daha guclu "
        "modeller devreye girer. Ucuncu adimda alt ajanlar olusturulur ve her birine dar "
        "kapsamli gorevler verilir."
    )
    real = len(enc.encode(tr, disallowed_special=()))
    estimated = estimate_messages_tokens([{"role": "user", "content": tr}])
    assert estimated > real, f"reservation would under-count Turkish prose ({estimated} <= {real})"


def test_estimate_messages_tokens() -> None:
    messages = [
        {"role": "system", "content": "y" * 40},
        {"role": "user", "content": "z" * 60},
    ]
    estimated = estimate_messages_tokens(messages)
    assert estimated >= 25
    multimodal = [{"role": "user", "content": [{"type": "text", "text": "hello"}]}]
    assert estimate_messages_tokens(multimodal) >= 1


def test_estimate_messages_tokens_image_block_flat_budget() -> None:
    """Images get a flat budget — the old json.dumps path counted base64 bytes
    as text and inflated one screenshot into tens of thousands of tokens."""
    from app.services.credits import NON_TEXT_BLOCK_TOKENS

    base64ish = "A" * 200_000  # ~200k chars of base64, like a real screenshot
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look at this"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64ish}"}},
            ],
        }
    ]
    estimated = estimate_messages_tokens(messages)
    # Flat budget + text + per-message overhead, nowhere near 50k phantom tokens.
    assert estimated < NON_TEXT_BLOCK_TOKENS + 500
    assert estimated >= NON_TEXT_BLOCK_TOKENS


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


# ---------------------------------------------------------------------------
# BudgetLedger — the sub-agent cost kill-switch (rolling-window budget)
# ---------------------------------------------------------------------------


async def test_budget_ledger_accumulates_within_window(app: FastAPI) -> None:
    from app.services.credits import BudgetLedger

    ledger = BudgetLedger(app.state.redis)
    user_id = uuid.uuid4()
    now = 1_000_000.0

    await ledger.consume(
        user_id=user_id, amount=Decimal("5"), limit=Decimal("10"),
        window_seconds=300, now=now,
    )
    await ledger.consume(
        user_id=user_id, amount=Decimal("4"), limit=Decimal("10"),
        window_seconds=300, now=now + 10,
    )
    assert await ledger.used(user_id, 300, now=now + 20) == Decimal("9.000000")


async def test_budget_ledger_blocks_when_window_exceeded(app: FastAPI) -> None:
    from app.services.credits import BudgetLedger

    ledger = BudgetLedger(app.state.redis)
    user_id = uuid.uuid4()
    now = 2_000_000.0

    await ledger.consume(
        user_id=user_id, amount=Decimal("8"), limit=Decimal("10"),
        window_seconds=300, now=now,
    )
    with pytest.raises(ApiError) as excinfo:
        await ledger.consume(
            user_id=user_id, amount=Decimal("3"), limit=Decimal("10"),
            window_seconds=300, now=now + 5,
        )
    assert excinfo.value.status_code == 402
    assert excinfo.value.code == "window_budget_exceeded"
    # The rejected amount must be rolled back — no phantom burn.
    assert await ledger.used(user_id, 300, now=now + 10) == Decimal("8.000000")


async def test_budget_ledger_resets_across_windows(app: FastAPI) -> None:
    from app.services.credits import BudgetLedger

    ledger = BudgetLedger(app.state.redis)
    user_id = uuid.uuid4()
    now = 3_000_000.0

    await ledger.consume(
        user_id=user_id, amount=Decimal("10"), limit=Decimal("10"),
        window_seconds=300, now=now,
    )
    # Next window: budget is fresh again.
    await ledger.consume(
        user_id=user_id, amount=Decimal("10"), limit=Decimal("10"),
        window_seconds=300, now=now + 300,
    )
    assert await ledger.used(user_id, 300, now=now + 310) == Decimal("10.000000")


def test_budget_window_start_alignment() -> None:
    from app.services.credits import BudgetLedger

    # 1_000_000 // 300 = 3333 -> window starts at 999_900
    assert BudgetLedger.window_start(300, now=1_000_000.0) == 999_900
    # 1_000_100 // 300 = 3333 -> same window
    assert BudgetLedger.window_start(300, now=1_000_100.0) == 999_900
    # 1_000_200 // 300 = 3334 -> next window
    assert BudgetLedger.window_start(300, now=1_000_200.0) == 1_000_200
    # Two moments inside the same window share the key.
    assert BudgetLedger.window_start(300, now=1_000_000.0) == BudgetLedger.window_start(
        300, now=1_000_100.0
    )
