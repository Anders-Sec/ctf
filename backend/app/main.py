"""Application factory and lifespan wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    admin,
    admin_challenges,
    admin_hints,
    admin_instances,
    admin_ops,
    admin_skills,
    assistant,
    auth,
    challenges,
    character,
    health,
    instances,
    scoreboard,
    signals,
    teams,
    users,
)
from app.config import Settings, get_settings
from app.db import dispose_engine, get_sessionmaker
from app.errors import register_exception_handlers
from app.logging import configure_logging, get_logger
from app.middleware import RequestContextMiddleware
from app.redis import close_redis, get_redis
from app.services.ai_client import close_clients as close_ai_clients
from app.services.instances.factory import build_orchestrator
from app.services.instances.reconciler import reconciler
from app.services.scoreboard_cache import broadcaster

logger = get_logger(__name__)


async def _ensure_instance_isolation(app: FastAPI) -> None:
    """Assert the namespace default-deny at boot. Best-effort: the platform
    session should also ship it, so a failure here (or the feature being off) is
    logged, never fatal."""
    settings: Settings = app.state.settings
    if not settings.instances_configured:
        return
    try:
        await app.state.orchestrator.ensure_default_deny(settings.kube_namespace)
    except Exception as exc:  # noqa: BLE001 - never block startup on the cluster
        logger.warning("instance_default_deny_failed", extra={"error_type": type(exc).__name__})


async def _purge_stale_conversations(settings: Settings) -> None:
    if not settings.ai_configured:
        return
    try:
        sessionmaker = get_sessionmaker(settings)
        async with sessionmaker() as session, session.begin():
            from app.services.assistant_review import purge_expired

            purged = await purge_expired(session, settings.ai_retention_days)
        if purged:
            logger.info("assistant_retention_purge", extra={"purged": purged})
    except Exception as exc:  # noqa: BLE001 - never block startup on this
        logger.warning("assistant_retention_purge_failed", extra={"error_type": type(exc).__name__})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "startup",
        extra={"environment": settings.environment, "version": settings.app_version},
    )
    # Touch Redis once so a misconfigured URL surfaces at boot rather than on the
    # first player request. Connection failures are left to readiness to report.
    redis = get_redis(settings)
    # One debounced recompute loop and one subscriber per process. Several pods
    # stay in step through the Redis channel, not through shared memory.
    broadcaster.start(get_sessionmaker(settings), redis)
    # A best-effort retention sweep at boot. Not the only trigger — the admin
    # console has a button — but it means a long-running deployment does not
    # accumulate stale transcripts just because nobody pressed it. Never fatal:
    # the assistant is optional and a failed purge must not stop the app serving.
    await _purge_stale_conversations(settings)
    await _ensure_instance_isolation(app)
    if settings.instances_configured:
        # One reconciler per process; several replicas stay off each other's toes
        # through the advisory lock, not shared memory.
        reconciler.start(get_sessionmaker(settings), settings, app.state.orchestrator)
    try:
        yield
    finally:
        await broadcaster.stop()
        await reconciler.stop()
        await close_ai_clients()
        await close_redis()
        await dispose_engine()
        logger.info("shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="CTF Platform API",
        version=settings.app_version,
        lifespan=lifespan,
        # Docs are a map of the platform's attack surface; players do not get one.
        docs_url=None if settings.is_production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/api/openapi.json",
    )
    app.state.settings = settings
    app.state.orchestrator = build_orchestrator(settings)

    app.add_middleware(RequestContextMiddleware)
    if settings.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    register_exception_handlers(app)

    # Probes hit the pod directly, so health lives at the root too.
    app.include_router(health.root_router)

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(admin.router)
    api.include_router(admin_challenges.router)
    api.include_router(admin_hints.router)
    api.include_router(admin_instances.router)
    api.include_router(admin_ops.router)
    api.include_router(admin_skills.router)
    api.include_router(assistant.router)
    api.include_router(challenges.router)
    api.include_router(character.router)
    api.include_router(instances.router)
    api.include_router(scoreboard.router)
    api.include_router(signals.router)
    api.include_router(teams.router)
    api.include_router(users.router)
    app.include_router(api)

    return app


app = create_app()
