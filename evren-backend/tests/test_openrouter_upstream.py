"""OpenRouter-style upstream verification (Milestone 1.3).

The gateway must be switchable to OpenRouter by env only
(UPSTREAM_BASE_URL / UPSTREAM_API_KEY / UPSTREAM_AUTH_HEADER). These tests run
the real request path against an httpx.MockTransport handler that mimics
documented OpenRouter behavior:

- streaming: `: OPENROUTER PROCESSING` comment keep-alive lines, data chunks,
  usage (incl. an upstream `cost` field) in the FINAL chunk, then `[DONE]`;
- errors: `{"error": {"message": ..., "code": <int>}}` bodies;
- 429 rate limits: `X-RateLimit-Reset` as a verbose UTC HTTP-date string
  (e.g. "Tuesday, February 6, 2024 8:13:17 PM UTC");
- auth: `Authorization: Bearer <key>` by default, `X-API-Key` when configured.

Behavioral guarantees under test: Retry-After is forwarded on upstream 429,
`error.resets_at` is derived from the reset hint, upstream `usage.cost` is
stripped from client responses, and failed requests are never charged
(usage row FAILED with credits_charged=0, ledger released).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.config import Settings
from app.models import UsageEvent
from app.models.enums import UsageStatus
from app.services.upstream import UpstreamClient
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from tests.helpers import register_and_login
from tests.test_gateway import MESSAGES, completion_response
from tests.test_plans_admin import create_plan_direct, create_tier_direct

CHAT_URL = "/v1/chat/completions"

OPENROUTER_BODY = {
    "alias": "fast",
    "display_name": "Fast",
    "upstream_model_id": "openrouter/fast-placeholder",  # placeholder, not a real model id
    "upstream_provider_name": "openrouter",
    "input_credits_per_1k_tokens": "1.0",
    "output_credits_per_1k_tokens": "2.0",
    "max_output_tokens": 1024,
    "context_window": 128000,
    "enabled": True,
}


@pytest.fixture
async def install_upstream(app: FastAPI):
    created: list[UpstreamClient] = []

    async def install(handler) -> UpstreamClient:
        client = UpstreamClient(app.state.settings, transport=httpx.MockTransport(handler))
        created.append(client)
        app.state.upstream = client
        return client

    yield install
    for client in created:
        await client.aclose()


@pytest.fixture
async def gateway_user(client: AsyncClient, app: FastAPI):
    await create_plan_direct(app)
    await create_tier_direct(app, **OPENROUTER_BODY)
    headers = await register_and_login(client, "or@example.com")
    user_id = uuid.UUID((await client.get("/me", headers=headers)).json()["id"])
    return headers, user_id


async def usage_events(app: FastAPI, user_id: uuid.UUID) -> list[UsageEvent]:
    async with app.state.database.session() as session:
        rows = (
            (
                await session.execute(
                    select(UsageEvent)
                    .where(UsageEvent.user_id == user_id)
                    .order_by(UsageEvent.created_at)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await session.refresh(row)
    return list(rows)


def sse(*events: bytes) -> bytes:
    return b"\n".join(events) + b"\n"


async def test_openrouter_nonstreaming_usage_and_cost_stripped(
    client, app, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user
    requests_seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(request)
        body = completion_response(model="openrouter/fast-placeholder")
        body["usage"]["cost"] = 0.000123  # OpenRouter-style upstream USD cost
        return httpx.Response(200, json=body)

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["model"] == "fast"
    assert data["usage"]["prompt_tokens"] == 10
    assert data["usage"]["completion_tokens"] == 5
    assert "cost" not in data["usage"]  # upstream billing internals never forwarded
    assert "evren" not in data["usage"]

    # the upstream model id is never sent to the client outside /v1/models details
    assert "openrouter/fast-placeholder" not in response.text

    # request went out with the tier's upstream model id
    sent = json.loads(requests_seen[0].content.decode())
    assert sent["model"] == "openrouter/fast-placeholder"

    events = await usage_events(app, user_id)
    assert len(events) == 1
    assert events[0].status == UsageStatus.SETTLED
    assert str(events[0].credits_charged) == "0.020000"  # (10*1 + 5*2) / 1000


async def test_openrouter_streaming_final_chunk_usage(
    client, app, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user

    def handler(request: httpx.Request) -> httpx.Response:
        final = {
            "id": "gen-123",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": "openrouter/fast-placeholder",
            "choices": [],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cost": 0.000123,
            },
        }
        body = sse(
            b": OPENROUTER PROCESSING",
            b'data: {"id":"gen-123","object":"chat.completion.chunk","created":1700000000,'
            b'"model":"openrouter/fast-placeholder","choices":[{"index":0,"delta":'
            b'{"role":"assistant","content":"Hi"},"finish_reason":null}]}',
            b": OPENROUTER PROCESSING",
            b'data: {"id":"gen-123","object":"chat.completion.chunk","created":1700000000,'
            b'"model":"openrouter/fast-placeholder","choices":[{"index":0,"delta":'
            b'{"content":"!"},"finish_reason":"stop"}]}',
            b"data: " + json.dumps(final).encode(),
            b"data: [DONE]",
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL,
        json={"model": "fast", "messages": MESSAGES, "stream": True},
        headers=headers,
    )
    assert response.status_code == 200
    text = response.text
    assert "OPENROUTER PROCESSING" in text  # comments pass through
    assert '"model": "fast"' in text  # alias rewritten (re-serialized lines)
    assert "openrouter/fast-placeholder" not in text  # upstream id never leaks
    assert "cost" not in text  # upstream USD cost stripped
    assert "[DONE]" in text

    events = await usage_events(app, user_id)
    assert len(events) == 1
    assert events[0].status == UsageStatus.SETTLED
    assert events[0].estimated is False  # real usage from the final chunk
    assert events[0].prompt_tokens == 10
    assert events[0].completion_tokens == 5
    assert str(events[0].credits_charged) == "0.020000"


async def test_openrouter_429_forwards_retry_after_and_never_charges(
    client, app, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user
    resets_at = datetime.now(UTC) + timedelta(seconds=45)
    verbose_date = resets_at.strftime("%A, %B %d, %Y %I:%M:%S %p UTC")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "Rate limit exceeded: free-models-per-day", "code": 429}},
            headers={"X-RateLimit-Reset": verbose_date},
        )

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 429, response.text
    error = response.json()["error"]
    assert error["code"] == "rate_limited"
    assert "free-models-per-day" in error["message"]
    assert 0 < int(response.headers["retry-after"]) <= 45
    assert "resets_at" in error

    # never charged: the row is FAILED with zero credits and the reserve released
    events = await usage_events(app, user_id)
    assert len(events) == 1
    assert events[0].status == UsageStatus.FAILED
    assert str(events[0].credits_charged) == "0.000000"

    # the released reserve means the very next request is NOT blocked by quota
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion_response(model="openrouter/fast-placeholder"))

    await install_upstream(ok_handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 200, response.text
    events = await usage_events(app, user_id)
    assert len(events) == 2
    assert events[1].status == UsageStatus.SETTLED
    assert str(events[1].credits_charged) == "0.020000"


async def test_openrouter_429_retry_after_header_precedence(
    client, app, install_upstream, gateway_user
) -> None:
    headers, _user_id = gateway_user

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "Rate limited", "code": 429}},
            headers={"Retry-After": "7", "X-RateLimit-Reset": "Tue, 21 Sep 2026 20:00:00 GMT"},
        )

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "7"


async def test_openrouter_auth_error_maps_to_502_and_never_charges(
    client, app, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "User not found", "code": 401}})

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "upstream_auth_error"
    # credentials/keys are never leaked in the response
    assert "User not found" not in response.text

    events = await usage_events(app, user_id)
    assert len(events) == 1
    assert events[0].status == UsageStatus.FAILED
    assert str(events[0].credits_charged) == "0.000000"


async def test_openrouter_provider_error_maps_to_502(
    client, app, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            502,
            json={
                "error": {
                    "message": "Provider returned error",
                    "code": 502,
                    "metadata": {"provider": "Example"},
                }
            },
        )

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == "upstream_error"
    assert "Provider returned error" in response.json()["error"]["message"]

    events = await usage_events(app, user_id)
    assert len(events) == 1
    assert events[0].status == UsageStatus.FAILED
    assert str(events[0].credits_charged) == "0.000000"


def _settings(**overrides) -> Settings:
    values = {
        "upstream_api_key": "sk-or-test-placeholder",
        "jwt_secret": "x" * 40,
        "database_url": "postgresql+asyncpg://x",
        "redis_url": "redis://x",
    }
    values.update(overrides)
    return Settings(**values)


async def test_env_only_switch_to_openrouter_url_and_bearer_auth() -> None:
    """UPSTREAM_BASE_URL/UPSTREAM_API_KEY/UPSTREAM_AUTH_HEADER fully determine
    where requests go and how they authenticate — no code change needed."""
    settings = _settings(upstream_base_url="https://openrouter.ai/api/v1")
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_response())

    client = UpstreamClient(settings, transport=httpx.MockTransport(handler))
    try:
        await client.chat({"model": "x", "messages": []})
    finally:
        await client.aclose()
    assert captured[0].url == "https://openrouter.ai/api/v1/chat/completions"
    assert captured[0].headers["authorization"] == "Bearer sk-or-test-placeholder"


async def test_env_only_switch_auth_header_style() -> None:
    settings = _settings(
        upstream_base_url="https://openrouter.ai/api/v1", upstream_auth_header="X-API-Key"
    )
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_response())

    client = UpstreamClient(settings, transport=httpx.MockTransport(handler))
    try:
        await client.chat({"model": "x", "messages": []})
    finally:
        await client.aclose()
    assert captured[0].headers["x-api-key"] == "sk-or-test-placeholder"
    assert "authorization" not in captured[0].headers
