"""Shared test fixtures.

Tests run against the real Postgres and Redis from docker-compose, not against
SQLite or fakes. Spec 001 makes this call deliberately: later specs depend on
Postgres-specific behaviour (timestamptz, ON CONFLICT, partial unique indexes,
advisory locks) that a substitute engine would not reproduce.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.main import create_app

TEST_DATABASE_NAME = "ctf_test"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _test_settings() -> Settings:
    base = Settings()  # type: ignore[call-arg]
    # Point at a separate database so a test run never touches dev data.
    database_url = base.database_url.rsplit("/", 1)[0] + f"/{TEST_DATABASE_NAME}"
    return Settings(
        environment="local",
        app_version="test",
        log_level=os.getenv("TEST_LOG_LEVEL", "WARNING"),
        database_url=database_url,
        redis_url=base.redis_url,
        cors_allowed_origins=[],
    )


@pytest.fixture(scope="session")
def settings() -> Settings:
    return _test_settings()


@pytest.fixture(scope="session", autouse=True)
async def _create_test_database(settings: Settings) -> AsyncIterator[None]:
    """Create the test database once per session if it does not exist."""
    admin_url = settings.async_database_url.rsplit("/", 1)[0] + "/postgres"
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DATABASE_NAME},
            )
            if not exists:
                await connection.execute(text(f'CREATE DATABASE "{TEST_DATABASE_NAME}"'))
    finally:
        await engine.dispose()
    yield


@pytest.fixture(scope="session", autouse=True)
async def _migrate(_create_test_database: None, settings: Settings) -> AsyncIterator[None]:
    """Apply migrations to the test database.

    Run through Alembic rather than ``Base.metadata.create_all`` so the tests
    exercise the same schema the event will actually run on — a migration that
    does not apply cleanly should fail the build, not be bypassed.
    """
    from alembic import command
    from alembic.config import Config

    # Alembic is synchronous and blocks the loop, which is fine for one-off
    # session setup but is why this does not belong in a request path.
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.sync_database_url)
    command.upgrade(config, "head")
    yield


@pytest.fixture(scope="session", autouse=True)
async def _wire_app_globals(_migrate: None, settings: Settings) -> AsyncIterator[None]:
    """Repoint the app's engine and Redis client at the test instances.

    ``app.db`` and ``app.redis`` hold lazily-created singletons built from the
    process-wide settings. Importing ``app.main`` already built an app from the
    real .env, so reset them and prime them with the test settings before any
    request runs — otherwise readiness checks would report on the dev database.
    """
    from app import db as db_module
    from app import redis as redis_module

    await db_module.dispose_engine()
    await redis_module.close_redis()

    db_module.get_sessionmaker(settings)
    redis_module.get_redis(settings)
    try:
        yield
    finally:
        await db_module.dispose_engine()
        await redis_module.close_redis()


@pytest.fixture
async def db_session(settings: Settings) -> AsyncIterator[AsyncSession]:
    """A session wrapped in a transaction that is rolled back after each test."""
    engine = create_async_engine(settings.async_database_url)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = async_sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as async_client:
        yield async_client
