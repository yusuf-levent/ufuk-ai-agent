"""Guards for the seeded tier/plan defaults.

Reasoning models spend the max_tokens budget on chain-of-thought before any
content is produced, so per-tier ceilings must stay generous
(fast/balanced 8192, strong 16384) and plan caps must never silently clamp
them below the tier ceiling.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seed.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("evren_seed_defaults", SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_tier_ceilings_match_reasoning_model_needs() -> None:
    seed = _load_seed_module()
    assert seed.DEFAULT_TIERS["fast"]["max_output_tokens"] == 8192
    assert (
        seed.DEFAULT_TIERS["fast"]["price_note"]
        == "Cheapest — for short questions and quick tasks"
    )
    assert (
        seed.DEFAULT_TIERS["fast"]["price_note_tr"]
        == "En ucuz — kısa sorular ve hızlı görevler için"
    )
    assert seed.DEFAULT_TIERS["balanced"]["max_output_tokens"] == 8192
    assert seed.DEFAULT_TIERS["strong"]["max_output_tokens"] == 16384
    assert (
        seed.DEFAULT_TIERS["strong"]["price_note"]
        == "Most powerful — complex tasks, more expensive"
    )
    assert (
        seed.DEFAULT_TIERS["strong"]["price_note_tr"]
        == "En güçlü — karmaşık görevler, daha pahalı"
    )


def test_seed_plan_caps_never_clamp_tier_ceilings() -> None:
    seed = _load_seed_module()
    for plan in seed.DEFAULT_PLANS.values():
        for alias in plan["allowed_tier_aliases"]:
            assert (
                plan["max_output_tokens_per_request"]
                >= seed.DEFAULT_TIERS[alias]["max_output_tokens"]
            ), f"plan cap would clamp tier '{alias}' below its ceiling"


def test_seed_plans_have_budget_kill_switch() -> None:
    """Every seeded plan must carry the sub-agent cost kill-switch: a
    per-request credit ceiling and a rolling-window ceiling."""
    seed = _load_seed_module()
    for name, plan in seed.DEFAULT_PLANS.items():
        assert plan["max_credits_per_request"] is not None, f"{name}: no per-request cap"
        assert plan["max_credits_per_window"] is not None, f"{name}: no window cap"
        assert plan["budget_window_seconds"] > 0, f"{name}: bad window"
        # The window cap must be at least one full request, otherwise the plan
        # could never make a single call.
        assert plan["max_credits_per_window"] >= plan["max_credits_per_request"], (
            f"{name}: window cap {plan['max_credits_per_window']} < "
            f"per-request cap {plan['max_credits_per_request']}"
        )


def test_seed_plans_have_concurrency_cap() -> None:
    """Every seeded plan must bound concurrent in-flight requests — the
    account-sharing blast-radius limiter."""
    seed = _load_seed_module()
    for name, plan in seed.DEFAULT_PLANS.items():
        assert plan["max_concurrent_requests"] is not None, f"{name}: no concurrency cap"
        assert plan["max_concurrent_requests"] >= 1, f"{name}: unusable concurrency cap"


def test_seed_user_facing_tiers_support_vision_and_tools() -> None:
    """Product rule: every user-facing tier must support image input AND tool
    calling. Text-only models are excluded from the picker."""
    seed = _load_seed_module()
    for alias, tier in seed.DEFAULT_TIERS.items():
        if tier.get("is_internal"):
            continue
        assert "image" in tier["output_modalities"] or "image" in (
            tier.get("input_modalities") or []
        ), f"{alias}: no image support"
        assert tier["supports_tools"] is True, f"{alias}: no tool calling"
        assert tier["pricing_unit"] == "token", f"{alias}: user tiers bill by token"


def test_seed_tier_rates_are_sane() -> None:
    """Credit rates must be positive and output must cost more than input
    (every upstream prices completion above prompt)."""
    seed = _load_seed_module()
    for alias, tier in seed.DEFAULT_TIERS.items():
        assert tier["input_credits_per_1k_tokens"] > 0, f"{alias}: non-positive input rate"
        assert tier["output_credits_per_1k_tokens"] > tier["input_credits_per_1k_tokens"], (
            f"{alias}: output cheaper than input"
        )
        assert tier["cache_read_multiplier"] <= 1, f"{alias}: cache read not a discount"


def test_seed_pricing_ladder() -> None:
    """The $10 / $100 / $30-per-seat ladder agreed with the product owner."""
    seed = _load_seed_module()
    plans = seed.DEFAULT_PLANS
    assert plans["free"]["price_usd"] == 0
    assert plans["plus"]["price_usd"] == 10
    assert plans["pro"]["price_usd"] == 100
    assert plans["team"]["price_usd"] == 30
    # Pro must grant meaningfully more than Plus (the 10x price jump buys far
    # more than 10x quota headroom in practice thanks to cache + cheap models).
    assert plans["pro"]["monthly_credit_limit"] > plans["plus"]["monthly_credit_limit"] * 10


def test_seed_has_auto_tier() -> None:
    """The product owner wants an Auto entry in the picker."""
    seed = _load_seed_module()
    assert "auto" in seed.DEFAULT_TIERS
    auto = seed.DEFAULT_TIERS["auto"]
    assert auto["routing_plugin"] == "auto-router"
    assert auto["fallback_model_ids"], "auto tier needs a pinned model set"


def test_seed_fallbacks_are_same_or_cheaper() -> None:
    """A fallback that costs MORE than its primary would let a transient error
    silently inflate the user's bill. Guard the seed against that.

    Compared in USD (per 1M in+out, live OpenRouter rates 2026-09-29) so every
    model sits on one scale — mixing credit rates (which carry a margin) with
    raw USD would be apples-to-oranges.
    """
    seed = _load_seed_module()
    usd_per_1m = {
        "qwen/qwen3.7-flash": 0.03 + 0.13,
        "deepseek/deepseek-v4.1-flash": 0.30 + 1.20,
        "google/gemma-4-31b-it": 0.09 + 0.34,
        "qwen/qwen3.8-flash": 0.15 + 0.47,
        "z-ai/glm-5.3-flash": 0.15 + 0.50,
        "xiaomi/mimo-v2.6-pro": 0.435 + 0.87,
        # Fallback-only models (not seeded tiers):
        "inclusionai/ling-3.0-flash-vl": 0.021 + 0.062,
    }
    for alias, tier in seed.DEFAULT_TIERS.items():
        if tier.get("routing_plugin"):
            continue  # router tiers pin a candidate set, not a fail-over chain
        primary = usd_per_1m.get(tier["upstream_model_id"])
        assert primary is not None, f"{alias}: no price for {tier['upstream_model_id']}"
        for fb in tier.get("fallback_model_ids", []):
            fb_cost = usd_per_1m.get(fb)
            assert fb_cost is not None, f"{alias}: unknown fallback {fb}"
            assert fb_cost <= primary, (
                f"{alias}: fallback {fb} (${fb_cost:.3f}) is pricier than "
                f"primary (${primary:.3f}) — would inflate the bill on errors"
            )


def test_seed_tiers_have_tooltip_metadata() -> None:
    """Every user-facing tier must carry tooltip metadata for the picker's
    ℹ️ hover card."""
    seed = _load_seed_module()
    for alias, tier in seed.DEFAULT_TIERS.items():
        if tier.get("is_internal"):
            continue
        assert tier.get("tooltip_title"), f"{alias}: no tooltip_title"
        assert tier.get("tooltip_body"), f"{alias}: no tooltip_body"
        assert tier.get("tooltip_best_for"), f"{alias}: no tooltip_best_for"
        for key in ("tooltip_cost_level", "tooltip_speed_level", "tooltip_quality_level"):
            val = tier.get(key)
            assert val is not None and 1 <= val <= 5, f"{alias}: bad {key}={val}"


def test_seed_plans_have_image_quota() -> None:
    """Every seeded plan must define an image quota (or explicitly disable
    image generation with 0)."""
    seed = _load_seed_module()
    for name, plan in seed.DEFAULT_PLANS.items():
        assert "monthly_image_quota" in plan, f"{name}: no monthly_image_quota"
        assert plan["monthly_image_quota"] >= 0, f"{name}: negative image quota"
