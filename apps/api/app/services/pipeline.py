"""Enqueueing pipeline stages. Callers only know task names, never worker code."""

import uuid
from typing import Final

from app.db.models import JobType
from app.workers.celery_app import celery_app

TASK_NAMES: Final[dict[JobType, str]] = {
    JobType.INGEST: "pipeline.ingest",
    JobType.TRANSCRIBE: "pipeline.transcribe",
    JobType.ANALYZE: "pipeline.analyze",
    JobType.RENDER: "pipeline.render",
}


def enqueue(job_type: JobType, project_id: uuid.UUID, job_id: uuid.UUID) -> str:
    """Send a stage task to its own queue. The Celery task id is the job id, so redelivery
    and retries stay correlated with the ``jobs`` row."""
    result = celery_app.send_task(
        TASK_NAMES[job_type],
        kwargs={"project_id": str(project_id), "job_id": str(job_id)},
        queue=job_type.value,
        task_id=str(job_id),
    )
    return str(result.id)


def enqueue_ingest(project_id: uuid.UUID, job_id: uuid.UUID) -> str:
    return enqueue(JobType.INGEST, project_id, job_id)


def revoke(task_ids: list[str]) -> None:
    if task_ids:
        celery_app.control.revoke(task_ids, terminate=False)
