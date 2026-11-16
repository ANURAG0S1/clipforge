"""Enqueueing pipeline stages. The API only knows task names, never worker code."""

import uuid
from typing import Final

from app.workers.celery_app import celery_app

INGEST_TASK: Final = "pipeline.ingest"


def enqueue_ingest(project_id: uuid.UUID, job_id: uuid.UUID) -> str:
    """Send the ingest task; the Celery task id is the job id so retries stay correlated."""
    result = celery_app.send_task(
        INGEST_TASK,
        kwargs={"project_id": str(project_id), "job_id": str(job_id)},
        queue="ingest",
        task_id=str(job_id),
    )
    return str(result.id)


def revoke(task_ids: list[str]) -> None:
    if task_ids:
        celery_app.control.revoke(task_ids, terminate=False)
