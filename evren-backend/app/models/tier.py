from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


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
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    context_window: Mapped[int] = mapped_column(Integer)
    # Human-readable price/performance note shown next to the model in the
    # picker (e.g. "Ucuz ve hızlı"). Manually curated via seed/admin — never
    # derived automatically from upstream pricing.
    price_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    price_note_tr: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Simple 1-5 ordering hints for picker labels (higher = faster/better).
    speed_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
