"""Seed default plans and model tiers.

DEFAULT_TIERS / DEFAULT_PLANS are the source of truth for the curated model
picker, so every run reconciles the database against them:

* a missing tier/plan is inserted, an existing one is overwritten with the
  seeded values (hand edits made through the admin API are replaced — use the
  admin API for permanent customisation, not the seed);
* seed-owned tiers that DEFAULT_TIERS no longer defines are retired (disabled)
  so a replaced model cannot linger in the picker;
* plan `allowed_tier_aliases` entries that no longer resolve to a usable tier
  are dropped, so a stale alias cannot hide a live model or surface a dead one.

Upstream model ids can be overridden with env vars when the upstream changes.

`--force` is accepted for backwards compatibility and no longer changes
behaviour: reconciliation is unconditional.

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
from sqlalchemy import select, update

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
    # ------------------------------------------------------------------
    # GIRIS / ORTA katman - Cinli modeller (ucuz, vision + tool zorunlu)
    # ------------------------------------------------------------------
    "qwen3.7-flash": {
        "display_name": "Qwen 3.7 Flash",
        "upstream_model_id": os.environ.get("SEED_QWEN37_FLASH_MODEL", "qwen/qwen3.7-flash"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.039"),
        "output_credits_per_1k_tokens": Decimal("0.169"),
        # Live OpenRouter ratios (2026-10-01): qwen3.7-flash cache read is 0.2x
        # and cache WRITE is 1.27x the prompt price - charging 1.0x for writes
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
        # Same-or-cheaper only (live USD, 2026-10-01): ling-3.0-flash-vl is
        # $0.083/1M in+out vs this tier's $0.16. A pricier fallback would
        # silently inflate the bill whenever the primary errors.
        "fallback_model_ids": ["inclusionai/ling-3.0-flash-vl"],
        "routing_plugin": None,
        "price_note": "Cheapest — for short questions and quick tasks",
        "price_note_tr": "En ucuz — kısa sorular ve hızlı görevler için",
        "tooltip_title": "Qwen 3.7 Flash",
        "tooltip_body": "En ucuz seçenek. Kısa sorular ve hızlı görevler için ideal. "
        "Uzun sohbetlerde onbellek sayesinde daha da ucuzlar.",
        "tooltip_cost_level": 1,
        "tooltip_speed_level": 5,
        "tooltip_quality_level": 2,
        "tooltip_best_for": "Kısa sorular, hızlı görevler, günlük kullanım",
        "speed_hint": 5,
        "quality_hint": 2,
    },
    "deepseek-v4.1-flash": {
        "display_name": "DeepSeek V4.1 Flash",
        "upstream_model_id": os.environ.get(
            "SEED_DEEPSEEK_V41_FLASH_MODEL", "deepseek/deepseek-v4.1-flash"
        ),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.039"),
        "output_credits_per_1k_tokens": Decimal("0.65"),
        # Live OpenRouter ratios (2026-10-01): deepseek-v4.1-flash cache read is
        # 0.333x the prompt price (no write premium).
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
        "Kisa sorular ve hizli gorevler icin ideal.",
        "tooltip_cost_level": 1,
        "tooltip_speed_level": 5,
        "tooltip_quality_level": 3,
        "tooltip_best_for": "Kısa sorular, hızlı görevler, görsel analiz",
        "speed_hint": 5,
        "quality_hint": 3,
    },
    "qwen3.8-flash": {
        "display_name": "Qwen 3.8 Flash",
        "upstream_model_id": os.environ.get("SEED_QWEN38_FLASH_MODEL", "qwen/qwen3.8-flash"),
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
        "fallback_model_ids": ["qwen/qwen3.7-flash", "google/gemma-4-31b-it"],
        "routing_plugin": None,
        "price_note": "Balanced — good choice for daily use",
        "price_note_tr": "Dengeli — günlük kullanım için iyi seçim",
        "tooltip_title": "Qwen 3.8 Flash",
        "tooltip_body": "Dengeli — günlük kullanım için iyi seçim. "
        "Gorsel ve video girdi destekli. "
        "Uzun sohbetlerde onbellek sayesinde daha da ucuzlar.",
        "tooltip_cost_level": 2,
        "tooltip_speed_level": 4,
        "tooltip_quality_level": 3,
        "tooltip_best_for": "Günlük kodlama, refactor, görsel analiz",
        "speed_hint": 4,
        "quality_hint": 3,
    },
    "glm-5.3-flash": {
        "display_name": "GLM 5.3 Flash",
        "upstream_model_id": os.environ.get("SEED_GLM53_FLASH_MODEL", "z-ai/glm-5.3-flash"),
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
        "fallback_model_ids": ["qwen/qwen3.8-flash", "google/gemma-4-31b-it"],
        "routing_plugin": None,
        "price_note": "Strong — complex tasks, more expensive",
        "price_note_tr": "Güçlü — karmaşık görevler, daha pahalı",
        "tooltip_title": "GLM 5.3 Flash",
        "tooltip_body": "Güçlü — karmaşık görevler, daha pahalı. "
        "Mimari kararlar, zor hata ayiklama, kritik refactor icin.",
        "tooltip_cost_level": 3,
        "tooltip_speed_level": 2,
        "tooltip_quality_level": 4,
        "tooltip_best_for": "Mimari kararlar, zor hata ayıklama, kritik refactor",
        "speed_hint": 2,
        "quality_hint": 4,
    },
    "mimo-v2.6-pro": {
        "display_name": "MiMo v2.6 Pro",
        "upstream_model_id": os.environ.get("SEED_MIMO_V26_PRO_MODEL", "xiaomi/mimo-v2.6-pro"),
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
        "price_note": "Powerful — long reasoning and image input",
        "price_note_tr": "Güçlü, uzun akıl yürütme ve görsel girdi destekli",
        "tooltip_title": "MiMo v2.6 Pro",
        "tooltip_body": "Güçlü, uzun akıl yürütme ve görsel girdi destekli. "
        "Karma??k gorevler icin. "
        "Uzun sohbetlerde onbellek sayesinde daha da ucuzlar.",
        "tooltip_cost_level": 3,
        "tooltip_speed_level": 2,
        "tooltip_quality_level": 4,
        "tooltip_best_for": "Karmaşık görevler, uzun akıl yürütme, görsel analiz",
        "speed_hint": 2,
        "quality_hint": 4,
    },
    # ------------------------------------------------------------------
    # FRONTIER katman - GPT / Claude amiral gemileri (pahali, en iyi kalite)
    # ------------------------------------------------------------------
    "gpt-6-sol": {
        "display_name": "GPT-6 Sol",
        "upstream_model_id": os.environ.get("SEED_GPT6_SOL_MODEL", "openai/gpt-6-sol"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("2.6"),
        "output_credits_per_1k_tokens": Decimal("13.0"),
        # Live OpenRouter ratios (2026-10-01): gpt-6-sol cache read 0.1x,
        # cache write 1.25x the prompt price.
        "cache_read_multiplier": Decimal("0.1"),
        "cache_write_multiplier": Decimal("1.25"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 32768,
        "context_window": 1050000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        "fallback_model_ids": ["anthropic/claude-sonnet-5.5"],
        "routing_plugin": None,
        "price_note": "Frontier — OpenAI flagship, most capable",
        "price_note_tr": "Frontier — OpenAI amiral gemisi, en yetenekli",
        "tooltip_title": "GPT-6 Sol",
        "tooltip_body": "Frontier — OpenAI amiral gemisi. "
        "En zor gorevler, mimari kararlar ve kritik kodlama icin. "
        "Cok pahalidir - gunluk isler icin onerilmez.",
        "tooltip_cost_level": 5,
        "tooltip_speed_level": 2,
        "tooltip_quality_level": 5,
        "tooltip_best_for": "En zor görevler, mimari kararlar, kritik kodlama",
        "speed_hint": 2,
        "quality_hint": 5,
    },
    "claude-sonnet-5.5": {
        "display_name": "Claude Sonnet 5.5",
        "upstream_model_id": os.environ.get(
            "SEED_CLAUDE_SONNET55_MODEL", "anthropic/claude-sonnet-5.5"
        ),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("2.6"),
        "output_credits_per_1k_tokens": Decimal("13.0"),
        "cache_read_multiplier": Decimal("0.1"),
        "cache_write_multiplier": Decimal("1.25"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 32768,
        "context_window": 1000000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        "fallback_model_ids": ["openai/gpt-6-sol"],
        "routing_plugin": None,
        "price_note": "Frontier — Anthropic flagship, excellent coder",
        "price_note_tr": "Frontier — Anthropic amiral gemisi, müthişem kodcu",
        "tooltip_title": "Claude Sonnet 5.5",
        "tooltip_body": "Frontier — Anthropic amiral gemisi. "
        "Kodlama ve uzun muhendislik gorevlerinde ustun. "
        "Cok pahalidir - gunluk isler icin onerilmez.",
        "tooltip_cost_level": 5,
        "tooltip_speed_level": 2,
        "tooltip_quality_level": 5,
        "tooltip_best_for": "Kodlama, uzun mühendislik görevleri, refactor",
        "speed_hint": 2,
        "quality_hint": 5,
    },
    "claude-opus-5.5": {
        "display_name": "Claude Opus 5.5",
        "upstream_model_id": os.environ.get(
            "SEED_CLAUDE_OPUS55_MODEL", "anthropic/claude-opus-5.5"
        ),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("5.2"),
        "output_credits_per_1k_tokens": Decimal("26.0"),
        "cache_read_multiplier": Decimal("0.05"),
        "cache_write_multiplier": Decimal("1.25"),
        "reasoning_multiplier": Decimal("1.0"),
        "max_output_tokens": 32768,
        "context_window": 1000000,
        "input_modalities": ["text", "image"],
        "output_modalities": ["text"],
        "supports_tools": True,
        "pricing_unit": "token",
        "is_internal": False,
        "fallback_model_ids": ["anthropic/claude-sonnet-5.5", "openai/gpt-6-sol"],
        "routing_plugin": None,
        "price_note": "Frontier ultra — strongest reasoning, very expensive",
        "price_note_tr": "Frontier ultra — en güçlü akıl yürütme, çok pahalı",
        "tooltip_title": "Claude Opus 5.5",
        "tooltip_body": "Frontier ultra — en güçlü akıl yürütme. "
        "Sadece en zor gorevler icin. "
        "Cok pahalidir - bir sohbet birkac dakikada bitebilir.",
        "tooltip_cost_level": 5,
        "tooltip_speed_level": 1,
        "tooltip_quality_level": 5,
        "tooltip_best_for": "En zor analiz, araştırma, kritik kararlar",
        "speed_hint": 1,
        "quality_hint": 5,
    },
    # ------------------------------------------------------------------
    # ROUTER - kullanici model secmez, ucuz adaylardan secer
    # ------------------------------------------------------------------
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
        # The router may only pick from this cheap, vision+tool capable set -
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
        "Hangi modeli kullanacagina kendin karar vermek istemiyorsan bunu sec.",
        "tooltip_cost_level": 2,
        "tooltip_speed_level": 4,
        "tooltip_quality_level": 4,
        "tooltip_best_for": "Her şey — otomatik model seçimi",
        "speed_hint": 4,
        "quality_hint": 4,
    },
}

ALL_TIERS = [
    "qwen3.7-flash",
    "deepseek-v4.1-flash",
    "qwen3.8-flash",
    "glm-5.3-flash",
    "mimo-v2.6-pro",
    "gpt-6-sol",
    "claude-sonnet-5.5",
    "claude-opus-5.5",
    "auto",
]

# Aliases this script has seeded in the past but DEFAULT_TIERS no longer
# defines. The picker is served straight from `model_tiers`, and nothing else
# ever removes a row, so a replaced tier would stay visible forever unless the
# seed retires it. Only these seed-owned aliases are ever retired — a tier an
# operator added by hand or through the admin API is left untouched.
LEGACY_TIER_ALIASES = ("fast", "balanced", "strong")


def retired_tier_aliases(existing_aliases: set[str]) -> list[str]:
    """Seed-managed aliases that DEFAULT_TIERS no longer defines.

    These must be disabled on every seed run: leaving them enabled keeps a
    model in the picker that the product no longer ships.
    """
    return sorted((existing_aliases & set(LEGACY_TIER_ALIASES)) - set(DEFAULT_TIERS))


def prune_plan_aliases(aliases: list[str], live_aliases: set[str]) -> list[str]:
    """Drop plan allow-list entries that no longer resolve to a usable tier.

    A plan still pointing at a retired alias surfaces a dead entry in the
    picker (or hides a live one behind a stale allow-list).
    """
    return [alias for alias in aliases if alias in live_aliases]

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
        # Light-tier models only (cost level 1). Mid/high tiers stay paid.
        "allowed_tier_aliases": ["qwen3.7-flash", "deepseek-v4.1-flash"],
        "is_default": True,
        "price_usd": Decimal("0"),
        "provider_price_id": None,
    },
    "plus": {
        "monthly_credit_limit": Decimal("2500"),
        "max_output_tokens_per_request": 32768,
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
        "max_output_tokens_per_request": 32768,
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
        "max_output_tokens_per_request": 32768,
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
                else:
                    for field, value in spec.items():
                        setattr(existing, field, value)
                    print(f"tier  ~ {alias} synced -> {spec['upstream_model_id']}")

            # Retire seed-owned tiers that DEFAULT_TIERS no longer defines. The
            # picker is served straight from `model_tiers`, so a replaced tier
            # would otherwise stay visible forever. Hand-added tiers are left
            # alone — only LEGACY_TIER_ALIASES are ever retired here.
            existing_aliases = set(
                (await session.execute(select(ModelTier.alias))).scalars().all()
            )
            for alias in retired_tier_aliases(existing_aliases):
                await session.execute(
                    update(ModelTier).where(ModelTier.alias == alias).values(enabled=False)
                )
                print(f"tier  - {alias} retired (disabled)")

            live_aliases = set(DEFAULT_TIERS)
            for name, spec in DEFAULT_PLANS.items():
                existing = await session.scalar(select(Plan).where(Plan.name == name))
                if existing is None:
                    session.add(Plan(name=name, **spec))
                    print(f"plan  + {name} (limit {spec['monthly_credit_limit']})")
                    continue
                for field, value in spec.items():
                    setattr(existing, field, value)
                print(f"plan  ~ {name} synced")
                # Drop allow-list entries that no longer resolve to a usable
                # tier: a stale alias hides a live model or surfaces a dead one.
                pruned = prune_plan_aliases(list(existing.allowed_tier_aliases), live_aliases)
                if pruned != list(existing.allowed_tier_aliases):
                    existing.allowed_tier_aliases = pruned
                    print(f"plan  ~ {name} aliases pruned -> {pruned}")

            await session.commit()
    finally:
        await database.aclose()
    print("done")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="deprecated: reconciliation is unconditional, the flag is kept for compatibility",
    )
    args = parser.parse_args()
    asyncio.run(seed(force=args.force))


if __name__ == "__main__":
    main()
