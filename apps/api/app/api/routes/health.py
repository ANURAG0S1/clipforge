from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core.config import Settings, get_settings
from app.schemas.health import HealthReport
from app.services.health import HealthCheck, default_checks, run_health_checks

router = APIRouter(tags=["health"])


def get_health_checks() -> dict[str, HealthCheck]:
    return default_checks()


@router.get(
    "/healthz",
    response_model=HealthReport,
    responses={503: {"model": HealthReport, "description": "One or more dependencies are down"}},
)
async def healthz(
    response: Response,
    checks: Annotated[dict[str, HealthCheck], Depends(get_health_checks)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthReport:
    report = await run_health_checks(checks, settings.health_check_timeout_s)
    if report.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
