"""The staff health page (spec 057)."""

import asyncio

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserRole, UserStatus
from app.services import platform_health
from tests.factories import make_user


async def staff(db_session: AsyncSession, client: AsyncClient, sign_in, role=UserRole.ADMIN):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


def check_named(body: dict, name: str) -> dict:
    return next(check for check in body["checks"] if check["name"] == name)


class TestChecks:
    async def test_the_datastores_report_ok_when_they_are(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)

        body = (await client.get("/api/admin/health")).json()

        assert check_named(body, "Postgres")["state"] == "ok"
        assert check_named(body, "Redis")["state"] == "ok"

    async def test_a_disabled_feature_is_not_configured_rather_than_down(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A red light for something deliberately switched off teaches an admin
        to ignore red lights."""
        await staff(db_session, client, sign_in)

        body = (await client.get("/api/admin/health")).json()

        # Instances are off in the test settings.
        assert check_named(body, "Orchestrator")["state"] == "not_configured"

    async def test_a_check_that_times_out_reports_down_without_hanging_the_page(
        self,
    ) -> None:
        async def never() -> None:
            await asyncio.sleep(10)

        check = await platform_health._timed("Slow thing", never)

        assert check.state == "down"
        assert "no answer" in (check.detail or "")

    async def test_a_check_that_raises_reports_the_type_only(self) -> None:
        async def boom() -> None:
            raise ConnectionRefusedError("connecting to 10.0.0.5:1234")

        check = await platform_health._timed("Broken thing", boom)

        assert check.state == "down"
        assert check.detail == "ConnectionRefusedError"
        assert "10.0.0.5" not in (check.detail or "")

    async def test_checks_run_in_parallel_not_in_sequence(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The total is bounded by the slowest, which is what keeps the page
        usable when one dependency is the thing that is wrong."""
        await staff(db_session, client, sign_in)

        started = asyncio.get_running_loop().time()
        await client.get("/api/admin/health")
        elapsed = asyncio.get_running_loop().time() - started

        # Six checks, each capped at 2s. In sequence a bad run would be 12s.
        assert elapsed < platform_health.CHECK_TIMEOUT_SECONDS * 3


class TestLoad:
    async def test_it_counts_the_requests_it_served(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in)
        for _ in range(3):
            await client.get("/api/admin/health")

        body = (await client.get("/api/admin/health")).json()

        assert body["load"]["requests_per_minute"] > 0
        assert body["load"]["uptime_seconds"] >= 0

    def test_a_server_error_is_counted_as_one(self) -> None:
        counters = platform_health._Counters()
        counters.record(duration_ms=5, status_code=200)
        counters.record(duration_ms=5, status_code=500)
        counters.record(duration_ms=5, status_code=404)

        snapshot = counters.snapshot()

        # A 404 is an answer, not a fault.
        assert snapshot["errors"] == 1

    def test_the_window_drops_what_has_aged_out(self) -> None:
        counters = platform_health._Counters()
        counters.record(duration_ms=5, status_code=200)
        # Age the sample past the window.
        counters.requests[0] -= platform_health.LOAD_WINDOW_SECONDS + 1
        counters.latencies[0] = (
            counters.latencies[0][0] - platform_health.LOAD_WINDOW_SECONDS - 1,
            5,
        )

        assert counters.snapshot()["requests_per_minute"] == 0


class TestTheProbesAreUntouched:
    async def test_liveness_still_checks_nothing(self, client: AsyncClient) -> None:
        """If it touched Postgres, a brief blip would restart every pod
        mid-event. This page must not become a reason to change that."""
        response = await client.get("/api/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    async def test_readiness_still_answers(self, client: AsyncClient) -> None:
        response = await client.get("/api/health/ready")

        assert response.status_code in (200, 503)
        assert "postgres" in response.json()


class TestAccess:
    async def test_staff_may_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await staff(db_session, client, sign_in, role=UserRole.ORGANIZER)

        assert (await client.get("/api/admin/health")).status_code == 200

    async def test_a_player_may_not(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/health")).status_code == 403
