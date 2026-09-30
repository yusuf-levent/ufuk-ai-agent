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

from app.db import Database
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
    BudgetLedger,
    CreditLedger,
    ensure_ledger_synced,
    estimate_messages_tokens,
    estimate_tokens,
    reserve_amount,
    token_cost,
)
from app.services.rate_limiter import check_rate_limit
from app.services.session_guard import SessionGuard
from app.services.upstream import normalize_upstream_error

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/v1", tags=["gateway"])

LEDGER_TTL_GRACE_SECONDS = 5 * 24 * 3600

# Upstream-private usage sub-objects/fields (platform billing/routing internals)
# that must never be forwarded to gateway clients: `evren` (EVREN platform
# credits + routed model) and `cost` (OpenRouter-style upstream USD cost).
PROTECTED_USAGE_FIELDS = ("evren", "cost")


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
        self.cached_prompt_tokens: int = 0
        self.cache_write_tokens: int = 0
        self.reasoning_tokens: int = 0
        self.upstream_cost_usd: Decimal | None = None
        self.selected_model_id: str | None = None
        self.finish_reason: str | None = None
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
        if isinstance(obj.get("model"), str):
            self.selected_model_id = obj["model"]
        usage = obj.get("usage")
        if isinstance(usage, dict):
            if isinstance(usage.get("prompt_tokens"), int):
                self.prompt_tokens = usage["prompt_tokens"]
            if isinstance(usage.get("completion_tokens"), int):
                self.completion_tokens = usage["completion_tokens"]
            cost = usage.get("cost")
            if isinstance(cost, (int, float)):
                self.upstream_cost_usd = Decimal(str(cost))
            details = usage.get("prompt_tokens_details")
            if isinstance(details, dict):
                if isinstance(details.get("cached_tokens"), int):
                    self.cached_prompt_tokens = details["cached_tokens"]
                if isinstance(details.get("cache_write_tokens"), int):
                    self.cache_write_tokens = details["cache_write_tokens"]
            comp_details = usage.get("completion_tokens_details")
            if isinstance(comp_details, dict) and isinstance(
                comp_details.get("reasoning_tokens"), int
            ):
                self.reasoning_tokens = comp_details["reasoning_tokens"]
            self.usage_seen = self.prompt_tokens is not None and self.completion_tokens is not None
        for choice in obj.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            if isinstance(choice.get("finish_reason"), str) and self.finish_reason is None:
                self.finish_reason = choice["finish_reason"]
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


def _extract_selected_model(data: dict[str, Any], tier: tier_service.TierView) -> str:
    """Concrete upstream model that served the request.

    For plain tiers this equals ``tier.upstream_model_id``; for ``auto`` /
    router tiers the upstream reports the model it actually picked, which is
    what cost attribution needs.
    """
    model = data.get("model") if isinstance(data, dict) else None
    return model if isinstance(model, str) and model else tier.upstream_model_id


def _extract_parent_request_id(request: Request) -> uuid.UUID | None:
    """Parent request id for sub-agent chain tracking.

    The desktop sends ``X-Ufuk-Parent-Request-Id`` when a sub-agent call is
    made on behalf of a user-visible request, so the full cost of one user
    message can be summed across the whole chain.
    """
    raw = request.headers.get("x-ufuk-parent-request-id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def _client_key(request: Request) -> str | None:
    """Coarse client identity for soft anomaly detection.

    Combines the client IP with the user agent. Only a salted hash of this is
    ever stored (see SessionGuard._client_hash) — the raw value lives for the
    duration of the request and is never persisted or logged.
    """
    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    if not ip and not user_agent:
        return None
    return f"{ip or ''}|{user_agent or ''}"


async def _flag_user_for_review(database: Database, user_id: uuid.UUID, reason: str) -> None:
    """Set the SOFT abuse flag. Never bans — a human reviews the account."""
    from sqlalchemy import update

    from app.models import User

    async with database.session() as session:
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(security_flagged=True, security_flag_reason=reason[:200])
        )
        await session.commit()
    logger.info("security_flag_set", user_id=str(user_id), reason=reason)


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
    cached_prompt_tokens: int = 0,
    cache_write_tokens: int = 0,
    reasoning_tokens: int = 0,
    upstream_cost_usd: Decimal | None = None,
    selected_model_id: str | None = None,
    parent_request_id: uuid.UUID | None = None,
    session_id: str | None = None,
    finish_reason: str | None = None,
) -> None:
    actual = token_cost(
        tier,
        prompt_tokens,
        completion_tokens,
        cached_prompt_tokens=cached_prompt_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
    )
    settled = await usage_service.settle_usage_event(
        request.app.state.database,
        event_id=event_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        credits=actual if status == UsageStatus.SETTLED else Decimal(0),
        estimated=estimated,
        latency_ms=latency_ms,
        status=status,
        upstream_cost_usd=upstream_cost_usd,
        cached_prompt_tokens=cached_prompt_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        selected_model_id=selected_model_id,
        parent_request_id=parent_request_id,
        session_id=session_id,
        finish_reason=finish_reason,
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

    # Release the in-flight slot (account-sharing concurrency cap). This is the
    # single terminal point for every request path — success, failure, timeout
    # and client-disconnect all funnel through here — so the slot can never
    # leak. The flag is cleared to keep a double finalize from releasing twice.
    guard: SessionGuard | None = getattr(request.state, "session_guard", None)
    if guard is not None and getattr(request.state, "guard_slot_held", False):
        request.state.guard_slot_held = False
        await guard.release_slot(user_id=user.id, held=True)


async def _reserve(
    request: Request,
    user: User,
    active: subscription_service.ActiveSubscription,
    tier: tier_service.TierView,
    messages: list[dict[str, Any]],
    requested_max_tokens: int | None,
    cap: int,
    session_id: str | None = None,
) -> tuple[uuid.UUID, int, Decimal, int]:
    database = request.app.state.database
    redis = request.app.state.redis

    max_tokens = cap if requested_max_tokens is None else min(requested_max_tokens, cap)
    est_prompt = estimate_messages_tokens(messages)
    amount = reserve_amount(tier, est_prompt, max_tokens)

    # Per-request ceiling: one LLM call may never reserve more than this, so a
    # single runaway prompt (huge context + huge max_tokens) cannot drain the
    # whole period in one shot.
    per_request_cap = active.plan.max_credits_per_request
    if per_request_cap is not None and amount > per_request_cap:
        raise ApiError(
            status_code=402,
            message="Single request exceeds the per-request credit budget",
            type="insufficient_quota",
            code="request_budget_exceeded",
        )

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

    # Rolling-window ceiling: the sub-agent cost kill-switch. A nested
    # sub-agent chain fires many calls in a burst; each is individually under
    # the per-request cap, so only a window budget stops the blow-up.
    window_cap = active.plan.max_credits_per_window
    if window_cap is not None:
        try:
            await BudgetLedger(redis).consume(
                user_id=user.id,
                amount=amount,
                limit=window_cap,
                window_seconds=active.plan.budget_window_seconds,
            )
        except ApiError:
            # Roll the period ledger back so the rejected request leaves no
            # phantom reservation behind.
            await ledger.release(
                user_id=user.id, period_key=active.period_key, amount=amount
            )
            raise

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
            parent_request_id=_extract_parent_request_id(request),
            session_id=session_id,
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
    # SECURITY: internal tiers serve hidden sub-agent / server-side work only.
    # A user request naming one is rejected outright — otherwise a user could
    # pick the hidden (often pricier) model and bypass the curated picker.
    if tier.is_internal:
        raise ApiError(
            status_code=403,
            message=f"Model '{body.model}' is not available on your plan",
            type="permission_error",
            code="model_not_allowed",
        )

    # Global rate limit — protects the single OpenRouter key
    global_retry = await check_rate_limit(
        redis,
        key="global:rpm",
        limit=request.app.state.settings.global_rate_limit_per_minute,
        window_seconds=60,
    )
    if global_retry is not None:
        raise ApiError(
            status_code=429,
            message="Service is busy, please retry shortly",
            type="rate_limit_error",
            code="rate_limited",
            headers={"Retry-After": str(global_retry)},
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

    # ---- Account-sharing deterrents (layers 2 and 3) ----------------------
    # Layer 2: concurrency cap. Acquired BEFORE reserving credits so a rejected
    # request never touches the ledger. Released in _finalize_event, the single
    # terminal point of every request path.
    guard = SessionGuard(redis)
    slot_held = await guard.acquire_slot(
        user_id=user.id, limit=active.plan.max_concurrent_requests
    )
    request.state.session_guard = guard
    request.state.guard_slot_held = slot_held

    # Layer 3: soft anomaly detection. Advisory only — never blocks. A pattern
    # that looks like a shared account sets a review flag on the user row.
    flag_reason = await guard.observe(
        user_id=user.id, client_key=_client_key(request)
    )
    if flag_reason and not user.security_flagged:
        await _flag_user_for_review(database, user.id, flag_reason)

    try:
        event_id, est_prompt, reserved_amount, max_tokens = await _reserve(
            request, user, active, tier, body.messages, body.max_tokens, cap,
            session_id=body.session_id,
        )
    except BaseException:
        request.state.guard_slot_held = False
        await guard.release_slot(user_id=user.id, held=slot_held)
        raise

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
            session_id=body.session_id,
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
    # Capture upstream-private cost BEFORE stripping it from the client
    # response: the real USD cost is internal margin data, never exposed.
    upstream_cost_usd: Decimal | None = None
    reasoning_tokens = 0
    finish_reason: str | None = None
    if isinstance(data, dict):
        usage_obj = data.get("usage")
        if isinstance(usage_obj, dict):
            cost = usage_obj.get("cost")
            if isinstance(cost, (int, float)):
                upstream_cost_usd = Decimal(str(cost))
            details = usage_obj.get("completion_tokens_details")
            if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
                reasoning_tokens = details["reasoning_tokens"]
        for choice in data.get("choices") or []:
            if isinstance(choice, dict) and isinstance(choice.get("finish_reason"), str):
                finish_reason = choice["finish_reason"]
                break
        _strip_protected_usage(data)
    usage = data.get("usage") if isinstance(data, dict) else None
    prompt_tokens = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    completion_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    cached_prompt_tokens = 0
    cache_write_tokens = 0
    if isinstance(usage, dict):
        details = usage.get("prompt_tokens_details")
        if isinstance(details, dict):
            cached_prompt_tokens = details.get("cached_tokens") or 0
            cache_write_tokens = details.get("cache_write_tokens") or 0
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
        cached_prompt_tokens=cached_prompt_tokens,
        cache_write_tokens=cache_write_tokens,
        reasoning_tokens=reasoning_tokens,
        upstream_cost_usd=upstream_cost_usd,
        selected_model_id=_extract_selected_model(data, tier),
        parent_request_id=_extract_parent_request_id(request),
        session_id=body.session_id,
        finish_reason=finish_reason,
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
    finalize: Callable[..., Awaitable[None]],
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
        await finalize(
            prompt_tokens,
            completion_tokens,
            not scanner.usage_seen,
            scanner.cached_prompt_tokens,
            scanner.cache_write_tokens,
            scanner.reasoning_tokens,
            scanner.upstream_cost_usd,
            scanner.selected_model_id,
            scanner.finish_reason,
        )

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
                        # Internal tiers are hidden sub-agent/server-side
                        # models: never listed to users.
                        ModelTier.is_internal.is_(False),
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
                    "output_modalities": list(tier.output_modalities or ["text"]),
                    "supports_tools": bool(tier.supports_tools),
                    "pricing_unit": str(tier.pricing_unit),
                    "price_note": tier.price_note,
                    "price_note_tr": tier.price_note_tr,
                    "speed_hint": tier.speed_hint,
                    "quality_hint": tier.quality_hint,
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
    session_id: str | None = None,
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

    async def finalize(
        prompt_tokens: int,
        completion_tokens: int,
        estimated: bool,
        cached_prompt_tokens: int = 0,
        cache_write_tokens: int = 0,
        reasoning_tokens: int = 0,
        upstream_cost_usd: Decimal | None = None,
        selected_model_id: str | None = None,
        finish_reason: str | None = None,
    ) -> None:
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
            cached_prompt_tokens=cached_prompt_tokens,
            cache_write_tokens=cache_write_tokens,
            reasoning_tokens=reasoning_tokens,
            upstream_cost_usd=upstream_cost_usd,
            selected_model_id=selected_model_id or tier.upstream_model_id,
            parent_request_id=_extract_parent_request_id(request),
            session_id=session_id,
            finish_reason=finish_reason,
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
