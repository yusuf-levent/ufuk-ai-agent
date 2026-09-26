from __future__ import annotations

from typing import Protocol

import structlog

logger = structlog.get_logger(__name__)


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender:
    """Dev-only sender: writes the message to structured logs."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("email_sent", to=to, subject=subject, email_body=body)
