from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ARRAY, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin


class Plan(Base, IdMixin, TimestampMixin):
    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(50), unique=True)
    monthly_credit_limit: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    max_output_tokens_per_request: Mapped[int] = mapped_column(Integer)
    requests_per_minute: Mapped[int] = mapped_column(Integer)
    # Per-request credit ceiling: a single LLM call may never reserve more than
    # this. Guards against one runaway prompt (huge context + huge max_tokens)
    # draining the whole period in one shot. NULL = unlimited.
    max_credits_per_request: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, default=None
    )
    # Rolling-window credit ceiling: total credits burned inside
    # `budget_window_seconds` may never exceed this. This is the sub-agent
    # kill-switch — a nested sub-agent chain fires many LLM calls in a short
    # burst, and each call alone is under `max_credits_per_request`, so only a
    # window budget stops the exponential blow-up. NULL = unlimited.
    max_credits_per_window: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, default=None
    )
    budget_window_seconds: Mapped[int] = mapped_column(
        Integer, default=300, server_default=text("300")
    )
    allowed_tier_aliases: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    is_default: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    stripe_price_id: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    # Provider-agnostic price/product identifier (Stripe `price_...`, Dodo
    # `pdt_...`, Paddle `pri_...`). Preferred over `stripe_price_id`, which is
    # kept for backwards compatibility with existing rows and clients.
    provider_price_id: Mapped[str | None] = mapped_column(String(100), nullable=True, default=None)
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True, default=None)
