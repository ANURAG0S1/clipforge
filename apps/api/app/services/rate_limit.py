"""Per-key fixed-window rate limiting backed by Redis."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from redis.asyncio import Redis

from app.core.config import get_settings


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_s: int


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_s: int) -> RateLimitResult: ...


class RedisRateLimiter:
    def __init__(self, redis: "Redis") -> None:
        self._redis = redis

    async def hit(self, key: str, limit: int, window_s: int) -> RateLimitResult:
        if limit <= 0 or window_s <= 0:
            raise ValueError("limit and window_s must be positive")
        redis_key = f"ratelimit:{key}"
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_s, nx=True)
            pipe.ttl(redis_key)
            count, _, ttl = await pipe.execute()
        used = int(count)
        retry_after = int(ttl) if int(ttl) > 0 else window_s
        return RateLimitResult(
            allowed=used <= limit, remaining=max(0, limit - used), retry_after_s=retry_after
        )


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimiter:
    return RedisRateLimiter(Redis.from_url(str(get_settings().redis_url)))
