from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.dependencies import get_current_user
from app.errors import ApiError
from app.models import UsageEvent, User
from app.models.base import utcnow
from app.models.enums import UsageStatus
from app.schemas.gateway import ChatCompletionRequest
from app.services import subscriptions as subscription_service
from app.services import tiers as tier_service
from app.services import usage_service
from app.services.circuit_breaker import CircuitBreaker
from app.services.credits import (
    CreditLedger,
    ensure_ledger_synced,
    estimate_messages_tokens,
    estimate_tokens,
    reserve_amount,
    token_cost,
)
from app.services.rate_limiter import check_rate_limit
from app.services.upstream import normalize_upstream_error

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["gateway"])

LEDGER_TTL_GRACE_SECONDS = 5 * 24 * 3600

# Upstream-private usage sub-objects (platform billing/routing internals)
# that must never be forwarded to gateway clients.
PROTECTED_USAGE_FIELDS = ("evren",)


def _strip_protected_usage(obj: dict[str, Any]) -> bool:
    """Remove upstream-private fields from a usage object. True if changed."""
    usage = obj.get("usage")
    if not isinstance(usage, dict):
        return False
    changed = False
    for field in PROTECTED_USAGE_FIELDS:
        if field in usage:
            del usage[field]
            changed = True
    return changed


class SseUsageScanner:
    """Scans passthrough SSE lines to capture usage and content size."""

    def __init__(self) -> None:
        self._content_chars = 0
        self.prompt_tokens: int | None = None
        self.completion_tokens: int | None = None
        self.usage_seen = False

    def feed_line(self, line: bytes) -> None:
        if not line.startswith(b"data:"):
            return
        payload = line[5:].strip()
        if not payload or payload == b"[DONE]":
            return
        try:
            obj = json.loads(payload)
        except ValueError:
            return
        if not isinstance(obj, dict):
            return
        usage = obj.get("usage")
        if isinstance(usage, dict):
            if isinstance(usage.get("prompt_tokens"), int):
                self.prompt_tokens = usage["prompt_tokens"]
            if isinstance(usage.get("completion_tokens"), int):
                self.completion_tokens = usage["completion_tokens"]
            self.usage_seen = self.prompt_tokens is not None and self.completion_tokens is not None
        for choice in obj.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            content = delta.get("content")
            if isinstance(content, str):
                self._content_chars += len(content)
            # Reasoning models emit reasoning text that is billed as
            # completion tokens; count it for disconnect estimates.
            for reasoning_key in ("reasoning", "reasoning_content"):
                reasoning = delta.get(reasoning_key)
                if isinstance(reasoning, str):
                    self._content_chars += len(reasoning)
            for tool_call in delta.get("tool_calls") or []:
                if isinstance(tool_call, dict) and isinstance(tool_call.get("function"), dict):
                    arguments = tool_call["function"].get("arguments")
                    if isinstance(arguments, str):
                        self._content_chars += len(arguments)

    def completion_estimate(self) -> int:
        return max(1, (self._content_chars + 3) // 4)


def _transform_sse_line(line: bytes, alias: str) -> bytes:
    """Rewrite the model field of a JSON data line to the tier alias and strip
    upstream-private usage fields."""
    if not line.startswith(b"data:"):
        return line
    payload = line[5:].strip()
    if not payload or payload == b"[DONE]":
        return line
    try:
        obj = json.loads(payload)
    except ValueError:
        return line
    if not isinstance(obj, dict):
        return line
    changed = _strip_protected_usage(obj)
    if isinstance(obj.get("model"), str):
        obj["model"] = alias
        changed = True
    if not changed:
        return line
    return b"data: " + json.dumps(obj, ensure_ascii=False).encode("utf-8")


def _extract_completion_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for choice in data.get("choices") or []:
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        for reasoning_key in ("reasoning", "reasoning_content"):
            reasoning = message.get(reasoning_key)
            if isinstance(reasoning, str):
                parts.append(reasoning)
        for tool_call in message.get("tool_calls") or []:
            if isinstance(tool_call, dict) and isinstance(tool_call.get("function"), dict):
                arguments = tool_call["function"].get("arguments")
                if isinstance(arguments, str):
                    parts.append(arguments)
    return "".join(parts)


async def _finalize_event(
    request: Request,
    *,
    user: User,
    active: subscription_service.ActiveSubscription,
    tier: tier_service.TierView,
    event_id: uuid.UUID,
    reserved_amount: Decimal,
    prompt_tokens: int,
    completion_tokens: int,
    estimated: bool,
    latency_ms: int,
    status: UsageStatus,
) -> None:
    actual = token_cost(tier, prompt_tokens, completion_tokens)
    settled = await usage_service.settle_usage_event(
        request.app.state.database,
        event_id=event_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        credits=actual if status == UsageStatus.SETTLED else Decimal(0),
        estimated=estimated,
        latency_ms=latency_ms,
        status=status,
    )
    if settled:
        ledger = CreditLedger(request.app.state.redis)
        if status == UsageStatus.SETTLED:
            await ledger.adjust(
                user_id=user.id, period_key=active.period_key, delta=actual - reserved_amount
            )
        else:
            await ledger.release(
                user_id=user.id, period_key=active.period_key, amount=reserved_amount
            )


async def _reserve(
    request: Request,
    user: User,
    active: subscription_service.ActiveSubscription,
    tier: tier_service.TierView,
    messages: list[dict[str, Any]],
    requested_max_tokens: int | None,
    cap: int,
) -> tuple[uuid.UUID, int, Decimal, int]:
    database = request.app.state.database
    redis = request.app.state.redis

    max_tokens = cap if requested_max_tokens is None else min(requested_max_tokens, cap)
    est_prompt = estimate_messages_tokens(messages)
    amount = reserve_amount(tier, est_prompt, max_tokens)

    ledger = CreditLedger(redis)
    ttl = int((active.period_end - utcnow()).total_seconds()) + LEDGER_TTL_GRACE_SECONDS
    await ensure_ledger_synced(
        database,
        redis,
        user_id=user.id,
        period_key=active.period_key,
        period_start=active.period_start,
        period_end=active.period_end,
        ttl_seconds=ttl,
    )
    await ledger.reserve(
        user_id=user.id,
        period_key=active.period_key,
        amount=amount,
        limit=active.plan.monthly_credit_limit,
    )

    request_id = uuid.uuid4()
    async with database.session() as session:
        event = UsageEvent(
            request_id=request_id,
            user_id=user.id,
            tier_alias=tier.alias,
            upstream_model_id=tier.upstream_model_id,
            credits_charged=amount,
            estimated=True,
            status=UsageStatus.RESERVED,
        )
        session.add(event)
        await session.commit()
        event_id = event.id
    return event_id, est_prompt, amount, max_tokens


async def _fail_event(
    request: Request,
    *,
    user: User,
    active: subscription_service.ActiveSubscription,
    tier: tier_service.TierView,
    event_id: uuid.UUID,
    reserved_amount: Decimal,
    est_prompt: int,
    started: float,
) -> None:
    await _finalize_event(
        request,
        user=user,
        active=active,
        tier=tier,
        event_id=event_id,
        reserved_amount=reserved_amount,
        prompt_tokens=est_prompt,
        completion_tokens=0,
        estimated=True,
        latency_ms=int((time.monotonic() - started) * 1000),
        status=UsageStatus.FAILED,
    )


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> JSONResponse | StreamingResponse:
    started = time.monotonic()
    database = request.app.state.database
    redis = request.app.state.redis

    active = await subscription_service.get_active_subscription(database, user.id)
    if active is None:
        raise ApiError(
            status_code=403,
            message="No active subscription",
            type="permission_error",
            code="subscription_inactive",
        )

    tier = await tier_service.get_tier(database, redis, body.model)
    if tier is None or tier.alias not in active.plan.allowed_tier_aliases:
        raise ApiError(
            status_code=403,
            message=f"Model '{body.model}' is not available on your plan",
            type="permission_error",
            code="model_not_allowed",
        )

    retry_after = await check_rate_limit(
        redis,
        key=f"rpm:{user.id}:{active.period_key}",
        limit=active.plan.requests_per_minute,
        window_seconds=60,
    )
    if retry_after is not None:
        resets_at = utcnow() + timedelta(seconds=retry_after)
        raise ApiError(
            status_code=429,
            message="Requests-per-minute limit exceeded",
            type="rate_limit_error",
            code="rate_limited",
            headers={"Retry-After": str(retry_after)},
            extra={"resets_at": resets_at.isoformat().replace("+00:00", "Z")},
        )

    breaker = request.app.state.circuit_breaker
    if not await breaker.allow_request():
        raise ApiError(
            status_code=503,
            message="Upstream provider temporarily unavailable",
            type="server_error",
            code="upstream_unavailable",
            headers={"Retry-After": "30"},
        )

    cap = min(tier.max_output_tokens, active.plan.max_output_tokens_per_request)
    event_id, est_prompt, reserved_amount, max_tokens = await _reserve(
        request, user, active, tier, body.messages, body.max_tokens, cap
    )

    upstream_client = request.app.state.upstream
    payload = upstream_client.sanitize_request(
        body.model_dump(exclude_unset=True), tier=tier, max_output_tokens=max_tokens
    )

    if body.stream is True:
        return await _stream_response(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            est_prompt=est_prompt,
            reserved_amount=reserved_amount,
            payload=payload,
            started=started,
        )

    try:
        response = await upstream_client.chat(payload)
    except ApiError:
        await breaker.record_failure()
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise
    except httpx.TimeoutException as exc:
        await breaker.record_failure()
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise ApiError(
            status_code=504,
            message="Upstream request timed out",
            type="server_error",
            code="timeout",
        ) from exc
    except httpx.HTTPError as exc:
        await breaker.record_failure()
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise ApiError(
            status_code=502,
            message="Upstream request failed",
            type="server_error",
            code="upstream_error",
        ) from exc

    await _record_breaker_outcome(breaker, response.status_code)

    if response.status_code != 200:
        error = normalize_upstream_error(response.status_code, response.text, response.headers)
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise error

    data = response.json()
    if isinstance(data, dict):
        _strip_protected_usage(data)
    usage = data.get("usage") if isinstance(data, dict) else None
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    estimated = not (isinstance(prompt_tokens, int) and isinstance(completion_tokens, int))
    if not isinstance(prompt_tokens, int):
        prompt_tokens = est_prompt
    if not isinstance(completion_tokens, int):
        completion_tokens = estimate_tokens(_extract_completion_text(data))

    latency_ms = int((time.monotonic() - started) * 1000)
    await _finalize_event(
        request,
        user=user,
        active=active,
        tier=tier,
        event_id=event_id,
        reserved_amount=reserved_amount,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated=estimated,
        latency_ms=latency_ms,
        status=UsageStatus.SETTLED,
    )
    data["model"] = tier.alias
    logger.info(
        "gateway_request_completed",
        user_id=str(user.id),
        request_id=str(event_id),
        tier_alias=tier.alias,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated=estimated,
        latency_ms=latency_ms,
        status=200,
    )
    return JSONResponse(content=data)


async def stream_sse_events(
    upstream_response: httpx.Response,
    *,
    tier_alias: str,
    scanner: SseUsageScanner,
    est_prompt: int,
    finalize: Callable[[int, int, bool], Awaitable[None]],
) -> AsyncIterator[bytes]:
    """Passthrough SSE generator: rewrites the model field line by line,
    records usage when the stream ends or the client disconnects."""

    async def _finalize_partial() -> None:
        prompt_tokens = scanner.prompt_tokens if scanner.prompt_tokens is not None else est_prompt
        completion_tokens = (
            scanner.completion_tokens
            if scanner.completion_tokens is not None
            else scanner.completion_estimate()
        )
        await finalize(prompt_tokens, completion_tokens, not scanner.usage_seen)

    buffer = b""
    try:
        async for chunk in upstream_response.aiter_bytes():
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                scanner.feed_line(line)
                yield _transform_sse_line(line, tier_alias) + b"\n"
        if buffer:
            scanner.feed_line(buffer)
            yield _transform_sse_line(buffer, tier_alias) + b"\n"
    finally:
        await upstream_response.aclose()
        # shield: keep the settlement alive even if the client just disconnected
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.shield(_finalize_partial())


async def _record_breaker_outcome(breaker: CircuitBreaker, status_code: int) -> None:
    if status_code == 200 or status_code in (400, 402, 422, 429):
        await breaker.record_success()
    else:
        await breaker.record_failure()


@router.get("/models")
async def list_models(request: Request, user: User = Depends(get_current_user)) -> dict[str, Any]:
    database = request.app.state.database
    active = await subscription_service.get_active_subscription(database, user.id)
    if active is None:
        raise ApiError(
            status_code=403,
            message="No active subscription",
            type="permission_error",
            code="subscription_inactive",
        )
    from sqlalchemy import select

    from app.models import ModelTier

    async with database.session() as session:
        tiers = (
            (
                await session.execute(
                    select(ModelTier)
                    .where(
                        ModelTier.enabled.is_(True),
                        ModelTier.alias.in_(active.plan.allowed_tier_aliases),
                    )
                    .order_by(ModelTier.alias)
                )
            )
            .scalars()
            .all()
        )
    return {
        "object": "list",
        "data": [
            {
                "id": tier.alias,
                "object": "model",
                "created": int(tier.created_at.timestamp()),
                "owned_by": tier.upstream_provider_name,
                "details": {
                    "display_name": tier.display_name,
                    "upstream_provider": tier.upstream_provider_name,
                    "upstream_model": tier.upstream_model_id,
                    "max_output_tokens": tier.max_output_tokens,
                    "context_window": tier.context_window,
                },
            }
            for tier in tiers
        ],
    }


async def _stream_response(
    request: Request,
    *,
    user: User,
    active: subscription_service.ActiveSubscription,
    tier: tier_service.TierView,
    event_id: uuid.UUID,
    est_prompt: int,
    reserved_amount: Decimal,
    payload: dict[str, Any],
    started: float,
) -> StreamingResponse:
    upstream_client = request.app.state.upstream

    try:
        upstream_response = await upstream_client.open_stream(payload)
    except ApiError:
        await request.app.state.circuit_breaker.record_failure()
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise
    except httpx.TimeoutException as exc:
        await request.app.state.circuit_breaker.record_failure()
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise ApiError(
            status_code=504,
            message="Upstream request timed out",
            type="server_error",
            code="timeout",
        ) from exc
    except httpx.HTTPError as exc:
        await request.app.state.circuit_breaker.record_failure()
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise ApiError(
            status_code=502,
            message="Upstream request failed",
            type="server_error",
            code="upstream_error",
        ) from exc

    await _record_breaker_outcome(request.app.state.circuit_breaker, upstream_response.status_code)

    if upstream_response.status_code != 200:
        body_text = (await upstream_response.aread()).decode("utf-8", errors="replace")
        error = normalize_upstream_error(
            upstream_response.status_code, body_text, upstream_response.headers
        )
        await upstream_response.aclose()
        await _fail_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            est_prompt=est_prompt,
            started=started,
        )
        raise error

    scanner = SseUsageScanner()

    async def finalize(prompt_tokens: int, completion_tokens: int, estimated: bool) -> None:
        await _finalize_event(
            request,
            user=user,
            active=active,
            tier=tier,
            event_id=event_id,
            reserved_amount=reserved_amount,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            estimated=estimated,
            latency_ms=int((time.monotonic() - started) * 1000),
            status=UsageStatus.SETTLED,
        )

    logger.info(
        "gateway_stream_started",
        user_id=str(user.id),
        request_id=str(event_id),
        tier_alias=tier.alias,
    )
    return StreamingResponse(
        stream_sse_events(
            upstream_response,
            tier_alias=tier.alias,
            scanner=scanner,
            est_prompt=est_prompt,
            finalize=finalize,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
