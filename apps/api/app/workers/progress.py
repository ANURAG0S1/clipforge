"""Job/project state transitions shared by all pipeline tasks."""

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Job, JobStatus, JobType, Project, ProjectStatus
from app.services import pipeline

logger = logging.getLogger(__name__)

T = TypeVar("T")
ProgressCallback = Callable[[float], None]


class JobTracker:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID, job_id: uuid.UUID
    ) -> None:
        self.sessions = sessions
        self.project_id = project_id
        self.job_id = job_id
        self._last_progress = -1

    async def start(self, project_status: ProjectStatus) -> None:
        async with self.sessions() as db:
            await db.execute(
                update(Job)
                .where(Job.id == self.job_id)
                .values(
                    status=JobStatus.RUNNING,
                    progress=0,
                    error=None,
                    started_at=datetime.now(tz=UTC),
                    finished_at=None,
                )
            )
            await db.execute(
                update(Project)
                .where(Project.id == self.project_id)
                .values(status=project_status, error=None)
            )
            await db.commit()
        self._last_progress = 0

    async def progress(self, pct: int) -> None:
        pct = max(0, min(100, pct))
        if pct == self._last_progress:
            return
        async with self.sessions() as db:
            await db.execute(update(Job).where(Job.id == self.job_id).values(progress=pct))
            await db.commit()
        self._last_progress = pct

    async def succeed(
        self,
        next_project_status: ProjectStatus,
        *,
        next_job: JobType | None = None,
        **project_fields: object,
    ) -> uuid.UUID | None:
        """Finish this job and, atomically, create the next stage's job (if any).

        Returns the next job's id; call :meth:`dispatch` with it after this returns.
        """
        next_job_id: uuid.UUID | None = None
        async with self.sessions() as db:
            if next_job is not None:
                job = Job(
                    project_id=self.project_id, type=next_job, status=JobStatus.QUEUED, progress=0
                )
                db.add(job)
                await db.flush()
                job.celery_task_id = str(job.id)
                next_job_id = job.id
            await db.execute(
                update(Job)
                .where(Job.id == self.job_id)
                .values(status=JobStatus.SUCCEEDED, progress=100, finished_at=datetime.now(tz=UTC))
            )
            await db.execute(
                update(Project)
                .where(Project.id == self.project_id)
                .values(status=next_project_status, error=None, **project_fields)
            )
            await db.commit()
        return next_job_id

    async def dispatch(self, job_type: JobType, job_id: uuid.UUID) -> bool:
        """Send the next stage's task. On failure, mark that job and the project failed."""
        try:
            await asyncio.to_thread(pipeline.enqueue, job_type, self.project_id, job_id)
        except Exception:
            logger.exception("failed to enqueue next stage", extra={"stage": job_type.value})
            message = f"Could not start the {job_type.value} step. Please try again."
            async with self.sessions() as db:
                await db.execute(
                    update(Job)
                    .where(Job.id == job_id)
                    .values(status=JobStatus.FAILED, error=message)
                )
                await db.execute(
                    update(Project)
                    .where(Project.id == self.project_id)
                    .values(status=ProjectStatus.FAILED, error=message)
                )
                await db.commit()
            return False
        return True

    async def redispatch_queued(self, job_type: JobType) -> None:
        """Re-send a next-stage job left QUEUED, e.g. when a crash hit between commit and send.

        Stage tasks are idempotent, so a duplicate delivery is harmless.
        """
        async with self.sessions() as db:
            job_id = await db.scalar(
                select(Job.id).where(
                    Job.project_id == self.project_id,
                    Job.type == job_type,
                    Job.status == JobStatus.QUEUED,
                )
            )
        if job_id is not None:
            await self.dispatch(job_type, job_id)

    async def fail(self, message: str) -> None:
        async with self.sessions() as db:
            await db.execute(
                update(Job)
                .where(Job.id == self.job_id)
                .values(status=JobStatus.FAILED, error=message, finished_at=datetime.now(tz=UTC))
            )
            await db.execute(
                update(Project)
                .where(Project.id == self.project_id)
                .values(status=ProjectStatus.FAILED, error=message)
            )
            await db.commit()

    async def requeue(self, message: str) -> None:
        """Mark the job queued again ahead of a retry, keeping the reason visible."""
        async with self.sessions() as db:
            await db.execute(
                update(Job)
                .where(Job.id == self.job_id)
                .values(status=JobStatus.QUEUED, error=message)
            )
            await db.commit()

    async def run_step(
        self, lo: int, hi: int, fn: Callable[[ProgressCallback], T], poll_s: float = 1.0
    ) -> T:
        """Run blocking ``fn(on_progress)`` in a thread, persisting progress mapped to [lo, hi]."""
        latest = 0.0

        def _on_progress(fraction: float) -> None:
            nonlocal latest
            latest = max(0.0, min(1.0, fraction))

        task = asyncio.ensure_future(asyncio.to_thread(fn, _on_progress))
        while not task.done():
            await asyncio.wait({task}, timeout=poll_s)
            await self.progress(lo + int((hi - lo) * latest))
        result = task.result()
        await self.progress(hi)
        return result
