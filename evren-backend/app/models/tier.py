from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ARRAY, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, str_enum
from app.models.enums import PricingUnit


class ModelTier(Base, IdMixin, TimestampMixin):
    __tablename__ = "model_tiers"

    alias: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    upstream_model_id: Mapped[str] = mapped_column(String(200))
    upstream_provider_name: Mapped[str] = mapped_column(String(100))
    input_credits_per_1k_tokens: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    output_credits_per_1k_tokens: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    # Prompt-cache pricing multipliers applied to the input rate. Providers
    # discount cached reads (DeepSeek/Alibaba/Anthropic 0.1x, Google/Moonshot
    # 0.25x, Groq 0.5x) and some charge a premium for cache writes (Anthropic/
    # Alibaba 1.25x). Defaults keep the historical behaviour: no discount and
    # no write premium.
    cache_read_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("1.0"), server_default=text("1.0")
    )
    cache_write_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("1.0"), server_default=text("1.0")
    )
    # Premium applied to reasoning (chain-of-thought) tokens ONLY. Providers
    # already count reasoning inside `completion_tokens`, so this is a relative
    # weight on that subset — NOT an extra charge on top of the output rate.
    # 1.0 (default) = reasoning billed exactly like visible output (no double
    # billing); 1.5 = reasoning costs 50% more than visible output.
    reasoning_multiplier: Mapped[Decimal] = mapped_column(
        Numeric(6, 4), default=Decimal("1.0"), server_default=text("1.0")
    )
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    context_window: Mapped[int] = mapped_column(Integer)
    # ---- Capability metadata (picker filtering + billing unit) ----
    # What the model can OUTPUT (e.g. ["text"] or ["text","image"]). Distinct
    # from input_modalities: a vision model READS images but does not generate
    # them. Used to route image-generation requests and to keep text-only tiers
    # out of image flows.
    output_modalities: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), default=lambda: ["text"], server_default=text("'{text}'")
    )
    # Whether the upstream model honours tool calling. Our user-facing picker
    # requires it (agent workflows depend on tools); image-generation models
    # mostly lack it and must stay behind the server-side tool facade.
    supports_tools: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # Billing unit: token (chat), image (generation), request (flat). Only
    # TOKEN tiers use the credit-per-1k formula; the others need their own
    # counters so we never mis-bill a generated image as tokens.
    pricing_unit: Mapped[PricingUnit] = mapped_column(
        str_enum(PricingUnit), default=PricingUnit.TOKEN, server_default="token"
    )
    # Ceiling on generated images per request (IMAGE tiers only). NULL = no
    # per-request cap beyond the plan's image quota.
    max_images_per_request: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    # Internal tiers are invisible and UNUSABLE from the public gateway: they
    # serve hidden sub-agent / server-side work only. A user request naming an
    # internal tier is rejected outright — otherwise a user could pick the
    # hidden (often pricier) model and bypass the curated picker.
    is_internal: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    # Ordered upstream model ids tried when the primary fails (rate limit,
    # outage, refusal). Sent as an OpenRouter `models` array. Entries must be
    # same-or-cheaper than the primary — a fallback that costs more would let a
    # transient error silently inflate the user's bill.
    fallback_model_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(200)), default=list, server_default=text("'{}'")
    )
    # Optional OpenRouter router plugin ("auto-router" | "pareto-router"). The
    # gateway pins `allowed_models` to this tier's own chain and `costTier` to
    # "low", so the router can never pick an off-list or expensive model.
    routing_plugin: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default=None
    )
    # Tooltip metadata for the model picker (ℹ️ hover card). Curated manually
    # via seed/admin — never derived from upstream pricing.
    tooltip_title: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    tooltip_body: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    tooltip_cost_level: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    tooltip_speed_level: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    tooltip_quality_level: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    tooltip_best_for: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    # Human-readable price/performance note shown next to the model in the
    # picker (e.g. "Ucuz ve hızlı"). Manually curated via seed/admin — never
    # derived automatically from upstream pricing.
    price_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    price_note_tr: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Simple 1-5 ordering hints for picker labels (higher = faster/better).
    speed_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
