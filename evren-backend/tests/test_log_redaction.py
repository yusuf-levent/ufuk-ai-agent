from __future__ import annotations

import json

import httpx
import pytest
import structlog
from app.logging import configure_logging, redact_processor
from fastapi import FastAPI
from httpx import AsyncClient
from tests.test_gateway import CHAT_URL, completion_response
from tests.test_gateway import install_upstream as install_upstream_fixture
from tests.test_plans_admin import create_plan_direct, create_tier_direct

install_upstream = install_upstream_fixture


@pytest.fixture
async def redaction_user(client: AsyncClient, app: FastAPI):
    await create_plan_direct(app)
    await create_tier_direct(app)
    from tests.helpers import register_and_login

    return await register_and_login(client, "redact@example.com")


async def test_gateway_logs_contain_no_bodies_or_secrets(
    client: AsyncClient, app: FastAPI, install_upstream, redaction_user
) -> None:
    headers = redaction_user
    secret_prompt = "TOPSECRETPROMPT-do-not-log-1234"
    secret_api_key = "sk-client-should-never-leak"
    auth_header_value = headers["Authorization"]

    captured: list[dict] = []

    def capture(logger, method_name, event_dict):
        captured.append(dict(event_dict))
        return event_dict

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            redact_processor,
            capture,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        cache_logger_on_first_use=False,
    )
    try:
        await install_upstream(lambda request: httpx.Response(200, json=completion_response()))
        response = await client.post(
            CHAT_URL,
            json={
                "model": "fast",
                "messages": [{"role": "user", "content": secret_prompt}],
                "api_key": secret_api_key,
            },
            headers=headers,
        )
        assert response.status_code == 200
    finally:
        configure_logging(app.state.settings)

    assert captured, "expected gateway log events"
    dump = json.dumps(captured, default=str)
    assert secret_prompt not in dump
    assert secret_api_key not in dump
    assert auth_header_value not in dump
    assert "test-upstream-key" not in dump

    completed = [e for e in captured if e.get("event") == "gateway_request_completed"]
    assert completed
    event = completed[0]
    assert event["tier_alias"] == "fast"
    assert event["prompt_tokens"] == 10
    assert event["latency_ms"] >= 0

    dropped = [e for e in captured if e.get("event") == "dropped_request_fields"]
    assert dropped
    assert dropped[0]["fields"] == ["api_key"]


async def test_console_email_sender_redacts_token_in_structured_output(
    client: AsyncClient, app: FastAPI
) -> None:
    captured: list[dict] = []

    def capture(logger, method_name, event_dict):
        captured.append(dict(event_dict))
        return event_dict

    structlog.configure(
        processors=[
            redact_processor,
            capture,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        cache_logger_on_first_use=False,
    )
    try:
        response = await client.post(
            "/auth/register",
            json={"email": "logs@example.com", "password": "Passw0rd!123"},
        )
        assert response.status_code == 201
    finally:
        configure_logging(app.state.settings)

    email_events = [e for e in captured if e.get("event") == "email_sent"]
    assert email_events
    dump = json.dumps(email_events, default=str)
    assert "Passw0rd!123" not in dump
