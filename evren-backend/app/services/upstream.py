from __future__ import annotations

import json
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import ceil
from typing import Any

import httpx
import structlog

from app.config import Settings
from app.errors import ApiError
from app.services.tiers import TierView

logger = structlog.get_logger(__name__)

ALLOWED_REQUEST_FIELDS = frozenset(
    {
        "messages",
        "temperature",
        "top_p",
        "stop",
        "max_tokens",
        "tools",
        "tool_choice",
        "response_format",
        "n",
        "presence_penalty",
        "frequency_penalty",
        "seed",
        "logit_bias",
        "parallel_tool_calls",
        "logprobs",
        "top_logprobs",
        # Sticky-routing key: keeps a conversation pinned to one upstream
        # provider so prompt-cache hits stay warm (big cost saver for agents).
        "session_id",
    }
)

# Fields the gateway constructs SERVER-SIDE and never forwards verbatim from a
# client. `models` (fallback chain) and `plugins` (router config) name upstream
# models directly — forwarding a client-supplied value would let a user reach
# any OpenRouter model (including expensive frontier ones) and bypass the
# curated tier picker. They are rebuilt from the tier's own config instead.
SERVER_ONLY_FIELDS = frozenset({"models", "plugins"})

CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)


class UpstreamClient:
    """Thin httpx wrapper around the configured upstream provider.

    Clients can never choose the upstream URL or supply credentials;
    everything here comes from server-side settings only.
    """

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,
                read=settings.upstream_timeout_seconds,
                write=30.0,
                pool=10.0,
            ),
            transport=transport,
        )

    def _apply_routing(self, payload: dict[str, Any], tier: TierView) -> None:
        """Set `model`/`models` and `plugins` from the tier's server-side config.

        Two features are built here, both driven entirely by tier config:

        * **Fallback chain** — when the tier lists fallback model ids, the
          request goes out as an OpenRouter `models` array (priority order) so
          a rate-limited/down/refusing primary transparently fails over. The
          response reports which model actually served, which the gateway
          records as ``selected_model_id`` for cost attribution.
        * **Router plugin** — ``routing_plugin`` (e.g. ``auto-router``) attaches
          an OpenRouter router plugin. ``allowed_models`` is pinned to the
          tier's own model + fallbacks so the router can never wander off to an
          expensive model, and ``costTier`` is pinned to ``low`` to honour the
          "cheap" product promise.
        """
        chain = [tier.upstream_model_id, *tier.fallback_model_ids]
        if tier.fallback_model_ids:
            payload["models"] = chain
        else:
            payload["model"] = tier.upstream_model_id

        if tier.routing_plugin:
            plugin: dict[str, Any] = {"id": tier.routing_plugin}
            if tier.routing_plugin == "auto-router":
                plugin["costTier"] = "low"
                plugin["allowed_models"] = chain
            elif tier.routing_plugin == "pareto-router":
                # Cheap-but-capable coders: medium band, cheapest pick inside it.
                plugin["minCodingScore"] = 0.33
                plugin["allowed_models"] = chain
            payload["plugins"] = [plugin]

    def _auth_headers(self) -> dict[str, str]:
        key = self._settings.upstream_api_key.get_secret_value()
        if self._settings.upstream_auth_header == "X-API-Key":
            return {"X-API-Key": key}
        return {"Authorization": f"Bearer {key}"}

    def sanitize_request(
        self, body: dict[str, Any], *, tier: TierView, max_output_tokens: int
    ) -> dict[str, Any]:
        payload = {
            field: value
            for field, value in body.items()
            if field in ALLOWED_REQUEST_FIELDS and field != "max_tokens"
        }
        dropped = sorted(
            set(body) - ALLOWED_REQUEST_FIELDS - {"model", "stream"} - SERVER_ONLY_FIELDS
        )
        if dropped:
            logger.info("dropped_request_fields", fields=dropped)
        # SECURITY: any client-supplied `models` / `plugins` is discarded above;
        # rebuild both from the tier's own config so a user can never name an
        # arbitrary upstream model.
        self._apply_routing(payload, tier)
        payload["max_tokens"] = max_output_tokens
        if body.get("stream") is True:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def chat(self, payload: dict[str, Any]) -> httpx.Response:
        return await self._send_with_retry(payload, stream=False)

    async def generate_image(self, payload: dict[str, Any]) -> httpx.Response:
        """POST to the upstream image-generation endpoint (non-streaming).

        Uses the same auth/base-url as chat but a different path. The caller is
        responsible for pinning `model` server-side — a client must never name
        an image model (see SERVER_ONLY_FIELDS rationale).
        """
        url = f"{self._settings.upstream_base_url}/images/generations"
        request = self._client.build_request(
            "POST", url, json=payload, headers=self._auth_headers()
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return await self._client.send(request, stream=False)
            except CONNECT_ERRORS as exc:
                last_error = exc
                if attempt == 0:
                    continue
        logger.error("upstream_image_connect_failed", error=str(last_error))
        raise ApiError(
            status_code=502,
            message="Cannot reach the upstream image provider",
            type="server_error",
            code="upstream_unavailable",
        )

    async def open_stream(self, payload: dict[str, Any]) -> httpx.Response:
        """Start a streaming request and return the (unconsumed) response."""
        return await self._send_with_retry(payload, stream=True)

    async def _send_with_retry(self, payload: dict[str, Any], *, stream: bool) -> httpx.Response:
        url = f"{self._settings.upstream_base_url}/chat/completions"
        request = self._client.build_request(
            "POST", url, json=payload, headers=self._auth_headers()
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                return await self._client.send(request, stream=stream)
            except CONNECT_ERRORS as exc:
                last_error = exc
                if attempt == 0:
                    # Connection never established, so nothing was streamed: safe to retry.
                    continue
        logger.error("upstream_connect_failed", error=str(last_error))
        raise ApiError(
            status_code=502,
            message="Cannot reach the upstream provider",
            type="server_error",
            code="upstream_unavailable",
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def _parse_http_date(value: str) -> datetime | None:
    """Parse an HTTP-date style reset hint.

    RFC 1123 ("Tue, 21 Sep 2026 20:00:00 GMT") and the verbose UTC format
    some providers use for X-RateLimit-Reset (e.g. OpenRouter:
    "Tuesday, February 6, 2024 8:13:17 PM UTC").
    """
    text = value.strip()
    try:
        parsed = parsedate_to_datetime(text)
    except (ValueError, TypeError):
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    for fmt in ("%A, %B %d, %Y %I:%M:%S %p UTC", "%A, %B %d, %Y %H:%M:%S UTC"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _parse_resets_at(value: Any) -> datetime | None:
    """Parse a resets_at hint: epoch seconds (int/str), ISO-8601 string or
    HTTP-date string."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=UTC)
        if isinstance(value, str):
            text = value.strip()
            if text.replace(".", "", 1).isdigit():
                return datetime.fromtimestamp(float(text), tz=UTC)
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return _parse_http_date(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
    except (ValueError, OverflowError, OSError):
        return None
    return None


def _find_body_resets_at(parsed: Any) -> datetime | None:
    """Look for resets_at hints in an upstream 429 body (EVREN style)."""
    if not isinstance(parsed, dict):
        return None
    candidates: list[Any] = []
    error = parsed.get("error")
    if isinstance(error, dict):
        candidates.extend((error.get("resets_at"), error.get("reset_at")))
    candidates.extend((parsed.get("resets_at"), parsed.get("reset_at")))
    for candidate in candidates:
        parsed_dt = _parse_resets_at(candidate)
        if parsed_dt is not None:
            return parsed_dt
    return None


def _to_iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_upstream_error(
    status_code: int, body_text: str, headers: httpx.Headers | None = None
) -> ApiError:
    message = f"Upstream request failed with status {status_code}"
    upstream_code: str | None = None
    parsed: Any = None
    try:
        parsed = json.loads(body_text)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, dict):
            if error.get("message"):
                message = str(error["message"])
            if error.get("code"):
                upstream_code = str(error["code"])
    except ValueError:
        pass

    if status_code == 400:
        return ApiError(
            status_code=400,
            message=message,
            type="invalid_request_error",
            code=upstream_code or "upstream_bad_request",
        )
    if status_code in (401, 403):
        return ApiError(
            status_code=502,
            message="Upstream provider rejected the gateway credentials",
            type="server_error",
            code="upstream_auth_error",
        )
    if status_code == 429:
        now = datetime.now(UTC)
        resets_at = _find_body_resets_at(parsed)
        retry_after: int | None = None
        header_retry_after = headers.get("retry-after") if headers is not None else None
        if header_retry_after is not None:
            try:
                retry_after = max(int(float(header_retry_after)), 0)
            except ValueError:
                retry_after = None
        if retry_after is None and resets_at is None:
            header_reset = headers.get("x-ratelimit-reset") if headers is not None else None
            if header_reset is not None:
                resets_at = _parse_resets_at(header_reset)
        if retry_after is None:
            if resets_at is not None:
                retry_after = max(ceil((resets_at - now).total_seconds()), 1)
            else:
                retry_after = 30
        extra = {"resets_at": _to_iso_z(resets_at)} if resets_at is not None else None
        return ApiError(
            status_code=429,
            message=message,
            type="rate_limit_error",
            code="rate_limited",
            headers={"Retry-After": str(retry_after)},
            extra=extra,
        )
    if status_code == 408:
        return ApiError(
            status_code=504,
            message="Upstream request timed out",
            type="server_error",
            code="timeout",
        )
    return ApiError(status_code=502, message=message, type="server_error", code="upstream_error")
