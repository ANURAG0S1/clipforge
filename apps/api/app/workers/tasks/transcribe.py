"""Transcribe: extract 16 kHz mono audio from the proxy, run Whisper (chunked when long)."""

import asyncio
import logging
import tempfile
import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from celery import Task
from sqlalchemy import delete

from app.core.config import Settings, get_settings
from app.core.logging import log_context
from app.db.models import Job, JobStatus, Project, ProjectStatus, Transcript
from app.services import ffmpeg
from app.services.keys import proxy_key
from app.services.storage import Storage, get_storage
from app.services.transcribe import (
    AudioFormatError,
    ChunkResult,
    ModelUnavailableError,
    NoSpeechError,
    ProgressCallback,
    Transcriber,
    WhisperTranscriber,
    merge_chunks,
    plan_chunks,
)
from app.services.transcribe import Transcript as TranscriptData
from app.workers.celery_app import celery_app
from app.workers.db import task_sessionmaker
from app.workers.progress import JobTracker
from app.workers.tasks.ingest import MAX_RETRIES, TRANSIENT_ERRORS

logger = logging.getLogger(__name__)

TranscriberFactory = Callable[[Settings], Transcriber]


class NoAudioError(ValueError):
    """The video has no audio track to transcribe."""


def human_error(exc: BaseException) -> str:
    if isinstance(exc, NoAudioError | NoSpeechError):
        return str(exc)
    if isinstance(exc, ModelUnavailableError):
        return (
            f"The speech model ({exc.model}) could not be loaded. Check that the transcription "
            "worker can reach huggingface.co or has the model in WHISPER_MODEL_DIR."
        )
    if isinstance(exc, ffmpeg.FFmpegError | ffmpeg.MediaProbeError | AudioFormatError):
        return "The audio could not be extracted from this video."
    if isinstance(exc, TRANSIENT_ERRORS):
        return "A temporary error interrupted transcription. Please try again."
    if isinstance(exc, MemoryError):
        return "Transcription ran out of memory. Try a smaller WHISPER_MODEL."
    return "Unexpected error while transcribing this video."


def _transcribe_chunk(
    transcriber: Transcriber, wav: Path, offset_s: float, on_progress: ProgressCallback
) -> ChunkResult:
    return transcriber.transcribe(wav, offset_s=offset_s, on_progress=on_progress)


def _default_factory(settings: Settings) -> Transcriber:
    return WhisperTranscriber(settings)


async def _run_transcription(
    tracker: JobTracker,
    project_id: uuid.UUID,
    storage: Storage,
    settings: Settings,
    factory: TranscriberFactory,
) -> TranscriptData:
    with tempfile.TemporaryDirectory(
        prefix=f"transcribe-{project_id}-", dir=settings.temp_dir
    ) as tmp_name:
        tmp = Path(tmp_name)
        proxy = tmp / "proxy.mp4"
        await asyncio.to_thread(storage.download_file, proxy_key(project_id), proxy)
        probe = await asyncio.to_thread(ffmpeg.probe, proxy)
        if not probe.has_audio:
            raise NoAudioError("This video has no audio track, so there is nothing to transcribe.")
        await tracker.progress(3)

        transcriber = await asyncio.to_thread(factory, settings)
        await tracker.progress(8)

        chunks = plan_chunks(
            probe.duration_s,
            max_single_pass_s=settings.transcribe_max_single_pass_s,
            chunk_s=settings.transcribe_chunk_s,
            overlap_s=settings.transcribe_chunk_overlap_s,
        )
        results: list[ChunkResult] = []
        span = 92 / len(chunks)
        for i, chunk in enumerate(chunks):
            wav = tmp / f"chunk-{i:03d}.wav"
            await asyncio.to_thread(
                ffmpeg.extract_audio,
                proxy,
                wav,
                start_s=chunk.start_s,
                duration_s=chunk.duration_s if len(chunks) > 1 else None,
                timeout_s=settings.ffmpeg_timeout_s,
            )
            lo = 8 + int(i * span)
            hi = 8 + int((i + 1) * span)
            results.append(
                await tracker.run_step(
                    lo, hi, partial(_transcribe_chunk, transcriber, wav, chunk.start_s)
                )
            )
            wav.unlink(missing_ok=True)

        transcript = merge_chunks(results, chunks)
        if not transcript.words:
            raise NoSpeechError("No speech was detected in this video.")
        return transcript


async def _save_transcript(tracker: JobTracker, data: TranscriptData) -> None:
    """Replace any previous transcript (retries and re-runs stay idempotent)."""
    async with tracker.sessions() as db:
        await db.execute(delete(Transcript).where(Transcript.project_id == tracker.project_id))
        db.add(
            Transcript(
                project_id=tracker.project_id,
                language=data.language,
                words=[w.model_dump() for w in data.words],
                segments=[s.model_dump() for s in data.segments],
            )
        )
        await db.commit()


async def transcribe_project(
    project_id: uuid.UUID,
    job_id: uuid.UUID,
    attempt: int,
    factory: TranscriberFactory = _default_factory,
) -> str | None:
    """Run transcription once. Returns an error message to retry with, or None when finished."""
    settings = get_settings()
    async with task_sessionmaker() as sessions:
        async with sessions() as db:
            project = await db.get(Project, project_id)
            job = await db.get(Job, job_id)
        if project is None or job is None:
            logger.info("project or job no longer exists; skipping transcription")
            return None
        if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            logger.info("transcribe job already finished; skipping", extra={"status": job.status})
            return None

        tracker = JobTracker(sessions, project_id, job_id)
        await tracker.start(ProjectStatus.TRANSCRIBING)
        try:
            data = await _run_transcription(tracker, project_id, get_storage(), settings, factory)
            await _save_transcript(tracker, data)
        except TRANSIENT_ERRORS as exc:
            if attempt < MAX_RETRIES:
                logger.warning("transient transcription error; will retry", exc_info=exc)
                await tracker.requeue(human_error(exc))
                return human_error(exc)
            logger.exception("transcription failed after retries")
            await tracker.fail(human_error(exc))
            return None
        except Exception as exc:
            logger.exception("transcription failed")
            await tracker.fail(human_error(exc))
            return None

        # Highlight detection (Phase 4) will chain from here; until then the project is ready.
        await tracker.succeed(ProjectStatus.READY)
        logger.info(
            "transcription complete",
            extra={"language": data.language, "words": len(data.words)},
        )
        return None


@celery_app.task(name="pipeline.transcribe", bind=True, acks_late=True, max_retries=MAX_RETRIES)
def transcribe(self: "Task[Any, None]", project_id: str, job_id: str) -> None:
    with log_context(project_id=project_id, job_id=job_id):
        retry_reason = asyncio.run(
            transcribe_project(uuid.UUID(project_id), uuid.UUID(job_id), self.request.retries)
        )
        if retry_reason is not None:
            countdown = min(300, 15 * 2**self.request.retries)
            raise self.retry(countdown=countdown, exc=RuntimeError(retry_reason))
