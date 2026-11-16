"""Ingest: fetch the source, probe it, enforce limits, build a seekable H.264 proxy."""

import asyncio
import logging
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from celery import Task
from sqlalchemy.exc import DBAPIError, OperationalError

from app.core.config import Settings, get_settings
from app.core.logging import log_context
from app.db.models import Job, JobStatus, Project, ProjectStatus, SourceType
from app.services import ffmpeg
from app.services.downloader import (
    DownloadRejectedError,
    TransientDownloadError,
    download_url,
)
from app.services.storage import Storage, StorageError, get_storage
from app.workers.celery_app import celery_app
from app.workers.db import task_sessionmaker
from app.workers.progress import JobTracker

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    TransientDownloadError,
    StorageError,
    OperationalError,
    DBAPIError,
    ConnectionError,
    TimeoutError,
)


class IngestRejectedError(ValueError):
    """The media is valid but violates a configured limit."""


def proxy_key(project_id: uuid.UUID) -> str:
    return f"projects/{project_id}/proxy.mp4"


def source_key(project_id: uuid.UUID, suffix: str) -> str:
    return f"projects/{project_id}/source{suffix or '.mp4'}"


@dataclass(frozen=True, slots=True)
class IngestResult:
    probe: ffmpeg.ProbeResult
    source_key: str


def check_limits(probe: ffmpeg.ProbeResult, settings: Settings) -> None:
    if probe.duration_s > settings.max_duration_s:
        raise IngestRejectedError(
            f"Video is {probe.duration_s / 60:.0f} min long; the limit is "
            f"{settings.max_duration_min} min"
        )
    if probe.size_bytes > settings.max_upload_bytes:
        raise IngestRejectedError(f"Video is larger than the {settings.max_upload_gb:g} GB limit")


def human_error(exc: BaseException) -> str:
    """User-facing message for a permanent failure. Never includes paths or credentials."""
    if isinstance(exc, IngestRejectedError | DownloadRejectedError | ffmpeg.MediaProbeError):
        return str(exc)
    if isinstance(exc, ffmpeg.FFmpegError):
        return "The video could not be processed. It may be corrupt or use an unsupported codec."
    if isinstance(exc, TRANSIENT_ERRORS):
        return "A temporary error kept this video from processing. Please try again."
    return "Unexpected error while processing this video."


async def _run_ingest(
    tracker: JobTracker, project: Project, storage: Storage, settings: Settings
) -> IngestResult:
    with tempfile.TemporaryDirectory(
        prefix=f"ingest-{project.id}-", dir=settings.temp_dir
    ) as tmp_name:
        tmp = Path(tmp_name)

        if project.source_type == SourceType.URL:
            if not project.source_url:
                raise IngestRejectedError("Project has no source URL")
            url = project.source_url
            media = await tracker.run_step(
                0,
                40,
                lambda cb: download_url(
                    url,
                    tmp,
                    max_bytes=settings.max_upload_bytes,
                    max_duration_s=settings.max_duration_s,
                    on_progress=cb,
                ),
            )
            local_source = media.path
            stored_source_key = source_key(project.id, local_source.suffix)
            await asyncio.to_thread(
                storage.upload_file, local_source, stored_source_key, "video/mp4"
            )
        else:
            if not project.source_key:
                raise IngestRejectedError("Project has no uploaded file")
            stored_source_key = project.source_key
            local_source = tmp / f"source{Path(stored_source_key).suffix or '.bin'}"
            await tracker.run_step(
                0, 20, lambda _cb: storage.download_file(stored_source_key, local_source)
            )
        await tracker.progress(42)

        probe = await asyncio.to_thread(ffmpeg.probe, local_source)
        check_limits(probe, settings)
        await tracker.progress(45)

        proxy_path = tmp / "proxy.mp4"
        await tracker.run_step(
            45,
            95,
            lambda cb: ffmpeg.make_proxy(
                local_source,
                proxy_path,
                duration_s=probe.duration_s,
                timeout_s=settings.ffmpeg_timeout_s,
                on_progress=cb,
            ),
        )
        await asyncio.to_thread(storage.upload_file, proxy_path, proxy_key(project.id), "video/mp4")
        return IngestResult(probe=probe, source_key=stored_source_key)


async def ingest_project(project_id: uuid.UUID, job_id: uuid.UUID, attempt: int) -> str | None:
    """Run ingest once. Returns an error message to retry with, or None when finished."""
    settings = get_settings()
    async with task_sessionmaker() as sessions:
        async with sessions() as db:
            project = await db.get(Project, project_id)
            job = await db.get(Job, job_id)
        if project is None or job is None:
            logger.info("project or job no longer exists; skipping ingest")
            return None
        if job.status in (JobStatus.SUCCEEDED, JobStatus.FAILED):
            logger.info("ingest job already finished; skipping", extra={"status": job.status})
            return None

        tracker = JobTracker(sessions, project_id, job_id)
        await tracker.start(ProjectStatus.INGESTING)
        try:
            result = await _run_ingest(tracker, project, get_storage(), settings)
        except TRANSIENT_ERRORS as exc:
            if attempt < MAX_RETRIES:
                logger.warning("transient ingest error; will retry", exc_info=exc)
                await tracker.requeue(human_error(exc))
                return human_error(exc)
            logger.exception("ingest failed after retries")
            await tracker.fail(human_error(exc))
            return None
        except Exception as exc:
            logger.exception("ingest failed")
            await tracker.fail(human_error(exc))
            return None

        probe = result.probe
        await tracker.succeed(
            ProjectStatus.TRANSCRIBING,
            source_key=result.source_key,
            duration_s=probe.duration_s,
            width=probe.width,
            height=probe.height,
            fps=probe.fps,
        )
        logger.info(
            "ingest complete",
            extra={"duration_s": probe.duration_s, "width": probe.width, "height": probe.height},
        )
        return None


@celery_app.task(name="pipeline.ingest", bind=True, acks_late=True, max_retries=MAX_RETRIES)
def ingest(self: "Task[Any, None]", project_id: str, job_id: str) -> None:
    with log_context(project_id=project_id, job_id=job_id):
        retry_reason = asyncio.run(
            ingest_project(uuid.UUID(project_id), uuid.UUID(job_id), self.request.retries)
        )
        if retry_reason is not None:
            countdown = min(300, 15 * 2**self.request.retries)
            raise self.retry(countdown=countdown, exc=RuntimeError(retry_reason))
