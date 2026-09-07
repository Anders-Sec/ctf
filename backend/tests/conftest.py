"""Shared test fixtures.

Tests run against the real Postgres and Redis from docker-compose, not against
SQLite or fakes. Spec 001 makes this call deliberately: later specs depend on
Postgres-specific behaviour (timestamptz, ON CONFLICT, partial unique indexes,
advisory locks) that a substitute engine would not reproduce.
"""

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db import get_db_session
from app.main import create_app
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.user import User
from app.services import ai_client
from app.services.cookies import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
)
from app.services.instances.fake import FakeOrchestrator
from app.services.sessions import IssuedSession, issue_session

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
        # No SMTP under test, ever. Without this the suite inherits the real
        # relay from .env and genuinely mails the fake addresses in the
        # fixtures — magic links and approval notices both.
        smtp_host=None,
        smtp_from=None,
        smtp_username=None,
        smtp_token=None,
        # A host that cannot resolve, so a test that forgets to install a fake
        # transport fails loudly instead of reaching the real model box.
        ai_base_url="http://model.invalid/v1",
        ai_api_key="test-key",
        ai_model="test-model",
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
    # create_savepoint: a test that provokes an IntegrityError rolls the session
    # back to a savepoint rather than tearing down the outer transaction, so the
    # test can keep using the session afterwards.
    session = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )()
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
def app(settings: Settings, db_session: AsyncSession) -> FastAPI:
    """An app whose requests run inside the test's rolled-back transaction.

    Without the override, a route would open its own session and could not see
    rows the test had created but not committed.
    """
    application = create_app(settings)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    application.dependency_overrides[get_db_session] = _override_session
    # A controllable fake so instance tests can drive readiness and inspect what
    # would have been applied, with no cluster in the loop.
    application.state.orchestrator = FakeOrchestrator()
    return application


@pytest.fixture
def orchestrator(app: FastAPI) -> FakeOrchestrator:
    """The fake the test app is using, for driving and inspecting instances."""
    return app.state.orchestrator


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as async_client:
        yield async_client


@pytest.fixture
async def sign_in(db_session: AsyncSession, settings: Settings):
    """Put a real session's cookies on a client, as a browser would carry them."""

    async def _sign_in(http_client: AsyncClient, user: User) -> IssuedSession:
        session = await issue_session(db_session, settings, user.id)
        http_client.cookies.set(ACCESS_COOKIE, session.access_token)
        # Same path the app scopes it to, or httpx ends up holding two cookies
        # of the same name after a refresh and cannot decide between them.
        http_client.cookies.set(REFRESH_COOKIE, session.refresh_token, path=REFRESH_COOKIE_PATH)
        http_client.cookies.set(CSRF_COOKIE, session.csrf_token)
        # The SPA copies the readable CSRF cookie into this header; tests do the
        # same rather than bypassing the check.
        http_client.headers[CSRF_HEADER] = session.csrf_token
        return session

    return _sign_in


@pytest.fixture
async def running_event(db_session: AsyncSession) -> EventConfig:
    """Put the event into its running window so gameplay gates open."""
    from datetime import UTC, datetime, timedelta

    config = await db_session.get(EventConfig, EVENT_CONFIG_ID)
    assert config is not None
    now = datetime.now(UTC)
    config.starts_at = now - timedelta(hours=1)
    config.ends_at = now + timedelta(days=1)
    await db_session.flush()
    return config


@pytest.fixture
async def clear_rate_limits(settings: Settings):
    """Rate-limit counters live in Redis and outlive a rolled-back transaction."""
    from app.redis import get_redis

    redis = get_redis(settings)
    keys = [key async for key in redis.scan_iter("magiclink:*")]
    if keys:
        await redis.delete(*keys)
    yield
    keys = [key async for key in redis.scan_iter("magiclink:*")]
    if keys:
        await redis.delete(*keys)


@pytest.fixture(autouse=True)
def no_outbound_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test tries to send mail.

    The settings above already leave SMTP unconfigured, so nothing should reach
    the transport. This is the tripwire: a future endpoint that sends
    unconditionally would otherwise start mailing example.com addresses and
    nobody would notice until the bounces arrived.
    """

    async def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a test attempted to send real mail")

    monkeypatch.setattr("app.services.mail.send_message", _refuse)


@pytest.fixture(autouse=True)
def _reset_ai_client() -> Iterator[None]:
    """Breakers and connection pools are module state; do not leak them between tests."""
    ai_client.reset_state()
    yield
    ai_client.reset_state()
