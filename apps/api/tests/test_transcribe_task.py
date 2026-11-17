import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import Job, JobStatus, JobType, Project, ProjectStatus, SourceType, User
from app.db.models import Transcript as TranscriptRow
from app.schemas.transcript import TranscriptWord
from app.services.transcribe import ChunkResult, ProgressCallback, RawSegment, Transcriber
from app.workers.tasks import transcribe as task_mod
from app.workers.tasks.ingest import MAX_RETRIES
from tests.support.fakes import FakeStorage
from tests.support.media import make_test_video, requires_ffmpeg

pytestmark = requires_ffmpeg

FIXTURE = Path(__file__).parent / "fixtures" / "speech-sample.mp4"


class FakeTranscriber:
    """Emits one segment per call, 3s into the chunk (past any overlap), recording each call."""

    def __init__(self, words: tuple[str, ...] = ("hello", "world")) -> None:
        self.calls: list[tuple[Path, float]] = []
        self.words = words

    def transcribe(
        self, wav: Path, *, offset_s: float, on_progress: ProgressCallback
    ) -> ChunkResult:
        assert wav.is_file()
        self.calls.append((wav, offset_s))
        on_progress(0.5)
        segs = []
        if self.words:
            segs.append(
                RawSegment(
                    start=offset_s + 3,
                    end=offset_s + 3 + len(self.words) * 0.4,
                    text=" ".join(self.words),
                    words=tuple(
                        TranscriptWord(
                            w=f" {w}",
                            start=offset_s + 3 + i * 0.4,
                            end=offset_s + 3.3 + i * 0.4,
                            conf=0.95,
                        )
                        for i, w in enumerate(self.words)
                    ),
                )
            )
        on_progress(1.0)
        return ChunkResult(language="en", language_probability=0.98, segments=segs)


def _factory(t: Transcriber) -> "task_mod.TranscriberFactory":
    def make(_settings: Settings) -> Transcriber:
        return t

    return make


@pytest.fixture(autouse=True)
def _use_fake_storage(storage: FakeStorage, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_mod, "get_storage", lambda: storage)


async def _seed(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage, video: Path | None
) -> tuple[uuid.UUID, uuid.UUID]:
    async with sessions() as db:
        user = User(email=f"{uuid.uuid4().hex}@example.com", password_hash="x")
        db.add(user)
        await db.flush()
        project = Project(
            user_id=user.id,
            title="t",
            source_type=SourceType.UPLOAD,
            source_key="uploads/x/source.mp4",
            status=ProjectStatus.TRANSCRIBING,
            duration_s=7.5,
        )
        db.add(project)
        await db.flush()
        job = Job(project_id=project.id, type=JobType.TRANSCRIBE, status=JobStatus.QUEUED)
        db.add(job)
        await db.commit()
    if video is not None:
        storage.put_file(f"projects/{project.id}/proxy.mp4", video)
    return project.id, job.id


async def _state(
    sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID, job_id: uuid.UUID
) -> tuple[Project, Job, list[TranscriptRow]]:
    async with sessions() as db:
        project = await db.get(Project, project_id)
        job = await db.get(Job, job_id)
        rows = list(
            await db.scalars(select(TranscriptRow).where(TranscriptRow.project_id == project_id))
        )
    assert project is not None
    assert job is not None
    return project, job, rows


async def test_transcript_is_saved_and_project_ready(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    fake = FakeTranscriber(("welcome", "to", "clipforge"))
    project_id, job_id = await _seed(sessions, storage, FIXTURE)

    assert await task_mod.transcribe_project(project_id, job_id, 0, _factory(fake)) is None

    project, job, rows = await _state(sessions, project_id, job_id)
    assert project.status == ProjectStatus.READY
    assert job.status == JobStatus.SUCCEEDED
    assert job.progress == 100
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == 0.0
    assert len(rows) == 1
    assert rows[0].language == "en"
    assert [w["w"].strip() for w in rows[0].words] == ["welcome", "to", "clipforge"]
    assert rows[0].segments[0]["first_word"] == 0
    assert rows[0].segments[0]["word_count"] == 3


async def test_rerun_replaces_transcript(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    project_id, job_id = await _seed(sessions, storage, FIXTURE)
    await task_mod.transcribe_project(project_id, job_id, 0, _factory(FakeTranscriber(("a",))))
    async with sessions() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.RUNNING  # simulate redelivery after a worker crash
        await db.commit()
    await task_mod.transcribe_project(project_id, job_id, 0, _factory(FakeTranscriber(("b", "c"))))
    _, _, rows = await _state(sessions, project_id, job_id)
    assert len(rows) == 1
    assert [w["w"].strip() for w in rows[0].words] == ["b", "c"]


async def test_long_audio_is_chunked_with_offsets(
    sessions: async_sessionmaker[AsyncSession],
    storage: FakeStorage,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRANSCRIBE_MAX_SINGLE_PASS_S", "61")
    monkeypatch.setenv("TRANSCRIBE_CHUNK_S", "62")
    monkeypatch.setenv("TRANSCRIBE_CHUNK_OVERLAP_S", "5")
    from app.core.config import get_settings

    get_settings.cache_clear()
    video = make_test_video(tmp_path / "long.mp4", seconds=130, width=64, height=36)
    fake = FakeTranscriber(("x",))
    project_id, job_id = await _seed(sessions, storage, video)
    await task_mod.transcribe_project(project_id, job_id, 0, _factory(fake))
    assert [offset for _, offset in fake.calls] == [0.0, 57.0, 114.0]
    _, job, rows = await _state(sessions, project_id, job_id)
    assert job.status == JobStatus.SUCCEEDED
    assert [w["start"] for w in rows[0].words] == [3.0, 60.0, 117.0]


async def test_video_without_audio_fails_readably(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage, tmp_path: Path
) -> None:
    silent = make_test_video(tmp_path / "silent.mp4", seconds=1, audio=False)
    fake = FakeTranscriber()
    project_id, job_id = await _seed(sessions, storage, silent)
    await task_mod.transcribe_project(project_id, job_id, 0, _factory(fake))
    project, job, rows = await _state(sessions, project_id, job_id)
    assert project.status == ProjectStatus.FAILED
    assert project.error == "This video has no audio track, so there is nothing to transcribe."
    assert job.status == JobStatus.FAILED
    assert fake.calls == []
    assert rows == []


async def test_no_speech_fails_readably(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    project_id, job_id = await _seed(sessions, storage, FIXTURE)
    await task_mod.transcribe_project(project_id, job_id, 0, _factory(FakeTranscriber(())))
    project, _, _ = await _state(sessions, project_id, job_id)
    assert project.status == ProjectStatus.FAILED
    assert project.error == "No speech was detected in this video."


async def test_missing_proxy_is_retried_as_transient(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    project_id, job_id = await _seed(sessions, storage, None)
    reason = await task_mod.transcribe_project(project_id, job_id, 0, _factory(FakeTranscriber()))
    assert reason is not None
    _, job, _ = await _state(sessions, project_id, job_id)
    assert job.status == JobStatus.QUEUED


async def test_finished_job_is_skipped(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    project_id, job_id = await _seed(sessions, storage, FIXTURE)
    async with sessions() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        job.status = JobStatus.SUCCEEDED
        await db.commit()
    fake = FakeTranscriber()
    await task_mod.transcribe_project(project_id, job_id, 0, _factory(fake))
    assert fake.calls == []


@pytest.mark.skipif(
    os.environ.get("RUN_WHISPER_TESTS") != "1",
    reason="downloads a Whisper model; set RUN_WHISPER_TESTS=1 (CI does)",
)
def test_real_whisper_on_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.services import ffmpeg
    from app.services.transcribe import Chunk, WhisperTranscriber, merge_chunks

    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_CPU_MODEL", os.environ.get("WHISPER_TEST_MODEL", "tiny.en"))
    get_settings.cache_clear()
    wav = tmp_path / "a.wav"
    ffmpeg.extract_audio(FIXTURE, wav, timeout_s=60)
    transcriber = WhisperTranscriber(get_settings())
    seen: list[float] = []
    result = transcriber.transcribe(wav, offset_s=0.0, on_progress=seen.append)
    transcript = merge_chunks([result], [Chunk(0, 7.5)])

    text = " ".join(w.w.strip().lower() for w in transcript.words)
    assert len(transcript.words) >= 8, text
    assert any(k in text for k in ("welcome", "clip", "test", "word", "timestamp")), text
    assert transcript.language == "en"
    starts = [w.start for w in transcript.words]
    assert starts == sorted(starts)
    assert all(0 <= w.start <= w.end <= 8.0 for w in transcript.words)
    assert seen[-1] == 1.0


async def test_model_load_failure_is_retried_then_explained(
    sessions: async_sessionmaker[AsyncSession], storage: FakeStorage
) -> None:
    from app.services.transcribe import ModelUnavailableError

    def _broken(_settings: Settings) -> Transcriber:
        raise ModelUnavailableError("tiny.en", ConnectionError("403 Forbidden"))

    project_id, job_id = await _seed(sessions, storage, FIXTURE)
    assert await task_mod.transcribe_project(project_id, job_id, 0, _broken) is not None
    _, job, _ = await _state(sessions, project_id, job_id)
    assert job.status == JobStatus.QUEUED

    await task_mod.transcribe_project(project_id, job_id, MAX_RETRIES, _broken)
    project, job, _ = await _state(sessions, project_id, job_id)
    assert job.status == JobStatus.FAILED
    assert project.error is not None
    assert "speech model (tiny.en) could not be loaded" in project.error


def test_whisper_transcriber_wraps_load_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.services import transcribe as svc

    def _boom(*_: object) -> object:
        raise RuntimeError("proxy said no")

    monkeypatch.setattr(svc, "_load_model", _boom)
    with pytest.raises(svc.ModelUnavailableError, match="could not load whisper model"):
        svc.WhisperTranscriber(get_settings())
