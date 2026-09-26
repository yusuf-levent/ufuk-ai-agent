from __future__ import annotations

from redis.asyncio import Redis


async def check_rate_limit(
    redis: Redis, *, key: str, limit: int, window_seconds: int
) -> int | None:
    """Fixed-window counter. Returns retry-after seconds when limited, else None."""
    count = await redis.incr(key)
    ttl = await redis.ttl(key)
    if ttl < 0:
        await redis.expire(key, window_seconds)
    if count > limit:
        return max(ttl, 1)
    return None


async def register_failure(redis: Redis, *, key: str, window_seconds: int) -> None:
    count = await redis.incr(key)
    if count == 1 or await redis.ttl(key) < 0:
        await redis.expire(key, window_seconds)


async def retry_after_if_blocked(redis: Redis, *, key: str, limit: int) -> int | None:
    count = await redis.get(key)
    if count is not None and int(count) >= limit:
        ttl = await redis.ttl(key)
        return max(ttl, 1)
    return None
