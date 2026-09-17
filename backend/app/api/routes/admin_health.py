"""Staff-facing platform health (spec 057).

One endpoint, because the page is one screen and a partial render of a health
page is a misleading health page.

The Kubernetes probes in ``health.py`` are deliberately untouched: liveness
checks nothing so a database blip cannot restart every pod mid-event, and
readiness stays cheap and container-local. This page must not become a reason to
make either expensive.
"""

from fastapi import APIRouter, Request

from app.api.deps import AppSettings, DbSession, RedisClient, Staff
from app.schemas.admin_health import HealthReportResponse
from app.services import platform_health

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
async def platform_report(
    request: Request,
    db: DbSession,
    redis: RedisClient,
    settings: AppSettings,
    current: Staff,
) -> HealthReportResponse:
    orchestrator = getattr(request.app.state, "orchestrator", None)
    return HealthReportResponse(
        **await platform_health.report(db, redis, settings, orchestrator)
    )
