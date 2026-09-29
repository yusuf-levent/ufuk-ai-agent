"""Billing provider registry.

`get_provider()` resolves the active provider from `BILLING_PROVIDER`
(`stripe` | `dodo` | `dodo_live` | `paddle` | `paddle_live`). Adding a provider
means adding a module here and one line in the registry below — the billing
router never changes.
"""

from __future__ import annotations

from app.services.billing_providers.base import (
    BillingError,
    CheckoutSession,
    EventType,
    NormalizedEvent,
    PaymentProvider,
    PortalSession,
    WebhookVerificationError,
)
from app.services.billing_providers.dodo import DodoProvider
from app.services.billing_providers.paddle import PaddleProvider
from app.services.billing_providers.stripe import StripeProvider

_PROVIDERS: dict[str, PaymentProvider] = {
    "stripe": StripeProvider(),
    "dodo": DodoProvider(live_mode=False),
    "dodo_live": DodoProvider(live_mode=True),
    "paddle": PaddleProvider(live_mode=False),
    "paddle_live": PaddleProvider(live_mode=True),
}


def get_provider(name: str) -> PaymentProvider:
    """Resolve a provider by its `BILLING_PROVIDER` identifier.

    Raises `BillingError` for unknown names so a typo in `.env` fails loudly
    at the first billing call rather than silently falling back.
    """
    provider = _PROVIDERS.get(name.lower())
    if provider is None:
        supported = ", ".join(sorted(_PROVIDERS))
        raise BillingError(
            f"Unknown BILLING_PROVIDER '{name}' (supported: {supported})",
            code="unknown_provider",
        )
    return provider


__all__ = [
    "BillingError",
    "CheckoutSession",
    "EventType",
    "NormalizedEvent",
    "PaymentProvider",
    "PortalSession",
    "WebhookVerificationError",
    "get_provider",
]
