from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin


class CostDailyRollup(Base, IdMixin):
    """Daily user x tier x model cost aggregate.

    Raw ``usage_events`` rows grow forever and answering "what did this user /
    model cost us last month" would scan thousands of rows. This rollup makes
    that a single indexed query — the basis for margin dashboards and for
    spotting a model whose real USD cost drifted away from its credit rate.

    Rows are upserted as requests settle; ``user_id`` becomes NULL when the
    account is deleted (same anonymisation rule as ``usage_events``).
    """

    __tablename__ = "cost_daily_rollup"
    __table_args__ = (
        UniqueConstraint(
            "day", "user_id", "tier_alias", "selected_model_id", name="uq_cost_rollup_key"
        ),
    )

    day: Mapped[date] = mapped_column(Date, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    tier_alias: Mapped[str] = mapped_column(String(50))
    selected_model_id: Mapped[str | None] = mapped_column(String(200), nullable=True)

    requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cached_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    credits_charged: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), default=Decimal("0"), server_default="0"
    )
    upstream_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 6), default=Decimal("0"), server_default="0"
    )