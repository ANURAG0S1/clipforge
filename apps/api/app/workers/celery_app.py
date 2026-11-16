"""Celery application. Each pipeline stage has its own queue so workers can scale per stage."""

from typing import Final

from celery import Celery
from kombu import Queue

from app.core.config import get_settings
from app.core.logging import configure_logging

QUEUES: Final = ("ingest", "transcribe", "analyze", "render")


def create_celery() -> Celery:
    settings = get_settings()
    configure_logging(settings.log_level)
    broker = str(settings.redis_url)

    app = Celery(
        "clipforge",
        broker=broker,
        backend=broker,
        include=["app.workers.tasks.system", "app.workers.tasks.ingest"],
    )
    app.conf.update(
        task_queues=[Queue(name) for name in QUEUES],
        task_default_queue="ingest",
        task_routes={"system.*": {"queue": "ingest"}, "pipeline.ingest": {"queue": "ingest"}},
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        result_expires=24 * 3600,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
        timezone="UTC",
        enable_utc=True,
    )
    return app


celery_app = create_celery()
