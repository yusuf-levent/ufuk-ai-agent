"""Seed default plans and model tiers.

Idempotent: existing rows are kept unless --force is passed.
Upstream model ids can be overridden with env vars when the upstream changes.

Usage (from the backend root):
    python scripts/seed.py [--force]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import Database
from app.models import ModelTier, Plan
from sqlalchemy import select

PROVIDER = os.environ.get("SEED_PROVIDER", "evren-llmapi")

# Upstream model ids verified against GET /v1/models on OpenRouter
# (2026-09-29). Every user-facing tier MUST support image input AND tool
# calling — text-only models are excluded by product decision (the picker
# promises vision + tools on every entry).
#
# Credit rates are derived from live OpenRouter prices with
# `python scripts/derive_credit_rates.py --source openrouter` (margin 0.3,
# 1000 credits per USD). Cache multipliers are the provider's live
# `input_cache_read` / `input_cache_write` divided by the prompt price.
#
# `price_note` is manually curated (never auto-derived): it reflects this
# gateway's credit pricing, not upstream USD prices. `price_note` is the
# English (default) variant; `price_note_tr` holds the Turkish translation.
DEFAULT_TIERS = {
    "fast": {
        "display_name": "Qwen 3.7 Flash",
        "upstream_model_id": os.environ.get("SEED_FAST_MODEL", "qwen/qwen3.7-flash"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.039"),
        "output_credits_per_1k_tokens": Decimal("0.169"),
        # Live OpenRouter ratios (2026-10-01): qwen3.7-flash cache read is 0.2x
        # and cache WRITE is 1.27x the prompt price — charging 1.0x for writes
        # would sell below cost.
        "cache_read_multiplier": Decimal("0.2"),
        "cache_write_multiplier": Decimal("1.27"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 8192,
        "context_window": 1000000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        # Same-or-cheaper only (live USD, 2026-09-29): ling-3.0-flash-vl is
        # $0.083/1M in+out vs this tier's $0.16. A pricier fallback would
        # silently inflate the bill whenever the primary errors.
        "fallback_model_ids": ["inclusionai/ling-3.0-flash-vl"],
        "routing_plugin": None,
        "price_note": "Cheapest — for short questions and quick tasks",
        "price_note_tr": "En ucuz — kısa sorular ve hızlı görevler için",
        "tooltip_title": "Qwen 3.7 Flash",
        "tooltip_body": "En ucuz seçenek. Kısa sorular ve hızlı görevler için ideal. "
        "Uzun sohbetlerde önbellek sayesinde daha da ucuzlar.",
        "tooltip_cost_level": 1,
        "tooltip_speed_level": 5,
        "tooltip_quality_level": 2,
        "tooltip_best_for": "Kısa sorular, hızlı görevler, günlük kullanım",
        "speed_hint": 5,
        "quality_hint": 2,
    },
    "fast2": {
        "display_name": "DeepSeek V4.1 Flash",
        "upstream_model_id": os.environ.get("SEED_FAST2_MODEL", "deepseek/deepseek-v4.1-flash"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.39"),
        "output_credits_per_1k_tokens": Decimal("1.56"),
        # Live OpenRouter ratios (2026-10-01): deepseek-v4.1-flash cache read is
        # 0.333x the prompt price (no write premium). The earlier 0.02x guess
        # was 16x too generous and sold cached prompts below cost.
        "cache_read_multiplier": Decimal("0.333"),
        "cache_write_multiplier": Decimal("1.0"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 8192,
        "context_window": 1048576,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        "fallback_model_ids": ["qwen/qwen3.7-flash", "google/gemma-4-31b-it"],
        "routing_plugin": None,
        "price_note": "Cheap and fast, supports image input",
        "price_note_tr": "Ucuz ve hızlı, görsel girdi destekli",
        "tooltip_title": "DeepSeek V4.1 Flash",
        "tooltip_body": "Ucuz ve hızlı. Görsel girdi destekli. "
        "Kısa sorular ve hızlı görevler için ideal.",
        "tooltip_cost_level": 1,
        "tooltip_speed_level": 5,
        "tooltip_quality_level": 3,
        "tooltip_best_for": "Kısa sorular, hızlı görevler, görsel analiz",
        "speed_hint": 5,
        "quality_hint": 3,
    },
    "balanced": {
        "display_name": "Gemma 4 31B",
        "upstream_model_id": os.environ.get("SEED_BALANCED_MODEL", "google/gemma-4-31b-it"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.117"),
        "output_credits_per_1k_tokens": Decimal("0.442"),
        "cache_read_multiplier": Decimal("0.556"),
        "cache_write_multiplier": Decimal("1.0"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 8192,
        "context_window": 262144,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        "fallback_model_ids": ["qwen/qwen3.7-flash"],
        "routing_plugin": None,
        "price_note": "Balanced — good choice for daily use",
        "price_note_tr": "Dengeli — günlük kullanım için iyi seçim",
        "tooltip_title": "Gemma 4 31B",
        "tooltip_body": "Dengeli — günlük kullanım için iyi seçim. Görsel ve video girdi destekli.",
        "tooltip_cost_level": 2,
        "tooltip_speed_level": 4,
        "tooltip_quality_level": 3,
        "tooltip_best_for": "Günlük kodlama, refactor, genel görevler",
        "speed_hint": 4,
        "quality_hint": 3,
    },
    "balanced2": {
        "display_name": "Qwen 3.8 Flash",
        "upstream_model_id": os.environ.get("SEED_BALANCED2_MODEL", "qwen/qwen3.8-flash"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.195"),
        "output_credits_per_1k_tokens": Decimal("0.611"),
        "cache_read_multiplier": Decimal("0.107"),
        "cache_write_multiplier": Decimal("1.33"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 8192,
        "context_window": 1000000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        "fallback_model_ids": ["google/gemma-4-31b-it", "qwen/qwen3.7-flash"],
        "routing_plugin": None,
        "price_note": "Balanced, supports image input",
        "price_note_tr": "Dengeli, görsel girdi destekli",
        "tooltip_title": "Qwen 3.8 Flash",
        "tooltip_body": "Dengeli — günlük kullanım için iyi seçim. "
        "Görsel ve video girdi destekli. "
        "Uzun sohbetlerde önbellek sayesinde daha da ucuzlar.",
        "tooltip_cost_level": 2,
        "tooltip_speed_level": 4,
        "tooltip_quality_level": 3,
        "tooltip_best_for": "Günlük kodlama, refactor, görsel analiz",
        "speed_hint": 4,
        "quality_hint": 3,
    },
    "strong": {
        "display_name": "GLM 5.3 Flash",
        "upstream_model_id": os.environ.get("SEED_STRONG_MODEL", "z-ai/glm-5.3-flash"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.195"),
        "output_credits_per_1k_tokens": Decimal("0.65"),
        "cache_read_multiplier": Decimal("0.2"),
        "cache_write_multiplier": Decimal("1.0"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 16384,
        "context_window": 1310720,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        # Same-or-cheaper only (live USD): qwen3.8-flash $0.62 vs this tier's
        # $0.65. MiMo ($1.305) would be 2x pricier and inflate bills on errors.
        "fallback_model_ids": ["qwen/qwen3.8-flash", "google/gemma-4-31b-it"],
        "routing_plugin": None,
        "price_note": "Most powerful — complex tasks, more expensive",
        "price_note_tr": "En güçlü — karmaşık görevler, daha pahalı",
        "tooltip_title": "GLM 5.3 Flash",
        "tooltip_body": "En güçlü — karmaşık görevler, daha pahalı. "
        "Mimari kararlar, zor hata ayıklama, kritik refactor için.",
        "tooltip_cost_level": 3,
        "tooltip_speed_level": 2,
        "tooltip_quality_level": 5,
        "tooltip_best_for": "Mimari kararlar, zor hata ayıklama, kritik refactor",
        "speed_hint": 2,
        "quality_hint": 5,
    },
    "strong2": {
        "display_name": "MiMo v2.6 Pro",
        "upstream_model_id": os.environ.get("SEED_STRONG2_MODEL", "xiaomi/mimo-v2.6-pro"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.5655"),
        "output_credits_per_1k_tokens": Decimal("1.131"),
        "cache_read_multiplier": Decimal("0.0083"),
        "cache_write_multiplier": Decimal("1.0"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 16384,
        "context_window": 1050000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        "fallback_model_ids": ["z-ai/glm-5.3-flash", "qwen/qwen3.8-flash"],
        "routing_plugin": None,
        "price_note": "Powerful, long reasoning and image input",
        "price_note_tr": "Güçlü, uzun akıl yürütme ve görsel girdi destekli",
        "tooltip_title": "MiMo v2.6 Pro",
        "tooltip_body": "Güçlü, uzun akıl yürütme ve görsel girdi destekli. "
        "Karmaşık görevler için. "
        "Uzun sohbetlerde önbellek sayesinde daha da ucuzlar.",
        "tooltip_cost_level": 3,
        "tooltip_speed_level": 2,
        "tooltip_quality_level": 4,
        "tooltip_best_for": "Karmaşık görevler, uzun akıl yürütme, görsel analiz",
        "speed_hint": 2,
        "quality_hint": 4,
    },
    "auto": {
        "display_name": "Auto",
        "upstream_model_id": os.environ.get("SEED_AUTO_MODEL", "openrouter/auto"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.195"),
        "output_credits_per_1k_tokens": Decimal("0.611"),
        "cache_read_multiplier": Decimal("0.1"),
        "cache_write_multiplier": Decimal("1.0"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 16384,
        "context_window": 1000000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        # The router may only pick from this cheap, vision+tool capable set —
        # `allowed_models` is pinned to it server-side (see UpstreamClient).
        "fallback_model_ids": [
            "qwen/qwen3.7-flash",
            "qwen/qwen3.8-flash",
            "google/gemma-4-31b-it",
        ],
        "routing_plugin": "auto-router",
        "price_note": "Recommended — picks the best model for your task",
        "price_note_tr": "Önerilen — görevin için en uygun modeli seçer",
        "tooltip_title": "Auto",
        "tooltip_body": "Önerilen — görevin için en uygun modeli otomatik seçer. "
        "Hangi modeli kullanacağına kendin karar vermek istemiyorsan bunu seç.",
        "tooltip_cost_level": 2,
        "tooltip_speed_level": 4,
        "tooltip_quality_level": 4,
        "tooltip_best_for": "Her şey — otomatik model seçimi",
        "speed_hint": 4,
        "quality_hint": 4,
    },
}

ALL_TIERS = ["fast", "fast2", "balanced", "balanced2", "strong", "strong2", "auto"]

DEFAULT_PLANS = {
    "free": {
        "monthly_credit_limit": Decimal("100"),
        "max_output_tokens_per_request": 8192,
        "requests_per_minute": 10,
        # Sub-agent cost kill-switch: one call may never reserve more than 5
        # credits, and a 5-minute burst may never burn more than 20.
        "max_credits_per_request": Decimal("5"),
        "max_credits_per_window": Decimal("20"),
        "budget_window_seconds": 300,
        "max_concurrent_requests": 2,
        "monthly_image_quota": 5,
        "allowed_tier_aliases": ["fast"],
        "is_default": True,
        "price_usd": Decimal("0"),
        "provider_price_id": None,
    },
    "plus": {
        "monthly_credit_limit": Decimal("2500"),
        "max_output_tokens_per_request": 16384,
        "requests_per_minute": 60,
        "max_credits_per_request": Decimal("50"),
        "max_credits_per_window": Decimal("250"),
        "budget_window_seconds": 300,
        "max_concurrent_requests": 3,
        "monthly_image_quota": 50,
        "allowed_tier_aliases": ALL_TIERS,
        "is_default": False,
        "price_usd": Decimal("10"),
        # Set to the provider's price/product id (Stripe `price_...`, Dodo
        # `pdt_...`, Paddle `pri_...`) to make this plan purchasable.
        "provider_price_id": None,
    },
    "pro": {
        "monthly_credit_limit": Decimal("30000"),
        "max_output_tokens_per_request": 16384,
        "requests_per_minute": 120,
        "max_credits_per_request": Decimal("500"),
        "max_credits_per_window": Decimal("3000"),
        "budget_window_seconds": 300,
        "max_concurrent_requests": 8,
        "monthly_image_quota": 500,
        "allowed_tier_aliases": ALL_TIERS,
        "is_default": False,
        "price_usd": Decimal("100"),
        "provider_price_id": None,
    },
    "team": {
        # Per-seat pricing: the payment provider multiplies this by seat count.
        # The credit grant is per seat; a shared pool is an org-layer concern.
        "monthly_credit_limit": Decimal("2000"),
        "max_output_tokens_per_request": 16384,
        "requests_per_minute": 200,
        "max_credits_per_request": Decimal("100"),
        "max_credits_per_window": Decimal("1000"),
        "budget_window_seconds": 300,
        "max_concurrent_requests": 10,
        "monthly_image_quota": 100,
        "allowed_tier_aliases": ALL_TIERS,
        "is_default": False,
        "price_usd": Decimal("30"),
        "provider_price_id": None,
    },
}


async def seed(*, force: bool) -> None:
    settings = get_settings()
    database = Database(settings)
    try:
        async with database.session() as session:
            for alias, spec in DEFAULT_TIERS.items():
                existing = await session.scalar(select(ModelTier).where(ModelTier.alias == alias))
                if existing is None:
                    session.add(ModelTier(alias=alias, enabled=True, **spec))
                    print(f"tier  + {alias} -> {spec['upstream_model_id']}")
                elif force:
                    for field, value in spec.items():
                        setattr(existing, field, value)
                    print(f"tier  ~ {alias} updated -> {spec['upstream_model_id']}")
                else:
                    print(f"tier  = {alias} exists (use --force to overwrite)")

            for name, spec in DEFAULT_PLANS.items():
                existing = await session.scalar(select(Plan).where(Plan.name == name))
                if existing is None:
                    session.add(Plan(name=name, **spec))
                    print(f"plan  + {name} (limit {spec['monthly_credit_limit']})")
                elif force:
                    for field, value in spec.items():
                        setattr(existing, field, value)
                    print(f"plan  ~ {name} updated")
                else:
                    print(f"plan  = {name} exists (use --force to overwrite)")

            await session.commit()
    finally:
        await database.aclose()
    print("done")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="overwrite existing rows")
    args = parser.parse_args()
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
