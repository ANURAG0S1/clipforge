from typing import Literal

from pydantic import BaseModel


class CheckResult(BaseModel):
    ok: bool
    latency_ms: float
    error: str | None


class HealthReport(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, CheckResult]
