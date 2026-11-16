from app.workers.celery_app import QUEUES, celery_app
from app.workers.tasks.system import ping


def test_queues_and_reliability_settings() -> None:
    names = {q.name for q in celery_app.conf.task_queues}
    assert names == set(QUEUES) == {"ingest", "transcribe", "analyze", "render"}
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


def test_ping_task_runs_locally() -> None:
    result = ping.apply().get(timeout=5)
    assert isinstance(result, str)
    assert "T" in result
