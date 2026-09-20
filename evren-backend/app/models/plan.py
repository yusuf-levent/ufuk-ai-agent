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
    allowed_tier_aliases: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    is_default: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
