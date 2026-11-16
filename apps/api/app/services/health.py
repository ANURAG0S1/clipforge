"""Dependency health checks used by ``GET /healthz``."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping

from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import get_engine
from app.schemas.health import CheckResult, HealthReport
from app.services.storage import get_storage

HealthCheck = Callable[[], Awaitable[None]]


async def check_database() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis() -> None:
    client: Redis = Redis.from_url(str(get_settings().redis_url))
    try:
        if not await client.ping():
            raise RuntimeError("redis PING returned a falsy reply")
    finally:
        await client.aclose()


async def check_storage() -> None:
    await get_storage().ping()


def default_checks() -> dict[str, HealthCheck]:
    return {"database": check_database, "redis": check_redis, "storage": check_storage}


async def _run_one(check: HealthCheck, timeout_s: float) -> CheckResult:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(check(), timeout=timeout_s)
    except TimeoutError:
        return CheckResult(ok=False, latency_ms=_ms(started), error=f"timed out after {timeout_s}s")
    except Exception as exc:
        # Surface the exception type and message, never connection strings or credentials.
        return CheckResult(ok=False, latency_ms=_ms(started), error=type(exc).__name__)
    return CheckResult(ok=True, latency_ms=_ms(started), error=None)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


async def run_health_checks(checks: Mapping[str, HealthCheck], timeout_s: float) -> HealthReport:
    names = list(checks)
    results = await asyncio.gather(*(_run_one(checks[n], timeout_s) for n in names))
    by_name = dict(zip(names, results, strict=True))
    ok = all(r.ok for r in results)
    return HealthReport(status="ok" if ok else "degraded", checks=by_name)
