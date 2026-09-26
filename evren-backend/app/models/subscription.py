from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, str_enum
from app.models.enums import SubscriptionStatus


class Subscription(Base, IdMixin, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_user_status", "user_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SubscriptionStatus] = mapped_column(str_enum(SubscriptionStatus))
