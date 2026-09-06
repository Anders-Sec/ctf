"""Tests for the health, readiness and version endpoints (spec 001)."""

import pytest
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import Settings
from app.main import create_app


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_does_not_touch_dependencies(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Liveness must stay cheap: a DB blip should not restart every pod."""

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("liveness must not check dependencies")

    monkeypatch.setattr("app.api.routes.health.get_sessionmaker", _explode)
    monkeypatch.setattr("app.api.routes.health.get_redis", _explode)

    response = await client.get("/api/health")

    assert response.status_code == 200


async def test_readiness_reports_healthy_dependencies(client: AsyncClient) -> None:
    response = await client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "ok", "redis": "ok"}


async def test_readiness_returns_503_when_redis_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _DeadRedis:
        async def ping(self) -> bool:
            raise RedisConnectionError("connection refused")

    monkeypatch.setattr("app.api.routes.health.get_redis", lambda *_: _DeadRedis())

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "error"
    # Postgres is still fine, and readiness says so rather than blaming everything.
    assert body["postgres"] == "ok"


async def test_readiness_returns_503_when_postgres_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _dead_sessionmaker(*_args: object, **_kwargs: object) -> object:
        raise OSError("connection refused")

    monkeypatch.setattr("app.api.routes.health.get_sessionmaker", _dead_sessionmaker)

    response = await client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["postgres"] == "error"


async def test_version_reports_configured_values(client: AsyncClient) -> None:
    response = await client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"version": "test", "environment": "local"}


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/health")

    assert response.headers["X-Request-ID"]


async def test_inbound_request_id_is_echoed_back(client: AsyncClient) -> None:
    """Correlation ids from an ingress or a load test should survive the round trip."""
    response = await client.get("/api/health", headers={"X-Request-ID": "load-test-42"})

    assert response.headers["X-Request-ID"] == "load-test-42"


async def test_inbound_request_id_is_truncated(client: AsyncClient) -> None:
    """The header is attacker-controlled and lands in logs, so it is capped."""
    response = await client.get("/api/health", headers={"X-Request-ID": "x" * 500})

    assert len(response.headers["X-Request-ID"]) == 64


async def test_docs_are_hidden_in_production(settings: Settings) -> None:
    """The OpenAPI schema is a map of the platform; players do not get one."""
    prod_settings = settings.model_copy(update={"environment": "prod"})
    prod_app = create_app(prod_settings)

    async with AsyncClient(
        transport=ASGITransport(app=prod_app), base_url="http://test"
    ) as prod_client:
        assert (await prod_client.get("/api/docs")).status_code == 404
        assert (await prod_client.get("/api/openapi.json")).status_code == 404


async def test_docs_are_available_outside_production(client: AsyncClient) -> None:
    assert (await client.get("/api/docs")).status_code == 200
