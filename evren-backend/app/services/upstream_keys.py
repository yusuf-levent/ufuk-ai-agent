from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Protocol


class UpstreamKeyProvider(Protocol):
    """Hook for creating per-user upstream API keys with spend limits.

    Intentionally not implemented yet. When a real provider supports
    per-key spend limits, implement this protocol and wire it in
    create_app; the gateway will then be able to attach per-user keys
    to upstream calls instead of the shared account key.
    """

    async def create_key(self, *, user_id: uuid.UUID, spend_limit: Decimal | None) -> str:
        """Returns the raw upstream API key for this user."""
        ...

    async def revoke_key(self, *, key_id: str) -> None: ...


class DisabledUpstreamKeyProvider:
    """Default implementation: per-user keys are not available."""

    async def create_key(self, *, user_id: uuid.UUID, spend_limit: Decimal | None) -> str:
        raise NotImplementedError("per-user upstream keys are not configured")

    async def revoke_key(self, *, key_id: str) -> None:
        raise NotImplementedError("per-user upstream keys are not configured")
