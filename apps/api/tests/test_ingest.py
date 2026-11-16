import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Job, JobStatus, JobType, Project, ProjectStatus, SourceType, User
from app.services.downloader import DownloadedMedia, DownloadRejectedError
from app.services.storage import StorageError
from app.workers.tasks import ingest as ingest_mod
from tests.support.fakes import FakeStorage
from tests.support.media import make_test_video, requires_ffmpeg

pytestmark = requires_ffmpeg


@pytest.fixture(autouse=True)
def _use_fake_storage(storage: FakeStorage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_mod, "get_storage", lambda: storage)


async def _seed(
    sessions: async_sessionmaker[AsyncSession],
    *,
    source_type: SourceType,
    source_key: str | None = None,
    source_url: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessions() as db:
        user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash="x")
        db.add(user)
        await db.flush()
        project = Project(
            user_id=user.id,
            title="t",
            source_type=source_type,
            source_key=source_key,
            source_url=source_url,
            status=ProjectStatus.PENDING,
        )
        db.add(project)
        await db.flush()
        job = Job(project_id=project.id, type=JobType.INGEST, status=JobStatus.QUEUED, progress=0)
        db.add(job)
        await db.commit()
        return project.id, job.id


async def _load(
    sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Project, Job]:
    async with sessions() as db:
        project = await db.get(Project, project_id)
        job = await db.get(Job, job_id)
        assert project is not None
        assert job is not None
        return project, job


async def test_upload_ingest_reaches_transcribing_with_metadata(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage, tmp_path: Path
) -> None:
    src = make_test_video(tmp_path / "v.mp4", seconds=3, width=640, height=360)
    key = f"uploads/{uuid.uuid4()}/{uuid.uuid4()}/source.mp4"
    storage.put_file(key, src)
    project_id, job_id = await _seed(sessions, source_type=SourceType.UPLOAD, source_key=key)

    assert await ingest_mod.ingest_project(project_id, job_id, attempt=0) is None

    project, job = await _load(sessions, project_id, job_id)
    assert project.status == ProjectStatus.TRANSCRIBING
    assert project.error is None
    assert (project.width, project.height, project.fps) == (640, 360, 25.0)
    assert project.duration_s is not None
    assert 2.9 <= project.duration_s <= 3.2
    assert project.source_key == key
    assert job.status == JobStatus.SUCCEEDED
    assert job.progress == 100
    assert job.started_at is not None
    assert job.finished_at is not None
    assert f"projects/{project_id}/proxy.mp4" in storage.all_keys()


async def test_url_ingest_stores_source_and_proxy(
    sessions: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_download(url: str, dest: Path, **_: object) -> DownloadedMedia:
        return DownloadedMedia(path=make_test_video(dest / "source.mp4", seconds=2), title="x")

    monkeypatch.setattr(ingest_mod, "download_url", _fake_download)
    project_id, job_id = await _seed(
        sessions, source_type=SourceType.URL, source_url="https://videos.example.com/a"
    )
    await ingest_mod.ingest_project(project_id, job_id, attempt=0)
    project, _ = await _load(sessions, project_id, job_id)
    assert project.status == ProjectStatus.TRANSCRIBING
    assert project.source_key == f"projects/{project_id}/source.mp4"
    assert set(storage.all_keys()) >= {
        f"projects/{project_id}/source.mp4",
        f"projects/{project_id}/proxy.mp4",
    }


def test_check_limits() -> None:
    from app.core.config import get_settings
    from app.services.ffmpeg import ProbeResult

    settings = get_settings()
    ok = ProbeResult(
        duration_s=60, width=1, height=1, fps=1, video_codec="h264", has_audio=True, size_bytes=1
    )
    ingest_mod.check_limits(ok, settings)
    too_long = ProbeResult(
        duration_s=settings.max_duration_s + 1,
        width=1,
        height=1,
        fps=1,
        video_codec="h264",
        has_audio=True,
        size_bytes=1,
    )
    with pytest.raises(ingest_mod.IngestRejectedError, match="limit is 180 min"):
        ingest_mod.check_limits(too_long, settings)
    too_big = ProbeResult(
        duration_s=1,
        width=1,
        height=1,
        fps=1,
        video_codec="h264",
        has_audio=True,
        size_bytes=settings.max_upload_bytes + 1,
    )
    with pytest.raises(ingest_mod.IngestRejectedError, match="GB limit"):
        ingest_mod.check_limits(too_big, settings)


async def test_limit_violation_fails_with_readable_error(
    sessions: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _reject(probe: object, settings: object) -> None:
        raise ingest_mod.IngestRejectedError("Video is 200 min long; the limit is 180 min")

    monkeypatch.setattr(ingest_mod, "check_limits", _reject)
    key = "uploads/u/k/source.mp4"
    storage.put_file(key, make_test_video(tmp_path / "v.mp4", seconds=1))
    project_id, job_id = await _seed(sessions, source_type=SourceType.UPLOAD, source_key=key)
    await ingest_mod.ingest_project(project_id, job_id, attempt=0)
    project, job = await _load(sessions, project_id, job_id)
    assert project.status == ProjectStatus.FAILED
    assert project.error == "Video is 200 min long; the limit is 180 min"
    assert job.status == JobStatus.FAILED


async def test_non_video_upload_fails_cleanly(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    key = "uploads/u/k/source.mp4"
    storage.put_bytes(key, b"definitely not a video")
    project_id, job_id = await _seed(sessions, source_type=SourceType.UPLOAD, source_key=key)
    await ingest_mod.ingest_project(project_id, job_id, attempt=0)
    project, _ = await _load(sessions, project_id, job_id)
    assert project.status == ProjectStatus.FAILED
    assert project.error is not None
    assert "not a readable media file" in project.error
    assert "/" not in project.error.split(":")[0]


async def test_rejected_url_download_fails_without_retry(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _reject(url: str, dest: Path, **_: object) -> DownloadedMedia:
        raise DownloadRejectedError("Live streams are not supported")

    monkeypatch.setattr(ingest_mod, "download_url", _reject)
    project_id, job_id = await _seed(
        sessions, source_type=SourceType.URL, source_url="https://videos.example.com/live"
    )
    assert await ingest_mod.ingest_project(project_id, job_id, attempt=0) is None
    project, _ = await _load(sessions, project_id, job_id)
    assert project.error == "Live streams are not supported"


async def test_transient_error_requests_retry_then_fails(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    key = "uploads/u/k/source.mp4"
    storage.put_bytes(key, b"x")
    object.__setattr__(storage, "fail_with", StorageError("minio down"))
    project_id, job_id = await _seed(sessions, source_type=SourceType.UPLOAD, source_key=key)

    reason = await ingest_mod.ingest_project(project_id, job_id, attempt=0)
    assert reason is not None
    project, job = await _load(sessions, project_id, job_id)
    assert job.status == JobStatus.QUEUED
    assert project.status == ProjectStatus.INGESTING

    final = await ingest_mod.ingest_project(project_id, job_id, attempt=ingest_mod.MAX_RETRIES)
    assert final is None
    project, job = await _load(sessions, project_id, job_id)
    assert project.status == ProjectStatus.FAILED
    assert job.status == JobStatus.FAILED
    assert "temporary error" in (project.error or "")


async def test_finished_or_deleted_jobs_are_skipped(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage, tmp_path: Path
) -> None:
    assert await ingest_mod.ingest_project(uuid.uuid4(), uuid.uuid4(), attempt=0) is None

    key = "uploads/u/k/source.mp4"
    storage.put_file(key, make_test_video(tmp_path / "v.mp4", seconds=1))
    project_id, job_id = await _seed(sessions, source_type=SourceType.UPLOAD, source_key=key)
    await ingest_mod.ingest_project(project_id, job_id, attempt=0)
    first, _ = await _load(sessions, project_id, job_id)
    # A redelivered message (e.g. worker crash after commit) must not redo the work.
    object.__setattr__(storage, "fail_with", StorageError("should not be touched"))
    await ingest_mod.ingest_project(project_id, job_id, attempt=0)
    again, job = await _load(sessions, project_id, job_id)
    assert again.status == ProjectStatus.TRANSCRIBING
    assert again.updated_at == first.updated_at
    assert job.status == JobStatus.SUCCEEDED


@pytest.mark.parametrize("fail", [False, True])
async def test_temp_dirs_are_cleaned_up(
    sessions: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("TEMP_DIR", str(work))
    from app.core.config import get_settings

    get_settings.cache_clear()
    key = "uploads/u/k/source.mp4"
    if fail:
        storage.put_bytes(key, b"not a video")
    else:
        storage.put_file(key, make_test_video(tmp_path / "v.mp4", seconds=1))
    project_id, job_id = await _seed(sessions, source_type=SourceType.UPLOAD, source_key=key)
    await ingest_mod.ingest_project(project_id, job_id, attempt=0)
    project, _ = await _load(sessions, project_id, job_id)
    assert project.status == (ProjectStatus.FAILED if fail else ProjectStatus.TRANSCRIBING)
    assert list(work.iterdir()) == []
