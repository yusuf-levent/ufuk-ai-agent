from __future__ import annotations

import logging
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from app.config import Settings

_REDACTED = "[REDACTED]"

_EXACT_REDACTED_KEYS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api_key",
        "apikey",
        "key",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "session",
        "password",
        "password_hash",
        "secret",
        "jwt_secret",
        "upstream_api_key",
        "credentials",
        "body",
        "request_body",
        "response_body",
        "messages",
        "prompt",
        "completion",
        "content",
        "choices",
        "delta",
        "chunk",
    }
)
_STEM_REDACTED = ("password", "secret", "api_key", "apikey", "authorization", "credential")
_MAX_DEPTH = 5


def _is_sensitive(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in _EXACT_REDACTED_KEYS or any(stem in normalized for stem in _STEM_REDACTED)


def _redact_value(value: Any, depth: int) -> Any:
    if depth >= _MAX_DEPTH:
        return _REDACTED
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _is_sensitive(str(k)) else _redact_value(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_value(v, depth + 1) for v in value]
    return value


def redact_processor(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    return {
        key: (_REDACTED if _is_sensitive(key) else _redact_value(value, 0))
        for key, value in event_dict.items()
    }


def configure_logging(settings: Settings) -> None:
    renderer: Processor
    if settings.environment == "dev":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact_processor,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=False,
    )
