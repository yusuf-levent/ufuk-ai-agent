from __future__ import annotations

import json
import uuid
from decimal import Decimal

import httpx
import pytest
from app.models.enums import UsageStatus
from app.services.credits import CreditLedger
from app.services.upstream import UpstreamClient
from fastapi import FastAPI
from httpx import AsyncClient
from tests.helpers import register_and_login
from tests.test_gateway import (
    CHAT_URL,
    MESSAGES,
    _period_key,
    get_usage_events,
)
from tests.test_plans_admin import create_plan_direct, create_tier_direct


def chunk_event(
    delta: dict | None = None, finish_reason: str | None = None, usage: dict | None = None
) -> dict:
    event: dict = {
        "id": "chatcmpl-x",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": "dev-model-fast",
        "choices": [],
    }
    if delta is not None or finish_reason is not None:
        event["choices"] = [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}]
    if usage is not None:
        event["usage"] = usage
    return event


def sse_body(events: list[dict]) -> bytes:
    lines = [f"data: {json.dumps(e)}" for e in events]
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def parse_sse(text: str) -> list[dict | str]:
    parsed: list[dict | str] = []
    for line in text.split("\n"):
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            parsed.append("[DONE]")
        else:
            parsed.append(json.loads(payload))
    return parsed


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
async def stream_user(client: AsyncClient, app: FastAPI):
    await create_plan_direct(
        app,
        name="free",
        monthly_credit_limit="100",
        max_output_tokens_per_request=2048,
        requests_per_minute=60,
        allowed_tier_aliases=["fast"],
        is_default=True,
    )
    await create_tier_direct(app)
    headers = await register_and_login(client, "stream@example.com")
    user_id = uuid.UUID((await client.get("/me", headers=headers)).json()["id"])
    return headers, user_id


async def test_streaming_passthrough_with_usage(
    client: AsyncClient, app: FastAPI, install_upstream, stream_user
) -> None:
    headers, user_id = stream_user
    events = [
        chunk_event(delta={"role": "assistant", "content": "Hel"}),
        chunk_event(delta={"content": "lo!"}),
        chunk_event(finish_reason="stop"),
        chunk_event(usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}),
    ]
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, content=sse_body(events), headers={"content-type": "text/event-stream"}
        )

    await install_upstream(handler)

    async with client.stream(
        "POST",
        CHAT_URL,
        json={"model": "fast", "messages": MESSAGES, "stream": True},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        text = (await response.aread()).decode()

    parsed = parse_sse(text)
    assert parsed[-1] == "[DONE]"
    data_events = [e for e in parsed if e != "[DONE]"]
    assert len(data_events) == 4
    contents = [e["choices"][0]["delta"].get("content") for e in data_events[:3]]
    assert contents == ["Hel", "lo!", None]
    assert data_events[2]["choices"][0]["finish_reason"] == "stop"
    assert data_events[3]["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "total_tokens": 12,
    }
    for event in data_events:
        assert event["model"] == "fast"

    upstream_body = json.loads(captured[0].content)
    assert upstream_body["stream"] is True
    assert upstream_body["stream_options"] == {"include_usage": True}
    assert upstream_body["model"] == "dev-model-fast"

    usage_events = await get_usage_events(app, user_id)
    assert len(usage_events) == 1
    assert usage_events[0].status == UsageStatus.SETTLED
    assert usage_events[0].prompt_tokens == 10
    assert usage_events[0].completion_tokens == 2
    assert usage_events[0].estimated is False
    assert usage_events[0].credits_charged == Decimal("0.014000")

    ledger = CreditLedger(app.state.redis)
    assert await ledger.used(user_id, await _period_key(app, user_id)) == Decimal("0.014000")


async def test_streaming_tool_calls_passthrough(
    client: AsyncClient, app: FastAPI, install_upstream, stream_user
) -> None:
    headers, user_id = stream_user
    events = [
        chunk_event(
            delta={
                "role": "assistant",
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": ""},
                    }
                ],
            }
        ),
        chunk_event(delta={"tool_calls": [{"index": 0, "function": {"arguments": '{"pa'}}]}),
        chunk_event(delta={"tool_calls": [{"index": 0, "function": {"arguments": 'th": 1}'}}]}),
        chunk_event(finish_reason="tool_calls"),
        chunk_event(usage={"prompt_tokens": 30, "completion_tokens": 8, "total_tokens": 38}),
    ]
    await install_upstream(
        lambda request: httpx.Response(
            200, content=sse_body(events), headers={"content-type": "text/event-stream"}
        )
    )

    async with client.stream(
        "POST",
        CHAT_URL,
        json={
            "model": "fast",
            "messages": MESSAGES,
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
        },
        headers=headers,
    ) as response:
        text = (await response.aread()).decode()

    parsed = [e for e in parse_sse(text) if e != "[DONE]"]
    tool_calls = [e["choices"][0]["delta"]["tool_calls"][0] for e in parsed[:3]]
    assert tool_calls[0]["id"] == "call_1"
    assert tool_calls[0]["function"]["name"] == "read_file"
    arguments = "".join(tc["function"]["arguments"] for tc in tool_calls)
    assert json.loads(arguments) == {"path": 1}

    usage_events = await get_usage_events(app, user_id)
    assert usage_events[0].prompt_tokens == 30
    assert usage_events[0].completion_tokens == 8


async def test_streaming_missing_usage_estimates(
    client: AsyncClient, app: FastAPI, install_upstream, stream_user
) -> None:
    headers, user_id = stream_user
    events = [
        chunk_event(delta={"role": "assistant", "content": "abcdefgh"}),
        chunk_event(delta={"content": "ijklmnop"}),
        chunk_event(finish_reason="stop"),
    ]
    await install_upstream(
        lambda request: httpx.Response(
            200, content=sse_body(events), headers={"content-type": "text/event-stream"}
        )
    )

    async with client.stream(
        "POST",
        CHAT_URL,
        json={"model": "fast", "messages": MESSAGES, "stream": True},
        headers=headers,
    ) as response:
        text = (await response.aread()).decode()
    assert parse_sse(text)[-1] == "[DONE]"

    usage_events = await get_usage_events(app, user_id)
    assert usage_events[0].status == UsageStatus.SETTLED
    assert usage_events[0].estimated is True
    assert usage_events[0].completion_tokens == 4  # 16 content chars / 4
    assert usage_events[0].prompt_tokens >= 1


async def test_streaming_upstream_error_before_stream(
    client: AsyncClient, app: FastAPI, install_upstream, stream_user
) -> None:
    headers, user_id = stream_user

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"error": {"message": "upstream busy", "type": "rate_limit_error", "code": None}},
            headers={"retry-after": "17"},
        )

    await install_upstream(handler)
    response = await client.post(
        CHAT_URL, json={"model": "fast", "messages": MESSAGES, "stream": True}, headers=headers
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
    assert response.headers["retry-after"] == "17"

    usage_events = await get_usage_events(app, user_id)
    assert usage_events[0].status == UsageStatus.FAILED
    ledger = CreditLedger(app.state.redis)
    assert await ledger.used(user_id, await _period_key(app, user_id)) == Decimal("0.000000")


async def test_client_disconnect_records_partial_usage(
    app: FastAPI, install_upstream, stream_user
) -> None:
    from app.routers.gateway import SseUsageScanner, stream_sse_events

    events = [
        chunk_event(delta={"role": "assistant", "content": "Hel"}),
        chunk_event(delta={"content": "lo!"}),
        chunk_event(delta={"content": "more text"}),
        chunk_event(finish_reason="stop"),
        chunk_event(usage={"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}),
    ]
    await install_upstream(
        lambda request: httpx.Response(
            200, content=sse_body(events), headers={"content-type": "text/event-stream"}
        )
    )
    upstream_client = app.state.upstream
    response = await upstream_client.open_stream(
        {"model": "dev-model-fast", "messages": MESSAGES, "stream": True}
    )
    assert response.status_code == 200

    finalize_calls: list[tuple[int, int, bool]] = []

    async def finalize(prompt_tokens: int, completion_tokens: int, estimated: bool) -> None:
        finalize_calls.append((prompt_tokens, completion_tokens, estimated))

    scanner = SseUsageScanner()
    generator = stream_sse_events(
        response, tier_alias="fast", scanner=scanner, est_prompt=25, finalize=finalize
    )
    first = await generator.__anext__()
    assert b"Hel" in first

    # simulate the client disconnecting mid-stream
    await generator.aclose()

    assert len(finalize_calls) == 1
    prompt_tokens, completion_tokens, estimated = finalize_calls[0]
    assert estimated is True
    assert prompt_tokens == 25
    assert completion_tokens == 1  # only "Hel" (3 chars) was streamed


async def test_stream_generator_full_consumption(
    app: FastAPI, install_upstream, stream_user
) -> None:
    from app.routers.gateway import SseUsageScanner, stream_sse_events

    events = [
        chunk_event(delta={"role": "assistant", "content": "Hi"}),
        chunk_event(finish_reason="stop"),
        chunk_event(usage={"prompt_tokens": 7, "completion_tokens": 1, "total_tokens": 8}),
    ]
    await install_upstream(
        lambda request: httpx.Response(
            200, content=sse_body(events), headers={"content-type": "text/event-stream"}
        )
    )
    upstream_client = app.state.upstream
    response = await upstream_client.open_stream(
        {"model": "dev-model-fast", "messages": MESSAGES, "stream": True}
    )

    finalize_calls: list[tuple[int, int, bool]] = []

    async def finalize(prompt_tokens: int, completion_tokens: int, estimated: bool) -> None:
        finalize_calls.append((prompt_tokens, completion_tokens, estimated))

    scanner = SseUsageScanner()
    generator = stream_sse_events(
        response, tier_alias="fast", scanner=scanner, est_prompt=25, finalize=finalize
    )
    output = b"".join([chunk async for chunk in generator])

    assert b"[DONE]" in output
    assert finalize_calls == [(7, 1, False)]


def test_transform_sse_line_rewrites_model() -> None:
    from app.routers.gateway import _transform_sse_line

    line = b'data: {"model":"dev-model-fast","choices":[{"delta":{"content":"x"}}]}'
    transformed = _transform_sse_line(line, "fast")
    assert json.loads(transformed[6:])["model"] == "fast"
    assert _transform_sse_line(b"data: [DONE]", "fast") == b"data: [DONE]"
    assert _transform_sse_line(b": keep-alive", "fast") == b": keep-alive"
    assert _transform_sse_line(b"data: not-json", "fast") == b"data: not-json"
