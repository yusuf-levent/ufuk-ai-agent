from __future__ import annotations

import httpx
import pytest
from app.services.upstream import normalize_upstream_error
from fastapi import FastAPI
from httpx import AsyncClient
from tests.helpers import register_and_login
from tests.test_gateway import (
    CHAT_URL,
    MESSAGES,
    completion_response,
)
from tests.test_gateway import install_upstream as install_upstream_fixture
from tests.test_plans_admin import create_plan_direct, create_tier_direct

install_upstream = install_upstream_fixture


def test_normalize_upstream_error_mapping() -> None:
    error = normalize_upstream_error(500, '{"error": {"message": "boom", "type": "server_error"}}')
    assert error.status_code == 502
    assert error.code == "upstream_error"
    assert error.message == "boom"

    error = normalize_upstream_error(400, '{"error": {"message": "bad input"}}')
    assert error.status_code == 400
    assert error.code == "upstream_bad_request"

    error = normalize_upstream_error(401, "denied")
    assert error.status_code == 502
    assert error.code == "upstream_auth_error"

    error = normalize_upstream_error(403, "nope")
    assert error.status_code == 502
    assert error.code == "upstream_auth_error"

    error = normalize_upstream_error(408, "slow")
    assert error.status_code == 504
    assert error.code == "timeout"

    error = normalize_upstream_error(
        429, '{"error": {"message": "slow down"}}', headers=httpx.Headers({"retry-after": "42"})
    )
    assert error.status_code == 429
    assert error.headers is not None
    assert error.headers["Retry-After"] == "42"

    error = normalize_upstream_error(503, "not json at all")
    assert error.status_code == 502
    assert "503" in error.message


@pytest.fixture
async def gateway_setup(client: AsyncClient, app: FastAPI):
    async def setup(email: str, **plan_overrides) -> dict[str, str]:
        plan_body = {
            "name": "free",
            "monthly_credit_limit": "100",
            "max_output_tokens_per_request": 2048,
            "requests_per_minute": 60,
            "allowed_tier_aliases": ["fast"],
            "is_default": True,
        }
        plan_body.update(plan_overrides)
        await create_plan_direct(app, **plan_body)
        await create_tier_direct(app)
        return await register_and_login(client, email)

    return setup


async def test_retry_once_on_connect_error(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_setup
) -> None:
    headers = await gateway_setup("retry@example.com")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=completion_response())

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 200
    assert len(calls) == 2


async def test_both_connect_attempts_fail(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_setup
) -> None:
    headers = await gateway_setup("retryfail@example.com")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        raise httpx.ConnectError("connection refused")

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert len(calls) == 2


async def test_timeout_normalized_to_504(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_setup
) -> None:
    headers = await gateway_setup("timeout@example.com")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out")

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "timeout"


async def test_circuit_breaker_opens_after_consecutive_failures(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_setup
) -> None:
    headers = await gateway_setup("breaker@example.com")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"error": {"message": "down"}})

    await install_upstream(handler)
    for _ in range(5):
        response = await client.post(
            CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
        )
        assert response.status_code == 502

    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_unavailable"
    assert len(calls) == 5


async def test_breaker_success_resets_counter(
    client: AsyncClient, app: FastAPI, install_upstream, gateway_setup
) -> None:
    headers = await gateway_setup("breaker2@example.com")
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) <= 2:
            return httpx.Response(500, json={"error": {"message": "down"}})
        return httpx.Response(200, json=completion_response())

    await install_upstream(handler)
    for _ in range(2):
        await client.post(CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 200
    for _ in range(4):
        await client.post(CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES}, headers=headers
    )
    assert response.status_code == 200
