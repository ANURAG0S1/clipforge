"""Test configuration. A complete, valid environment is installed before any app import.

Database-backed tests run against a real PostgreSQL (``clipforge_test`` database, created on
demand). Locally, start one with ``docker compose up -d postgres``. Without a reachable
database those tests are skipped, except in CI (``CI=true``), where they fail instead.
"""

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

TEST_ENV: dict[str, str] = {
    "DATABASE_URL": "postgresql+asyncpg://clipforge:clipforge@localhost:5432/clipforge_test",
    "REDIS_URL": "redis://localhost:6379/15",
    "S3_ENDPOINT": "http://localhost:9000",
    "S3_PUBLIC_ENDPOINT": "http://localhost:9000",
    "S3_ACCESS_KEY": "minioadmin",
    "S3_SECRET_KEY": "minioadmin",
    "S3_BUCKET": "clipforge-test",
    "ANTHROPIC_API_KEY": "sk-ant-test-key",
    "JWT_SECRET": "test-secret-that-is-definitely-longer-than-32-chars",
    "LOG_LEVEL": "WARNING",
}
for _k, _v in TEST_ENV.items():
    os.environ.setdefault(_k, _v)


def _test_database_url(url: str) -> str:
    """Tests drop and recreate tables, so they only ever touch a database named ``*_test``."""
    base, _, name = url.rpartition("/")
    name = name.split("?", 1)[0]
    return url if name.endswith("_test") else f"{base}/{name}_test"


os.environ["DATABASE_URL"] = _test_database_url(os.environ["DATABASE_URL"])

import asyncpg  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import pipeline  # noqa: E402
from app.services.rate_limit import get_rate_limiter  # noqa: E402
from app.services.storage import get_storage  # noqa: E402
from tests.support.fakes import FakeStorage, InMemoryRateLimiter  # noqa: E402

_DB_URL = make_url(os.environ["DATABASE_URL"])
_schema_ready = False


async def _ensure_database() -> None:
    """Create the test database if needed and (re)build the schema once per session."""
    global _schema_ready
    if _schema_ready:
        return
    dsn = (
        f"postgresql://{_DB_URL.username}:{_DB_URL.password}@{_DB_URL.host}:{_DB_URL.port or 5432}"
    )
    try:
        conn = await asyncpg.connect(f"{dsn}/postgres", timeout=3)
    except (OSError, asyncpg.PostgresError) as exc:
        if os.environ.get("CI") == "true":
            raise
        pytest.skip(f"PostgreSQL not reachable for DB tests: {type(exc).__name__}")
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", _DB_URL.database
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_DB_URL.database}"')
    finally:
        await conn.close()

    engine = create_async_engine(_DB_URL, poolclass=NullPool)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    await engine.dispose()
    _schema_ready = True


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    await _ensure_database()
    engine = create_async_engine(_DB_URL, poolclass=NullPool)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as c:
            tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
            await c.execute(text(f"TRUNCATE {tables} CASCADE"))
        await engine.dispose()


@pytest.fixture
def storage(tmp_path: Path) -> FakeStorage:
    root = tmp_path / "s3"
    root.mkdir()
    return FakeStorage(root)


@pytest.fixture
def limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter()


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def _fake_enqueue(project_id: uuid.UUID, job_id: uuid.UUID) -> str:
        calls.append((project_id, job_id))
        return str(job_id)

    monkeypatch.setattr(pipeline, "enqueue_ingest", _fake_enqueue)
    monkeypatch.setattr(pipeline, "revoke", lambda _ids: None)
    return calls


@pytest.fixture
def app(storage: FakeStorage, limiter: InMemoryRateLimiter) -> Iterator[FastAPI]:
    application = create_app()
    application.dependency_overrides[get_storage] = lambda: storage
    application.dependency_overrides[get_rate_limiter] = lambda: limiter
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def db_app(app: FastAPI, sessions: async_sessionmaker[AsyncSession]) -> FastAPI:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _new_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def register(client: AsyncClient, email: str, password: str = "password123") -> str:
    resp = await client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


@pytest.fixture
async def alice(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    c = await _new_client(db_app)
    await register(c, "alice@example.com")
    yield c
    await c.aclose()


@pytest.fixture
async def bob(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    c = await _new_client(db_app)
    await register(c, "bob@example.com")
    yield c
    await c.aclose()


@pytest.fixture
async def anon(db_app: FastAPI) -> AsyncIterator[AsyncClient]:
    c = await _new_client(db_app)
    yield c
    await c.aclose()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
