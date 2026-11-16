import asyncio

from fastapi import FastAPI
from httpx import AsyncClient

from app.api.routes.health import get_health_checks
from app.services.health import HealthCheck


async def _ok() -> None:
    return None


async def _boom() -> None:
    raise ConnectionRefusedError("postgresql://clipforge:secret@db refused")


async def _hang() -> None:
    await asyncio.sleep(60)


def _override(app: FastAPI, checks: dict[str, HealthCheck]) -> None:
    app.dependency_overrides[get_health_checks] = lambda: checks


async def test_healthz_all_green(app: FastAPI, client: AsyncClient) -> None:
    _override(app, {"database": _ok, "redis": _ok, "storage": _ok})
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert set(body["checks"]) == {"database", "redis", "storage"}
    assert all(c["ok"] for c in body["checks"].values())


async def test_healthz_failure_returns_503_without_leaking(
    app: FastAPI, client: AsyncClient
) -> None:
    _override(app, {"database": _boom, "redis": _ok, "storage": _ok})
    resp = await client.get("/healthz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == {
        "ok": False,
        "latency_ms": body["checks"]["database"]["latency_ms"],
        "error": "ConnectionRefusedError",
    }
    assert "secret" not in resp.text
    assert body["checks"]["redis"]["ok"] is True


async def test_healthz_times_out_hanging_dependency(app: FastAPI, client: AsyncClient) -> None:
    _override(app, {"database": _ok, "redis": _hang, "storage": _ok})
    resp = await asyncio.wait_for(client.get("/healthz"), timeout=10)
    assert resp.status_code == 503
    assert "timed out" in resp.json()["checks"]["redis"]["error"]


def test_default_checks_cover_all_dependencies() -> None:
    from app.services.health import default_checks

    assert set(default_checks()) == {"database", "redis", "storage"}
