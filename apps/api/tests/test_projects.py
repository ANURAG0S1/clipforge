import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes import projects as projects_routes
from app.db.models import Job, JobStatus, Project, ProjectStatus
from app.services import pipeline
from tests.support.fakes import FakeStorage, InMemoryRateLimiter


async def _upload(client: AsyncClient, storage: FakeStorage, size: int = 1024) -> str:
    resp = await client.post(
        "/uploads/presign",
        json={"filename": "talk.mp4", "content_type": "video/mp4", "size_bytes": size},
    )
    key = str(resp.json()["key"])
    storage.put_bytes(key, b"\0" * size)
    return key


async def _create(client: AsyncClient, key: str, title: str = "Talk") -> dict[str, object]:
    resp = await client.post(
        "/projects", json={"title": title, "source": {"type": "upload", "key": key}}
    )
    assert resp.status_code == 201, resp.text
    body: dict[str, object] = resp.json()
    return body


async def test_create_from_upload_enqueues_ingest(
    alice: AsyncClient,
    storage: FakeStorage,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    key = await _upload(alice, storage)
    body = await _create(alice, key)
    assert body["status"] == "pending"
    assert body["source_type"] == "upload"
    assert body["progress"] == 0
    assert len(enqueued) == 1
    project_id, job_id = enqueued[0]
    assert str(project_id) == body["id"]
    async with sessions() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.QUEUED
        assert job.celery_task_id == str(job_id)


async def test_cannot_use_another_users_upload(
    alice: AsyncClient,
    bob: AsyncClient,
    storage: FakeStorage,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    alice_key = await _upload(alice, storage)
    resp = await bob.post(
        "/projects", json={"title": "Stolen", "source": {"type": "upload", "key": alice_key}}
    )
    assert resp.status_code == 404
    assert enqueued == []


@pytest.mark.parametrize("suffix", ["../../other/source.mp4", "x//source.mp4"])
async def test_traversal_keys_rejected(
    alice: AsyncClient, storage: FakeStorage, suffix: str
) -> None:
    me = (await alice.get("/auth/me")).json()
    key = f"uploads/{me['id']}/{suffix}"
    resp = await alice.post(
        "/projects", json={"title": "x", "source": {"type": "upload", "key": key}}
    )
    assert resp.status_code == 404


async def test_missing_or_oversize_upload(
    alice: AsyncClient, storage: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = (await alice.get("/auth/me")).json()
    never_uploaded = f"uploads/{me['id']}/{uuid.uuid4()}/source.mp4"
    resp = await alice.post(
        "/projects", json={"title": "x", "source": {"type": "upload", "key": never_uploaded}}
    )
    assert resp.status_code == 404

    key = await _upload(alice, storage, size=2048)
    monkeypatch.setenv("MAX_UPLOAD_GB", str(1024 / 1024**3))
    from app.core.config import get_settings

    get_settings.cache_clear()
    resp = await alice.post(
        "/projects", json={"title": "x", "source": {"type": "upload", "key": key}}
    )
    assert resp.status_code == 413


async def test_create_from_url_validates_ssrf(
    alice: AsyncClient,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for url in ["http://127.0.0.1/x.mp4", "http://169.254.169.254/", "http://localhost/v"]:
        resp = await alice.post(
            "/projects", json={"title": "x", "source": {"type": "url", "url": url}}
        )
        assert resp.status_code == 422, url
    bad_scheme = await alice.post(
        "/projects", json={"title": "x", "source": {"type": "url", "url": "ftp://example.com/v"}}
    )
    assert bad_scheme.status_code == 422
    assert enqueued == []

    monkeypatch.setattr(projects_routes, "validate_public_url", lambda url: url.strip())
    ok = await alice.post(
        "/projects",
        json={"title": "Remote", "source": {"type": "url", "url": "https://videos.example.com/a"}},
    )
    assert ok.status_code == 201
    assert ok.json()["source_url"] == "https://videos.example.com/a"
    assert len(enqueued) == 1


async def test_ownership_is_enforced_with_404(
    alice: AsyncClient,
    bob: AsyncClient,
    storage: FakeStorage,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
) -> None:
    project = await _create(alice, await _upload(alice, storage))
    pid = project["id"]
    assert (await bob.get(f"/projects/{pid}")).status_code == 404
    assert (await bob.get(f"/projects/{pid}/jobs")).status_code == 404
    assert (await bob.delete(f"/projects/{pid}")).status_code == 404
    assert (await bob.get("/projects")).json() == []
    assert (await alice.get(f"/projects/{pid}")).status_code == 200
    assert [p["id"] for p in (await alice.get("/projects")).json()] == [pid]
    assert (await alice.get(f"/projects/{uuid.uuid4()}")).status_code == 404


async def test_unauthenticated_requests_rejected(anon: AsyncClient) -> None:
    assert (await anon.get("/projects")).status_code == 401
    assert (await anon.get(f"/projects/{uuid.uuid4()}")).status_code == 401
    resp = await anon.post(
        "/projects", json={"title": "x", "source": {"type": "url", "url": "https://a.com"}}
    )
    assert resp.status_code == 401


async def test_delete_removes_objects_and_rows(
    alice: AsyncClient,
    storage: FakeStorage,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    key = await _upload(alice, storage)
    project = await _create(alice, key)
    pid = str(project["id"])
    storage.put_bytes(f"projects/{pid}/proxy.mp4", b"proxy")
    storage.put_bytes(f"projects/{pid}/clips/a.mp4", b"clip")
    other = await _create(alice, await _upload(alice, storage), title="Other")
    storage.put_bytes(f"projects/{other['id']}/proxy.mp4", b"keep")

    resp = await alice.delete(f"/projects/{pid}")
    assert resp.status_code == 204
    remaining = storage.all_keys()
    assert not any(k.startswith(f"projects/{pid}/") for k in remaining)
    assert key not in remaining
    assert f"projects/{other['id']}/proxy.mp4" in remaining
    async with sessions() as db:
        assert await db.get(Project, uuid.UUID(pid)) is None
        jobs = (await db.scalars(select(Job).where(Job.project_id == uuid.UUID(pid)))).all()
        assert jobs == []
    assert (await alice.get(f"/projects/{pid}")).status_code == 404


async def test_project_creation_rate_limited(
    alice: AsyncClient,
    storage: FakeStorage,
    limiter: InMemoryRateLimiter,
    enqueued: list[tuple[uuid.UUID, uuid.UUID]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROJECT_CREATE_LIMIT", "2")
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = await _upload(alice, storage)
    for _ in range(2):
        await _create(alice, key)
    resp = await alice.post(
        "/projects", json={"title": "x", "source": {"type": "upload", "key": key}}
    )
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) > 0
    assert len(enqueued) == 2


async def test_enqueue_failure_marks_project_failed(
    alice: AsyncClient,
    storage: FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    def _broken(project_id: uuid.UUID, job_id: uuid.UUID) -> str:
        raise ConnectionError("redis down")

    monkeypatch.setattr(pipeline, "enqueue_ingest", _broken)
    key = await _upload(alice, storage)
    resp = await alice.post(
        "/projects", json={"title": "x", "source": {"type": "upload", "key": key}}
    )
    assert resp.status_code == 503
    projects = (await alice.get("/projects")).json()
    assert projects[0]["status"] == ProjectStatus.FAILED.value
    assert projects[0]["error"]
