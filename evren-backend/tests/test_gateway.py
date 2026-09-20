from __future__ import annotations

import json
import uuid
from decimal import Decimal

import httpx
import pytest
from app.models import UsageEvent
from app.models.enums import UsageStatus
from app.services.credits import CreditLedger
from app.services.upstream import UpstreamClient
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select
from tests.helpers import register_and_login
from tests.test_plans_admin import create_plan_direct, create_tier_direct

CHAT_URL = "/v1/chat/completions"

MESSAGES = [{"role": "user", "content": "hello"}]


def completion_response(
    *, content: str = "Hi there!", usage: dict | None = None, model: str = "dev-model-fast"
) -> dict:
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage
        if usage is not None
        else {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
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
    await create_plan_direct(
        app,
        name="free",
        monthly_credit_limit="100",
        max_output_tokens_per_request=2048,
        requests_per_minute=60,
        allowed_tier_aliases=["fast", "balanced"],
        is_default=True,
    )
    await create_tier_direct(app)
    await create_tier_direct(
        app,
        alias="balanced",
        display_name="Balanced",
        upstream_model_id="dev-model-balanced",
        input_credits_per_1k_tokens="2.0",
        output_credits_per_1k_tokens="4.0",
        max_output_tokens=2048,
    )
    headers = await register_and_login(client, "gw@example.com")
    user_id = (await client.get("/me", headers=headers)).json()["id"]
    return headers, uuid.UUID(user_id)


async def get_usage_events(app: FastAPI, user_id: uuid.UUID) -> list[UsageEvent]:
    async with app.state.database.session() as session:
        events = (
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
        for event in events:
            await session.refresh(event)
    return list(events)


def request_json(request: httpx.Request) -> dict:
    return json.loads(request.content.decode())


async def test_non_streaming_completion(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_response())

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["model"] == "fast"
    assert data["choices"][0]["message"]["content"] == "Hi there!"

    upstream_body = request_json(captured[0])
    assert upstream_body["model"] == "dev-model-fast"
    assert captured[0].headers["Authorization"] == "Bearer test-upstream-key"
    assert "user" not in upstream_body

    events = await get_usage_events(app, user_id)
    assert len(events) == 1
    assert events[0].status == UsageStatus.SETTLED
    assert events[0].prompt_tokens == 10
    assert events[0].completion_tokens == 5
    assert events[0].estimated is False
    assert events[0].credits_charged == Decimal("0.020000")

    ledger = CreditLedger(app.state.redis)
    active_key = await _period_key(app, user_id)
    assert await ledger.used(user_id, active_key) == Decimal("0.020000")


async def _period_key(app: FastAPI, user_id: uuid.UUID) -> str:
    from app.services import subscriptions as subscription_service

    active = await subscription_service.get_active_subscription(app.state.database, user_id)
    assert active is not None
    return active.period_key


async def test_tool_call_passthrough(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user
    tool_response = {
        "id": "chatcmpl-tool",
        "object": "chat.completion",
        "created": 1700000000,
        "model": "dev-model-fast",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": '{"path": "x"}'},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }
    await install_upstream(lambda request: httpx.Response(200, json=tool_response))

    response = await client.post(
        CHAT_URL,
        json={
            "model": "fast",
            "messages": MESSAGES,
            "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
            "tool_choice": "auto",
        },
        headers=headers,
    )
    assert response.status_code == 200
    assert (
        response.json()["choices"][0]["message"]["tool_calls"]
        == tool_response["choices"][0]["message"]["tool_calls"]
    )

    events = await get_usage_events(app, user_id)
    assert events[0].prompt_tokens == 20
    assert events[0].completion_tokens == 10


async def test_missing_usage_estimated(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user
    body = completion_response(content="abcdefgh" * 10)
    body.pop("usage")
    await install_upstream(lambda request: httpx.Response(200, json=body))

    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 200
    events = await get_usage_events(app, user_id)
    assert events[0].status == UsageStatus.SETTLED
    assert events[0].estimated is True
    assert events[0].completion_tokens == 20
    assert events[0].prompt_tokens >= 1


async def test_unknown_and_dangerous_fields_dropped(
    client: AsyncClient, install_upstream, gateway_user
) -> None:
    headers, _ = gateway_user
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_response())

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL,
        json={
            "model": "fast",
            "messages": MESSAGES,
            "temperature": 0.5,
            "top_p": 0.9,
            "stop": ["\n"],
            "user": "should-be-stripped",
            "routing": {"provider": "evil"},
            "base_url": "https://evil.example.com",
            "api_key": "sk-evil",
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = request_json(captured[0])
    assert body["temperature"] == 0.5
    assert body["top_p"] == 0.9
    assert body["stop"] == ["\n"]
    for forbidden in ("user", "routing", "base_url", "api_key"):
        assert forbidden not in body


async def test_max_tokens_clamped(client: AsyncClient, install_upstream, gateway_user) -> None:
    headers, _ = gateway_user
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=completion_response())

    await install_upstream(handler)
    await client.post(
        CHAT_URL,
        json={"model": "fast", "messages": MESSAGES, "max_tokens": 999999},
        headers=headers,
    )
    assert request_json(captured[0])["max_tokens"] == 1024

    await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES, "max_tokens": 16}, headers=headers
    )
    assert request_json(captured[1])["max_tokens"] == 16


async def test_quota_exceeded_never_calls_upstream(
    client: AsyncClient, app: FastAPI, install_upstream
) -> None:
    await create_plan_direct(
        app,
        name="tiny",
        monthly_credit_limit="0.000001",
        allowed_tier_aliases=["fast"],
        is_default=True,
    )
    await create_tier_direct(app)
    headers = await register_and_login(client, "tiny@example.com")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("upstream must not be called when quota is exhausted")

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 402
    assert response.json()["error"]["code"] == "quota_exceeded"


async def test_rpm_limit(client: AsyncClient, app: FastAPI, install_upstream) -> None:
    await create_plan_direct(
        app,
        name="free",
        requests_per_minute=1,
        allowed_tier_aliases=["fast"],
        is_default=True,
    )
    await create_tier_direct(app)
    headers = await register_and_login(client, "slow@example.com")
    await install_upstream(lambda request: httpx.Response(200, json=completion_response()))

    first = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert first.status_code == 200
    second = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"
    assert int(second.headers["retry-after"]) >= 1


async def test_model_not_allowed(client: AsyncClient, install_upstream, gateway_user) -> None:
    headers, _ = gateway_user
    await install_upstream(lambda request: httpx.Response(200, json=completion_response()))
    response = await client.post(
        CHAT_URL, json={"model": "strong", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "model_not_allowed"


async def test_subscription_inactive(client: AsyncClient, app: FastAPI, install_upstream) -> None:
    await create_tier_direct(app)
    headers = await register_and_login(client, "orphan@example.com")
    await install_upstream(lambda request: httpx.Response(200, json=completion_response()))
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "subscription_inactive"


async def test_gateway_requires_auth(client: AsyncClient) -> None:
    response = await client.post(CHAT_URL, json={"model": "fast", "messages": MESSAGES})
    assert response.status_code == 401


async def test_upstream_error_releases_reserve(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500, json={"error": {"message": "model exploded", "type": "server_error", "code": None}}
        )

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_error"
    assert response.json()["error"]["message"] == "model exploded"

    events = await get_usage_events(app, user_id)
    assert len(events) == 1
    assert events[0].status == UsageStatus.FAILED
    assert events[0].credits_charged == Decimal("0.000000")

    ledger = CreditLedger(app.state.redis)
    assert await ledger.used(user_id, await _period_key(app, user_id)) == Decimal("0.000000")


async def test_idempotent_settle_never_double_charges(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_user
) -> None:
    headers, user_id = gateway_user
    await install_upstream(lambda request: httpx.Response(200, json=completion_response()))

    await client.post(CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers)
    events = await get_usage_events(app, user_id)
    event = events[0]
    assert event.status == UsageStatus.SETTLED

    from app.services import usage_service

    settled_again = await usage_service.settle_usage_event(
        app.state.database,
        event_id=event.id,
        prompt_tokens=10,
        completion_tokens=5,
        credits=Decimal("0.020000"),
        estimated=False,
        latency_ms=5,
        status=UsageStatus.SETTLED,
    )
    assert settled_again is False
    events = await get_usage_events(app, user_id)
    assert events[0].credits_charged == Decimal("0.020000")
