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
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    context_window: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
