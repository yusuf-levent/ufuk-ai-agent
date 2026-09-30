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
