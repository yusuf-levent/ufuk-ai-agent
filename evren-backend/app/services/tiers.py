from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select

from app.db import Database
from app.models import ModelTier

TIER_CACHE_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class TierView:
    alias: str
    display_name: str
    upstream_model_id: str
    upstream_provider_name: str
    input_credits_per_1k_tokens: Decimal
    output_credits_per_1k_tokens: Decimal
    max_output_tokens: int
    context_window: int
    # Prompt-cache pricing multipliers applied to the input rate (1.0 = no
    # discount/premium). Optional with a neutral default so older callers and
    # stale cache entries keep working unchanged.
    cache_read_multiplier: Decimal = Decimal("1.0")
    cache_write_multiplier: Decimal = Decimal("1.0")
    # Relative weight on the reasoning subset of completion tokens (1.0 =
    # reasoning billed like visible output, no double billing).
    reasoning_multiplier: Decimal = Decimal("1.0")
    # Capability metadata (defaults keep older callers working).
    output_modalities: tuple[str, ...] = ("text",)
    supports_tools: bool = True
    pricing_unit: str = "token"
    max_images_per_request: int | None = None
    is_internal: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> TierView:
        return cls(
            alias=data["alias"],
            display_name=data["display_name"],
            upstream_model_id=data["upstream_model_id"],
            upstream_provider_name=data["upstream_provider_name"],
            input_credits_per_1k_tokens=Decimal(data["input_credits_per_1k_tokens"]),
            output_credits_per_1k_tokens=Decimal(data["output_credits_per_1k_tokens"]),
            # Older cache entries predate the cache multipliers; fall back to
            # neutral values so a stale Redis key never breaks billing.
            cache_read_multiplier=Decimal(data.get("cache_read_multiplier", "1.0")),
            cache_write_multiplier=Decimal(data.get("cache_write_multiplier", "1.0")),
            reasoning_multiplier=Decimal(data.get("reasoning_multiplier", "1.0")),
            max_output_tokens=int(data["max_output_tokens"]),
            context_window=int(data["context_window"]),
            output_modalities=tuple(
                json.loads(data["output_modalities"])
                if "output_modalities" in data
                else ("text",)
            ),
            supports_tools=data.get("supports_tools", "true") == "true",
            pricing_unit=data.get("pricing_unit", "token"),
            max_images_per_request=(
                int(data["max_images_per_request"])
                if data.get("max_images_per_request")
                else None
            ),
            is_internal=data.get("is_internal", "false") == "true",
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "alias": self.alias,
            "display_name": self.display_name,
            "upstream_model_id": self.upstream_model_id,
            "upstream_provider_name": self.upstream_provider_name,
            "input_credits_per_1k_tokens": str(self.input_credits_per_1k_tokens),
            "output_credits_per_1k_tokens": str(self.output_credits_per_1k_tokens),
            "cache_read_multiplier": str(self.cache_read_multiplier),
            "cache_write_multiplier": str(self.cache_write_multiplier),
            "reasoning_multiplier": str(self.reasoning_multiplier),
            "max_output_tokens": str(self.max_output_tokens),
            "context_window": str(self.context_window),
            "output_modalities": json.dumps(list(self.output_modalities)),
            "supports_tools": "true" if self.supports_tools else "false",
            "pricing_unit": self.pricing_unit,
            "max_images_per_request": (
                str(self.max_images_per_request)
                if self.max_images_per_request is not None
                else ""
            ),
            "is_internal": "true" if self.is_internal else "false",
        }


def tier_to_view(tier: ModelTier) -> TierView:
    return TierView(
        alias=tier.alias,
        display_name=tier.display_name,
        upstream_model_id=tier.upstream_model_id,
        upstream_provider_name=tier.upstream_provider_name,
        input_credits_per_1k_tokens=tier.input_credits_per_1k_tokens,
        output_credits_per_1k_tokens=tier.output_credits_per_1k_tokens,
        cache_read_multiplier=tier.cache_read_multiplier,
        cache_write_multiplier=tier.cache_write_multiplier,
        reasoning_multiplier=tier.reasoning_multiplier,
        max_output_tokens=tier.max_output_tokens,
        context_window=tier.context_window,
        output_modalities=tuple(tier.output_modalities or ("text",)),
        supports_tools=bool(tier.supports_tools),
        pricing_unit=str(tier.pricing_unit),
        max_images_per_request=tier.max_images_per_request,
        is_internal=bool(tier.is_internal),
    )


def _cache_key(alias: str) -> str:
    return f"tier:{alias}"


async def get_tier(db: Database, redis: Redis, alias: str) -> TierView | None:
    cached = await redis.get(_cache_key(alias))
    if cached is not None:
        return TierView.from_dict(json.loads(cached))
    async with db.session() as session:
        row = await session.scalar(
            select(ModelTier).where(ModelTier.alias == alias, ModelTier.enabled.is_(True))
        )
    if row is None:
        return None
    view = tier_to_view(row)
    await redis.set(_cache_key(alias), json.dumps(view.as_dict()), ex=TIER_CACHE_TTL_SECONDS)
    return view


async def invalidate_tier(redis: Redis, *aliases: str) -> None:
    if aliases:
        await redis.delete(*(_cache_key(alias) for alias in aliases))
