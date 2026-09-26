from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class CircuitBreaker:
    """In-process breaker: fail fast while the upstream is failing."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        return self._clock() - self._opened_at < self._cooldown_seconds

    async def allow_request(self) -> bool:
        async with self._lock:
            if self._opened_at is None:
                return True
            # half-open after the cooldown: let one probe through
            return self._clock() - self._opened_at >= self._cooldown_seconds

    async def record_success(self) -> None:
        async with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = self._clock()
