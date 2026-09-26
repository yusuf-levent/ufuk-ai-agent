from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "derive_credit_rates",
    Path(__file__).resolve().parents[1] / "scripts" / "derive_credit_rates.py",
)
assert _spec is not None and _spec.loader is not None
derive_credit_rates = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(derive_credit_rates)


def test_formula_matches_documented_rule() -> None:
    # rates = usd_per_1m / 1000 * credits_per_usd * (1 + margin)
    in_rate, out_rate = derive_credit_rates.derive_rates(
        Decimal("0.15"),
        Decimal("0.60"),
        margin=Decimal("0.3"),
        credits_per_usd=Decimal("1000"),
    )
    assert in_rate == Decimal("0.195000")
    assert out_rate == Decimal("0.780000")


def test_quantization_and_zero_margin() -> None:
    in_rate, out_rate = derive_credit_rates.derive_rates(
        Decimal("1"),
        Decimal("3"),
        margin=Decimal("0"),
        credits_per_usd=Decimal("1000"),
    )
    assert in_rate == Decimal("1.000000")
    assert out_rate == Decimal("3.000000")

    # rounding to the credit quantum used by the gateway (6 decimals, HALF_UP)
    in_rate, _ = derive_credit_rates.derive_rates(
        Decimal("0.0000011"),
        Decimal("1"),
        margin=Decimal("0"),
        credits_per_usd=Decimal("1"),
    )
    assert in_rate == Decimal("0.000000")  # 0.0000000011 rounds away below the quantum
