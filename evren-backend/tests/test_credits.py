from __future__ import annotations

import uuid
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


def test_token_cost_math() -> None:
    tier = make_tier()
    # 1000 prompt tokens * 1/1000 + 500 completion * 2/1000 = 1 + 1 = 2
    assert token_cost(tier, 1000, 500) == Decimal("2.000000")
    # fractional: 123 prompt * 1/1000 + 45 * 2/1000
    assert token_cost(tier, 123, 45) == Decimal("0.213000")


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
