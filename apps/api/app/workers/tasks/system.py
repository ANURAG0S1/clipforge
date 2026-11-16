"""Operational tasks used to verify worker liveness end-to-end through the broker."""

from datetime import UTC, datetime

from app.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    return datetime.now(tz=UTC).isoformat()
