from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, utcnow, str_enum
from app.models.enums import ImageQuality


class GeneratedImage(Base, IdMixin):
    """A generated image stored on our backend.

    Binary data lives on disk/object storage; this row tracks metadata for
    quota enforcement, cost attribution, and the user's gallery. The user never
    sees the upstream model id — it stays internal like hidden sub-agent tiers.
    """

    __tablename__ = "generated_images"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # The upstream model that actually generated this (internal only).
    upstream_model_id: Mapped[str] = mapped_column(String(200))
    # Prompt sent to the image model (stored for regeneration/history; NOT
    # shared with other users).
    prompt: Mapped[str] = mapped_column(String(2000))
    quality: Mapped[ImageQuality] = mapped_column(str_enum(ImageQuality))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(10), default="png")
    # Where the binary lives (relative path under the images root).
    storage_path: Mapped[str] = mapped_column(String(500))
    # Credits charged for this image (quality multiplier applied).
    credits_charged: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    # Real USD cost from OpenRouter (for margin tracking).
    upstream_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, default=None
    )
    # Generation time in milliseconds.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )