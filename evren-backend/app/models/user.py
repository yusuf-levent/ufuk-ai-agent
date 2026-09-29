from __future__ import annotations

from sqlalchemy import String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, str_enum
from app.models.enums import UserRole


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole), default=UserRole.USER, server_default="user"
    )
    email_verified: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True, default=None
    )
    # Provider-agnostic customer id (Stripe `cus_...`, Dodo `cus_...`, Paddle
    # `ctm_...`). Preferred over `stripe_customer_id`, which is kept for
    # backwards compatibility with existing rows and clients.
    provider_customer_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True, default=None
    )
