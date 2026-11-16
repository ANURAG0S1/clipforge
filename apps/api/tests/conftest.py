"""Test configuration. A complete, valid environment is installed before any app import."""

import os
from collections.abc import AsyncIterator, Iterator

import pytest
from httpx import ASGITransport, AsyncClient

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

from fastapi import FastAPI  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402


@pytest.fixture
def app() -> Iterator[FastAPI]:
    application = create_app()
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
