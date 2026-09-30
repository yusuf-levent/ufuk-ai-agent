"""Account-sharing deterrents: concurrency cap + soft anomaly detection.

Finans/hesap güvenliği çekirdeği — bu testler özellikle titiz:
- slot bırakma HER yolda olmalı (başarı, hata, timeout, disconnect) yoksa
  kullanıcı kilitlenir (finansal zarar: kullanamadığı aboneliğe para öder)
- anomali tespiti asla bloke etmemeli (soft flag)
- ham IP/cihaz kimliği asla saklanmamalı (gizlilik)
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from app.errors import ApiError
from app.services.session_guard import SessionGuard
from fastapi import FastAPI
from httpx import AsyncClient
from tests.helpers import register_and_login
from tests.test_gateway import completion_response
from tests.test_plans_admin import create_plan_direct, create_tier_direct


async def test_acquire_slot_no_limit_means_no_tracking(app: FastAPI) -> None:
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()
    held = await guard.acquire_slot(user_id=user_id, limit=None)
    assert held is False
    # No key created when unlimited.
    assert await app.state.redis.get(f"inflight:{user_id}") is None


async def test_acquire_slot_up_to_limit_then_reject(app: FastAPI) -> None:
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()

    assert await guard.acquire_slot(user_id=user_id, limit=2) is True
    assert await guard.acquire_slot(user_id=user_id, limit=2) is True

    with pytest.raises(ApiError) as excinfo:
        await guard.acquire_slot(user_id=user_id, limit=2)
    assert excinfo.value.status_code == 429
    assert excinfo.value.code == "concurrency_limit_exceeded"
    # The rejected acquire must not leak a slot.
    assert int(await app.state.redis.get(f"inflight:{user_id}")) == 2


async def test_release_slot_frees_capacity(app: FastAPI) -> None:
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()

    await guard.acquire_slot(user_id=user_id, limit=1)
    with pytest.raises(ApiError):
        await guard.acquire_slot(user_id=user_id, limit=1)

    await guard.release_slot(user_id=user_id, held=True)
    # Capacity is back: a new acquire succeeds.
    assert await guard.acquire_slot(user_id=user_id, limit=1) is True


async def test_release_slot_not_held_is_noop(app: FastAPI) -> None:
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()
    await guard.release_slot(user_id=user_id, held=False)
    assert await app.state.redis.get(f"inflight:{user_id}") is None


async def test_release_slot_never_goes_negative(app: FastAPI) -> None:
    """A double release must not drive the counter negative, which would let
    the account exceed its cap afterwards."""
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()
    await guard.acquire_slot(user_id=user_id, limit=2)
    await guard.release_slot(user_id=user_id, held=True)
    await guard.release_slot(user_id=user_id, held=True)  # spurious second release
    await guard.release_slot(user_id=user_id, held=True)  # and a third
    value = int(await app.state.redis.get(f"inflight:{user_id}"))
    assert value >= 0
    # Cap still enforced: two acquires fill the limit, the third is rejected.
    await guard.acquire_slot(user_id=user_id, limit=2)
    await guard.acquire_slot(user_id=user_id, limit=2)
    with pytest.raises(ApiError):
        await guard.acquire_slot(user_id=user_id, limit=2)


async def test_observe_flags_many_distinct_clients(app: FastAPI) -> None:
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()
    now = 5_000_000.0

    reason = None
    for i in range(4):
        reason = await guard.observe(
            user_id=user_id,
            client_key=f"10.0.0.{i}|agent-{i}",
            distinct_threshold=5,
            burst_threshold=500,
            now=now,
        )
        assert reason is None, f"flagged too early at client {i}"

    reason = await guard.observe(
        user_id=user_id,
        client_key="10.0.0.9|agent-9",
        distinct_threshold=5,
        burst_threshold=500,
        now=now,
    )
    assert reason is not None
    assert reason.startswith("distinct_clients:5")


async def test_observe_flags_burst_requests(app: FastAPI) -> None:
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()
    now = 6_000_000.0

    reason = None
    for _ in range(499):
        reason = await guard.observe(
            user_id=user_id,
            client_key="same-client",
            distinct_threshold=5,
            burst_threshold=500,
            now=now,
        )
    assert reason is None
    reason = await guard.observe(
        user_id=user_id,
        client_key="same-client",
        distinct_threshold=5,
        burst_threshold=500,
        now=now,
    )
    assert reason == "burst_requests:500"


async def test_observe_same_client_never_flags(app: FastAPI) -> None:
    """One honest user on one machine must never trip the distinct-client flag,
    no matter how many requests they make."""
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()
    now = 7_000_000.0
    for _ in range(50):
        reason = await guard.observe(
            user_id=user_id,
            client_key="1.2.3.4|ua",
            distinct_threshold=5,
            burst_threshold=500,
            now=now,
        )
        assert reason is None


async def test_observe_window_boundary_resets_counts(app: FastAPI) -> None:
    guard = SessionGuard(app.state.redis)
    user_id = uuid.uuid4()
    window = 3600
    t0 = 8_000_000.0
    for i in range(4):
        await guard.observe(
            user_id=user_id,
            client_key=f"c{i}",
            window_seconds=window,
            distinct_threshold=5,
            burst_threshold=500,
            now=t0,
        )
    # Next window: distinct-client count starts over.
    reason = await guard.observe(
        user_id=user_id,
        client_key="c-new",
        window_seconds=window,
        distinct_threshold=5,
        burst_threshold=500,
        now=t0 + window,
    )
    assert reason is None


def test_client_hash_is_salted_per_user_and_not_reversible() -> None:
    """Same client key under two accounts must hash differently, so stored sets
    cannot be mined for cross-account linkage."""
    a = SessionGuard._client_hash(uuid.uuid4(), "1.2.3.4|ua")
    b = SessionGuard._client_hash(uuid.uuid4(), "1.2.3.4|ua")
    assert a != b
    assert "1.2.3.4" not in a
    assert SessionGuard._client_hash(uuid.uuid4(), None) == "unknown"


# ---------------------------------------------------------------------------
# Gateway integration — the concurrency cap must hold AND always release.
# ---------------------------------------------------------------------------


@pytest.fixture
async def install_upstream(app: FastAPI):
    from app.services.upstream import UpstreamClient

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
async def guarded_user(client: AsyncClient, app: FastAPI):
    """User on a plan with max_concurrent_requests=1 (the tightest cap)."""
    await create_plan_direct(
        app,
        name="free",
        monthly_credit_limit="1000",
        max_output_tokens_per_request=2048,
        requests_per_minute=600,
        max_concurrent_requests=1,
        allowed_tier_aliases=["fast"],
        is_default=True,
    )
    await create_tier_direct(app)
    headers = await register_and_login(client, "guard@example.com")
    user_id = uuid.UUID((await client.get("/me", headers=headers)).json()["id"])
    return headers, user_id


async def test_gateway_enforces_concurrency_cap(
    client: AsyncClient, app: FastAPI, install_upstream, guarded_user
) -> None:
    """With max_concurrent_requests=1, a second acquire is rejected and the
    rejection does not consume the slot."""
    headers, user_id = guarded_user
    await install_upstream(lambda request: httpx.Response(200, json=completion_response()))

    # Occupy the single slot directly, simulating an in-flight request.
    guard = SessionGuard(app.state.redis)
    assert await guard.acquire_slot(user_id=user_id, limit=1) is True

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "fast", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "concurrency_limit_exceeded"

    # The rejected request must not have leaked its own slot.
    assert int(await app.state.redis.get(f"inflight:{user_id}")) == 1


async def test_gateway_releases_slot_after_success(
    client: AsyncClient, app: FastAPI, install_upstream, guarded_user
) -> None:
    headers, user_id = guarded_user
    await install_upstream(lambda request: httpx.Response(200, json=completion_response()))

    for _ in range(3):
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "fast", "messages": [{"role": "user", "content": "hi"}]},
            headers=headers,
        )
        assert response.status_code == 200
    # Every request released its slot: the counter is back to zero, so a limit
    # of 1 never blocked a sequential user.
    assert int(await app.state.redis.get(f"inflight:{user_id}")) == 0


async def test_gateway_releases_slot_after_upstream_failure(
    client: AsyncClient, app: FastAPI, install_upstream, guarded_user
) -> None:
    """THE lockout guard: a failed request must release its slot, otherwise the
    user is permanently locked out of a plan they paid for."""
    headers, user_id = guarded_user
    await install_upstream(
        lambda request: httpx.Response(500, json={"error": {"message": "boom", "code": 500}})
    )

    response = await client.post(
        "/v1/chat/completions",
        json={"model": "fast", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    assert response.status_code == 502
    assert int(await app.state.redis.get(f"inflight:{user_id}")) == 0

    # And the user can immediately try again (slot is free).
    await install_upstream(lambda request: httpx.Response(200, json=completion_response()))
    response = await client.post(
        "/v1/chat/completions",
        json={"model": "fast", "messages": [{"role": "user", "content": "hi"}]},
        headers=headers,
    )
    assert response.status_code == 200


async def test_register_records_terms_acceptance(client: AsyncClient, app: FastAPI) -> None:
    from app.models import User
    from sqlalchemy import select

    response = await client.post(
        "/auth/register",
        json={
            "email": "terms-reg@example.com",
            "password": "Passw0rd!123",
            "accept_terms": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["terms_accepted_at"] is not None
    assert data["terms_version"] == "2026-09"

    async with app.state.database.session() as session:
        user = await session.scalar(select(User).where(User.email == "terms-reg@example.com"))
        assert user is not None
        assert user.terms_accepted_at is not None


async def test_register_without_terms_is_grandfathered(client: AsyncClient, app: FastAPI) -> None:
    """Accounts created without the clause stay usable — we never retroactively
    lock out users over a term added later."""
    response = await client.post(
        "/auth/register",
        json={"email": "no-terms@example.com", "password": "Passw0rd!123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["terms_accepted_at"] is None
    assert data["terms_version"] is None
