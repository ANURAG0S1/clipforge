import json
import logging

from app.core.logging import JsonFormatter, log_context


def _format(record_extra: dict[str, object]) -> dict[str, object]:
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    for k, v in record_extra.items():
        setattr(record, k, v)
    parsed: dict[str, object] = json.loads(JsonFormatter().format(record))
    return parsed


def test_json_shape_and_correlation_ids() -> None:
    with log_context(project_id="p-1", job_id="j-1"):
        out = _format({"stage": "ingest"})
    assert out["msg"] == "hello world"
    assert out["level"] == "INFO"
    assert out["project_id"] == "p-1"
    assert out["job_id"] == "j-1"
    assert out["stage"] == "ingest"


def test_context_resets_after_block() -> None:
    with log_context(project_id="p-2"):
        pass
    out = _format({})
    assert "project_id" not in out


def test_sensitive_extras_redacted() -> None:
    out = _format({"password": "hunter2", "api_key": "sk-123", "jwt_token": "abc"})
    assert out["password"] == "[REDACTED]"
    assert out["api_key"] == "[REDACTED]"
    assert out["jwt_token"] == "[REDACTED]"
