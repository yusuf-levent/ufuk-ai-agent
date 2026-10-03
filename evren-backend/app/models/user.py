from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TimestampMixin, str_enum
from app.models.enums import UserRole


class User(Base, IdMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # Nullable: federated (Google / Apple) accounts are passwordless.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    display_name: Mapped[str | None] = mapped_column(String(100))
    # ---- Federated identity (Google / Apple sign-in) ----
    # Which provider owns this identity ("google" | "apple") and the
    # provider-scoped subject (the `sub` claim). Both stay NULL for
    # email/password accounts. The pair is unique so a provider identity can
    # never be claimed twice.
    auth_provider: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    provider_subject: Mapped[str | None] = mapped_column(String(255), nullable=True, default=None)
    role: Mapped[UserRole] = mapped_column(
        str_enum(UserRole), default=UserRole.USER, server_default="user"
    )
    email_verified: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("true"))
    # ---- Account-sharing deterrent (contractual + soft detection) ----
    # When the terms were accepted and which revision. Nullable so accounts
    # created before the clause existed stay grandfathered in — locking out
    # paying users retroactively would be both unfair and legally shaky.
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    terms_version: Mapped[str | None] = mapped_column(String(20), nullable=True, default=None)
    # Soft abuse flag: set when usage patterns look like a shared account
    # (many parallel sessions / bursts). Never auto-bans — a human reviews.
    security_flagged: Mapped[bool] = mapped_column(default=False, server_default=text("false"))
    security_flag_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, default=None
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True, default=None
    )
    # Provider-agnostic customer id (Stripe `cus_...`, Dodo `cus_...`, Paddle
    # `ctm_...`). Preferred over `stripe_customer_id`, which is kept for
    # backwards compatibility with existing rows and clients.
    provider_customer_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True, nullable=True, default=None
    )
