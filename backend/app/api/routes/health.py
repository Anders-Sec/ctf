"""Liveness, readiness and version endpoints."""

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.db import get_sessionmaker
from app.logging import get_logger
from app.redis import get_redis
from app.schemas.health import HealthResponse, ReadinessResponse, VersionResponse

logger = get_logger(__name__)

router = APIRouter(tags=["health"])

#: The same probes mounted at the root of the pod, outside the /api prefix.
#: Kubernetes probes hit the container directly rather than through the
#: ingress, and the platform's standard probe config expects /health there.
#: Hidden from the schema so the docs show one canonical path, not two.
root_router = APIRouter(tags=["health"], include_in_schema=False)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness. Deliberately checks nothing.

    If this touched Postgres, a brief database blip would restart every pod in the
    middle of the event. Dependency health is readiness' job.
    """
    return HealthResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def readiness(response: Response) -> ReadinessResponse:
    """Readiness: can this pod actually serve traffic right now?"""
    postgres = await _check_postgres()
    redis = await _check_redis()

    ready = postgres == "ok" and redis == "ok"
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ok" if ready else "degraded",
        postgres=postgres,
        redis=redis,
    )


@router.get("/version", response_model=VersionResponse)
async def version(request: Request) -> VersionResponse:
    # create_app always stashes Settings here, so tests can build an app with
    # overridden settings and this endpoint reports them rather than the process-wide
    # cached singleton.
    settings = request.app.state.settings
    return VersionResponse(version=settings.app_version, environment=settings.environment)


async def _check_postgres() -> str:
    try:
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        logger.warning("readiness_postgres_failed", extra={"error_type": type(exc).__name__})
        return "error"


async def _check_redis() -> str:
    try:
        await get_redis().ping()
        return "ok"
    except Exception as exc:
        logger.warning("readiness_redis_failed", extra={"error_type": type(exc).__name__})
        return "error"


# Registered under both prefixes; the handlers above are the single definition.
root_router.add_api_route("/health", health, methods=["GET"])
root_router.add_api_route("/health/ready", readiness, methods=["GET"])
root_router.add_api_route("/version", version, methods=["GET"])
