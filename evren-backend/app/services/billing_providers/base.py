"""Provider-agnostic billing interfaces.

The gateway's billing router talks to this abstraction only. Concrete
providers (Stripe, Dodo Payments, Paddle) translate their own API shapes and
webhook payloads into the normalized forms below, so switching providers is a
`.env` change (`BILLING_PROVIDER`) and never a code change.

Nothing here knows about plans, credits, or subscriptions — the router maps a
`NormalizedEvent` onto `assign_plan()` itself.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass, field
from typing import Any


class BillingError(Exception):
    """Provider call failed (bad request, network error, upstream 4xx/5xx)."""

    def __init__(self, message: str, *, code: str = "billing_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class WebhookVerificationError(Exception):
    """Webhook signature missing or invalid — reject with 400/401."""


class EventType(enum.StrEnum):
    """Provider-independent billing lifecycle events."""

    SUBSCRIPTION_STARTED = "subscription.started"
    SUBSCRIPTION_RENEWED = "subscription.renewed"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"


@dataclass(frozen=True, slots=True)
class NormalizedEvent:
    """A provider webhook event reduced to what the gateway cares about.

    `provider_price_id` is matched against `plans.provider_price_id` (falling
    back to the legacy `plans.stripe_price_id`) and `customer_email` against
    `users.email`. Either may be `None` when the provider payload does not
    carry it — the router then ignores the event.
    """

    type: EventType
    provider_event_id: str | None = None
    provider_event_type: str = ""
    provider_price_id: str | None = None
    provider_customer_id: str | None = None
    customer_email: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    """Result of creating a hosted checkout session."""

    url: str
    provider_session_id: str | None = None


@dataclass(frozen=True, slots=True)
class PortalSession:
    """Result of creating a customer self-service (billing portal) session."""

    url: str


class PaymentProvider(abc.ABC):
    """One billing backend (Stripe, Dodo Payments, Paddle, ...).

    Implementations must be stateless: configuration arrives per call so the
    router can honour per-request settings overrides in tests.
    """

    #: Stable identifier used in `BILLING_PROVIDER` and in logs.
    name: str = "abstract"

    @abc.abstractmethod
    def is_configured(self, api_key: str | None) -> bool:
        """Whether checkout/portal calls can be made with these credentials."""

    @abc.abstractmethod
    async def create_checkout(
        self,
        *,
        api_key: str,
        provider_price_id: str,
        user_id: str,
        user_email: str,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        """Create a hosted subscription checkout and return its URL."""

    @abc.abstractmethod
    async def create_portal(
        self,
        *,
        api_key: str,
        provider_customer_id: str,
        return_url: str,
    ) -> PortalSession:
        """Create a customer billing-portal session and return its URL."""

    @abc.abstractmethod
    async def find_customer_id(self, *, api_key: str, email: str) -> str | None:
        """Look up an existing provider customer by email, if any."""

    @abc.abstractmethod
    async def create_customer(self, *, api_key: str, email: str, user_id: str) -> str:
        """Create a provider customer for this account and return its id."""

    @abc.abstractmethod
    def verify_webhook(self, *, payload: bytes, headers: Any, secret: str) -> None:
        """Raise `WebhookVerificationError` unless the signature is valid.

        `headers` is a case-insensitive mapping (Starlette `Headers`).
        """

    @abc.abstractmethod
    def parse_event(self, payload: bytes) -> NormalizedEvent | None:
        """Translate a verified webhook payload into a `NormalizedEvent`.

        Return `None` for event types the gateway does not act on.
        """
