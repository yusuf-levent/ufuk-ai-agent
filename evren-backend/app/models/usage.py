from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, str_enum, utcnow
from app.models.enums import UsageStatus


class UsageEvent(Base, IdMixin):
    __tablename__ = "usage_events"

    request_id: Mapped[uuid.UUID] = mapped_column(unique=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    tier_alias: Mapped[str] = mapped_column(String(50))
    upstream_model_id: Mapped[str] = mapped_column(String(200))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    credits_charged: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    estimated: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    status: Mapped[UsageStatus] = mapped_column(str_enum(UsageStatus))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # ---- Cost accounting (internal only — never exposed to clients) ----
    # Real USD the upstream charged for this request (OpenRouter `usage.cost`).
    # The foundation of margin tracking: "this user cost us $2.30 and paid $10".
    upstream_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, default=None
    )
    # Prompt-cache buckets, used to measure how much the cache discount saves.
    cached_prompt_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    cache_write_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    # Reasoning (chain-of-thought) tokens — billed at the output rate but worth
    # tracking separately so "why did 5 lines of answer cost 40 credits" is
    # answerable.
    reasoning_tokens: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0")
    )
    # Which concrete upstream model actually served the request. Matters for
    # `auto` tiers and hidden sub-agent tiers where the alias hides the model.
    selected_model_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, default=None
    )
    # Chain tracking: a sub-agent call points at the user-visible request that
    # spawned it, so the full cost of one user message can be summed.
    parent_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, default=None, index=True
    )
    # Conversation key used for upstream sticky routing / cache-hit analysis.
    session_id: Mapped[str | None] = mapped_column(
        String(256), nullable=True, default=None
    )
    # Why the model stopped: stop | length | tool_calls | content_filter | ...
    finish_reason: Mapped[str | None] = mapped_column(
        String(32), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
