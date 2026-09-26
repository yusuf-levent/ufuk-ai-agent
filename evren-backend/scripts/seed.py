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

DEFAULT_TIERS = {
    "fast": {
        "display_name": "Fast",
        "upstream_model_id": os.environ.get("SEED_FAST_MODEL", "deepseek-v4-flash"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("0.5"),
        "output_credits_per_1k_tokens": Decimal("1.0"),
        "max_output_tokens": 8192,
        "context_window": 128000,
    },
    "balanced": {
        "display_name": "Balanced",
        "upstream_model_id": os.environ.get("SEED_BALANCED_MODEL", "gemma-4-31b"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("1.5"),
        "output_credits_per_1k_tokens": Decimal("3.0"),
        "max_output_tokens": 8192,
        "context_window": 128000,
    },
    "strong": {
        "display_name": "Strong",
        "upstream_model_id": os.environ.get("SEED_STRONG_MODEL", "glm-5.3"),
        "upstream_provider_name": PROVIDER,
        "input_credits_per_1k_tokens": Decimal("4.0"),
        "output_credits_per_1k_tokens": Decimal("8.0"),
        "max_output_tokens": 16384,
        "context_window": 200000,
    },
}

ALL_TIERS = ["fast", "balanced", "strong"]

DEFAULT_PLANS = {
    "free": {
        "monthly_credit_limit": Decimal("100"),
        "max_output_tokens_per_request": 8192,
        "requests_per_minute": 10,
        "allowed_tier_aliases": ["fast"],
        "is_default": True,
    },
    "pro": {
        "monthly_credit_limit": Decimal("5000"),
        "max_output_tokens_per_request": 16384,
        "requests_per_minute": 60,
        "allowed_tier_aliases": ALL_TIERS,
        "is_default": False,
    },
    "team": {
        "monthly_credit_limit": Decimal("50000"),
        "max_output_tokens_per_request": 16384,
        "requests_per_minute": 200,
        "allowed_tier_aliases": ALL_TIERS,
        "is_default": False,
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
