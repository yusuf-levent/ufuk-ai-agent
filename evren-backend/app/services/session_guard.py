"""Account-sharing deterrents: concurrency cap + soft anomaly detection.

Layer 2 and 3 of the sharing defence (layer 1 is the contractual terms clause
recorded at signup). Design rules, taken from how Claude/Copilot/Devin handle
this:

* Never auto-ban. Patterns that LOOK like sharing also occur for honest power
  users, so we only set a soft review flag.
* Store no raw identifiers. We track counts and hashed client keys only — no
  IP addresses or device fingerprints are persisted (see docs/privacy-rules.md).
* Fail open on infrastructure errors. A Redis blip must never lock paying
  users out of the product.
"""

from __future__ import annotations

import hashlib
import time
import uuid

from redis.asyncio import Redis

from app.errors import ApiError

#: How long an in-flight request slot lives before it self-releases. Bounds
#: blast radius if a worker dies mid-request and never releases its slot.
CONCURRENCY_SLOT_TTL_SECONDS = 600

#: Sliding-ish window (fixed buckets) over which burst activity is counted.
ANOMALY_WINDOW_SECONDS = 3600

#: Distinct client keys inside the window that suggest a shared account.
#: Generous on purpose: phones + laptops + a CI box is normal for one person.
DISTINCT_CLIENT_FLAG_THRESHOLD = 5

#: Requests inside the window that suggest scripted/shared abuse.
BURST_FLAG_THRESHOLD = 500


class SessionGuard:
    """Concurrency limiter + soft anomaly detector backed by Redis."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    # ---- Layer 2: concurrent in-flight request cap ------------------------

    @staticmethod
    def _concurrency_key(user_id: uuid.UUID) -> str:
        return f"inflight:{user_id}"

    async def acquire_slot(
        self, *, user_id: uuid.UUID, limit: int | None
    ) -> bool:
        """Claim an in-flight slot. Returns True when the caller owns a slot
        (and MUST later call :meth:`release_slot`), False when no limit applies.

        Raises ``429 concurrency_limit_exceeded`` when the account already has
        ``limit`` requests in flight.
        """
        if limit is None:
            return False
        key = self._concurrency_key(user_id)
        count = await self._redis.incr(key)
        if count == 1:
            await self._redis.expire(key, CONCURRENCY_SLOT_TTL_SECONDS)
        if count > limit:
            await self._redis.decr(key)
            raise ApiError(
                status_code=429,
                message="Too many concurrent requests on this account",
                type="rate_limit_error",
                code="concurrency_limit_exceeded",
                headers={"Retry-After": "5"},
            )
        return True

    async def release_slot(self, *, user_id: uuid.UUID, held: bool) -> None:
        if not held:
            return
        key = self._concurrency_key(user_id)
        remaining = await self._redis.decr(key)
        # Never let a double-release drive the counter negative.
        if remaining is not None and int(remaining) < 0:
            await self._redis.set(key, "0", ex=CONCURRENCY_SLOT_TTL_SECONDS)

    # ---- Layer 3: soft anomaly detection ----------------------------------

    @staticmethod
    def _client_hash(user_id: uuid.UUID, client_key: str | None) -> str:
        """HMAC-free keyed hash: we only need cardinality, not reversibility.

        Salting with the user id means the same IP hashes differently per
        account, so the stored set cannot be mined for cross-account linkage.
        """
        if not client_key:
            return "unknown"
        digest = hashlib.sha256(f"{user_id}:{client_key}".encode()).hexdigest()
        return digest[:16]

    @staticmethod
    def _anomaly_bucket(window_seconds: int, *, now: float | None = None) -> int:
        moment = time.time() if now is None else now
        return int(moment // window_seconds)

    async def observe(
        self,
        *,
        user_id: uuid.UUID,
        client_key: str | None,
        window_seconds: int = ANOMALY_WINDOW_SECONDS,
        distinct_threshold: int = DISTINCT_CLIENT_FLAG_THRESHOLD,
        burst_threshold: int = BURST_FLAG_THRESHOLD,
        now: float | None = None,
    ) -> str | None:
        """Record one request; return a flag reason when the account crosses a
        soft-abuse threshold, else None.

        The caller decides what to do with the reason (persist a review flag).
        Nothing here blocks the request — detection is advisory by design.
        """
        bucket = self._anomaly_bucket(window_seconds, now=now)
        base = f"anomaly:{user_id}:{bucket}"
        pipe = self._redis.pipeline(transaction=False)
        pipe.sadd(f"{base}:clients", self._client_hash(user_id, client_key))
        pipe.scard(f"{base}:clients")
        pipe.incr(f"{base}:count")
        pipe.expire(f"{base}:clients", window_seconds + 60)
        pipe.expire(f"{base}:count", window_seconds + 60)
        results = await pipe.execute()
        distinct_clients = int(results[1])
        request_count = int(results[2])

        if distinct_clients >= distinct_threshold:
            return f"distinct_clients:{distinct_clients}"
        if request_count >= burst_threshold:
            return f"burst_requests:{request_count}"
        return None
