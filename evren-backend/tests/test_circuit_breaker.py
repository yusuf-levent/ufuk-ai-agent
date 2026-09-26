from __future__ import annotations

from app.services.circuit_breaker import CircuitBreaker


async def test_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0, clock=lambda: 0.0)
    assert await breaker.allow_request() is True
    for _ in range(3):
        await breaker.record_failure()
    assert breaker.is_open is True
    assert await breaker.allow_request() is False


async def test_success_resets() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=30.0, clock=lambda: 0.0)
    await breaker.record_failure()
    await breaker.record_failure()
    await breaker.record_success()
    await breaker.record_failure()
    assert breaker.is_open is False


async def test_half_open_after_cooldown() -> None:
    now = 100.0
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=30.0, clock=lambda: now)
    await breaker.record_failure()
    await breaker.record_failure()
    assert await breaker.allow_request() is False

    now = 131.0
    assert await breaker.allow_request() is True

    await breaker.record_failure()
    assert await breaker.allow_request() is False


async def test_half_open_success_closes() -> None:
    now = 100.0
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=30.0, clock=lambda: now)
    await breaker.record_failure()
    await breaker.record_failure()

    now = 200.0
    assert await breaker.allow_request() is True
    await breaker.record_success()
    assert await breaker.allow_request() is True
    assert breaker.is_open is False
