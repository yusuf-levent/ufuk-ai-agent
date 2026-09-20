from __future__ import annotations

import json
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
    }
)

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
        dropped = sorted(set(body) - ALLOWED_REQUEST_FIELDS - {"model", "stream"})
        if dropped:
            logger.info("dropped_request_fields", fields=dropped)
        payload["model"] = tier.upstream_model_id
        payload["max_tokens"] = max_output_tokens
        if body.get("stream") is True:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def chat(self, payload: dict[str, Any]) -> httpx.Response:
        return await self._send_with_retry(payload, stream=False)

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


def normalize_upstream_error(
    status_code: int, body_text: str, headers: httpx.Headers | None = None
) -> ApiError:
    message = f"Upstream request failed with status {status_code}"
    upstream_code: str | None = None
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
        retry_after = headers.get("retry-after") if headers is not None else None
        response_headers = {"Retry-After": retry_after if retry_after else "30"}
        return ApiError(
            status_code=429,
            message=message,
            type="rate_limit_error",
            code="rate_limited",
            headers=response_headers,
        )
    if status_code == 408:
        return ApiError(
            status_code=504,
            message="Upstream request timed out",
            type="server_error",
            code="timeout",
        )
    return ApiError(status_code=502, message=message, type="server_error", code="upstream_error")
