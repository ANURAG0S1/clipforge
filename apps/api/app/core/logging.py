"""Structured JSON logging with project/job correlation via contextvars."""

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Final

project_id_var: ContextVar[str | None] = ContextVar("project_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

_RESERVED: Final = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys() | {"message", "asctime"}
)
_REDACTED_KEYS: Final = frozenset(
    {"password", "password_hash", "token", "secret", "authorization", "api_key", "cookie"}
)


def _redact(key: str, value: object) -> object:
    lowered = key.lower()
    if any(marker in lowered for marker in _REDACTED_KEYS):
        return "[REDACTED]"
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        project_id = project_id_var.get()
        job_id = job_id_var.get()
        if project_id is not None:
            payload["project_id"] = project_id
        if job_id is not None:
            payload["job_id"] = job_id
        for key, value in vars(record).items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _redact(key, value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("uvicorn.access", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(logging.WARNING, root.level))
    # Let uvicorn's own loggers propagate to our JSON handler.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


@contextmanager
def log_context(*, project_id: str | None = None, job_id: str | None = None) -> Iterator[None]:
    p_token = project_id_var.set(project_id) if project_id is not None else None
    j_token = job_id_var.set(job_id) if job_id is not None else None
    try:
        yield
    finally:
        if j_token is not None:
            job_id_var.reset(j_token)
        if p_token is not None:
            project_id_var.reset(p_token)
