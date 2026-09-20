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

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> TierView:
        return cls(
            alias=data["alias"],
            display_name=data["display_name"],
            upstream_model_id=data["upstream_model_id"],
            upstream_provider_name=data["upstream_provider_name"],
            input_credits_per_1k_tokens=Decimal(data["input_credits_per_1k_tokens"]),
            output_credits_per_1k_tokens=Decimal(data["output_credits_per_1k_tokens"]),
            max_output_tokens=int(data["max_output_tokens"]),
            context_window=int(data["context_window"]),
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "alias": self.alias,
            "display_name": self.display_name,
            "upstream_model_id": self.upstream_model_id,
            "upstream_provider_name": self.upstream_provider_name,
            "input_credits_per_1k_tokens": str(self.input_credits_per_1k_tokens),
            "output_credits_per_1k_tokens": str(self.output_credits_per_1k_tokens),
            "max_output_tokens": str(self.max_output_tokens),
            "context_window": str(self.context_window),
        }


def tier_to_view(tier: ModelTier) -> TierView:
    return TierView(
        alias=tier.alias,
        display_name=tier.display_name,
        upstream_model_id=tier.upstream_model_id,
        upstream_provider_name=tier.upstream_provider_name,
        input_credits_per_1k_tokens=tier.input_credits_per_1k_tokens,
        output_credits_per_1k_tokens=tier.output_credits_per_1k_tokens,
        max_output_tokens=tier.max_output_tokens,
        context_window=tier.context_window,
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
