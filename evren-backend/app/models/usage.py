from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, text
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
