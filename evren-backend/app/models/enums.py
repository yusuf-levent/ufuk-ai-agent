from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class EmailTokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class UsageStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PricingUnit(StrEnum):
    """What one billable unit of a tier costs.

    TOKEN  — per-token billing (chat models; our credit formula applies).
    IMAGE  — per generated image (image-generation models; needs its own
             counter because `kredi = token x oran` cannot express it).
    REQUEST — per upstream request (rare; flat fee per call).
    """

    TOKEN = "token"
    IMAGE = "image"
    REQUEST = "request"


class ImageQuality(StrEnum):
    """Resolution tier for generated images. Maps to OpenRouter's `variant`
    pricing (1K / 2K / 4K) and drives the credit multiplier."""

    STANDARD = "standard"  # 1K  (~1024px)  — 1 credit
    HIGH = "high"          # 2K  (~2048px)  — 2 credits
    ULTRA = "ultra"        # 4K  (~4096px)  — 4 credits
