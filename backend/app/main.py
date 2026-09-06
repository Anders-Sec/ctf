"""Application factory and lifespan wiring."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, health, users
from app.config import Settings, get_settings
from app.db import dispose_engine
from app.errors import register_exception_handlers
from app.logging import configure_logging, get_logger
from app.middleware import RequestContextMiddleware
from app.redis import close_redis, get_redis

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logger.info(
        "startup",
        extra={"environment": settings.environment, "version": settings.app_version},
    )
    # Touch Redis once so a misconfigured URL surfaces at boot rather than on the
    # first player request. Connection failures are left to readiness to report.
    get_redis(settings)
    try:
        yield
    finally:
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

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(auth.router)
    api.include_router(users.router)
    app.include_router(api)

    return app


app = create_app()
