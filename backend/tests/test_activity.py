"""The ticker (spec 069).

The test that matters is §3's: a non-boss row carries **no challenge title**.
Naming the challenge would hand every watcher a list of solvable work, and the
decision is enforced on the server because a title the client is asked to hide is
a title in the payload.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import BossTier, ScoringMode
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


@pytest.fixture(autouse=True)
async def clear_scoreboard_cache(settings: Settings):
    """The ticker rides the board's payload, so the board's cache is its cache."""
    redis = get_redis(settings)

    async def flush() -> None:
        await redis.delete(
            scoreboard_cache.CACHE_KEY,
            scoreboard_cache.DIRTY_KEY,
            scoreboard_cache.LOCK_KEY,
        )

    await flush()
    yield
    await flush()


async def viewer(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def zone(db_session, name: str):
    return await make_category(db_session, name=f"{name} {uuid.uuid4().hex[:6]}")


class TestWhatItSays:
    async def test_a_solve_names_the_zone_and_not_the_challenge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """§3. The whole cost of the feature, paid down to the zone."""
        web = await zone(db_session, "Web")
        challenge = await make_challenge(
            db_session, category=web, title="Port of Call", scoring=ScoringMode.STATIC
        )
        solver = await make_user(db_session, display_name="Rin")
        await record_solve(db_session, solver, challenge)
        await viewer(db_session, client, sign_in, display_name="Watcher")

        body = (await client.get("/api/activity")).json()
        row = next(item for item in body["items"] if item["display_name"] == "Rin")

        assert row["kind"] == "solve"
        assert row["zone_name"] == web.name
        assert row["challenge_title"] is None
        # Not merely null on the row — absent from the whole payload.
        assert "Port of Call" not in str(body)

    async def test_a_boss_kill_is_named_in_full(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Spec 032 already broadcasts these by name; being first is the point."""
        web = await zone(db_session, "Web")
        boss = await make_challenge(
            db_session, category=web, title="The Gatekeeper", scoring=ScoringMode.STATIC
        )
        boss.boss_tier = BossTier.CITY
        await db_session.flush()

        slayer = await make_user(db_session, display_name="Vek")
        await record_solve(db_session, slayer, boss)
        await viewer(db_session, client, sign_in, display_name="Watcher")

        body = (await client.get("/api/activity")).json()
        row = next(item for item in body["items"] if item["display_name"] == "Vek")

        assert row["kind"] == "boss"
        assert row["challenge_title"] == "The Gatekeeper"
        assert row["tier"] == "city"
        assert row["tier_level"] == 3

    async def test_it_runs_newest_first(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        web = await zone(db_session, "Web")
        early = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)
        late = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)
        solver = await make_user(db_session, display_name="Rin")

        first = await record_solve(db_session, solver, early)
        second = await record_solve(db_session, solver, late)
        now = datetime.now(UTC).replace(tzinfo=None)
        first.submitted_at = now - timedelta(hours=2)
        second.submitted_at = now
        await db_session.flush()
        await viewer(db_session, client, sign_in, display_name="Watcher")

        items = (await client.get("/api/activity")).json()["items"]
        ours = [item for item in items if item["display_name"] == "Rin"]

        assert ours[0]["at"] > ours[1]["at"]

    async def test_staff_do_not_appear(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The same exclusion the board makes: staff run the event, not win it."""
        web = await zone(db_session, "Web")
        challenge = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)
        staff = await make_user(db_session, display_name="Dungeon Master", role=UserRole.ADMIN)
        await record_solve(db_session, staff, challenge)
        await viewer(db_session, client, sign_in, display_name="Watcher")

        body = (await client.get("/api/activity")).json()

        assert "Dungeon Master" not in str(body)

    async def test_it_is_empty_rather_than_absent_when_nothing_has_happened(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await viewer(db_session, client, sign_in, display_name="Watcher")

        response = await client.get("/api/activity")

        assert response.status_code == 200
        assert "items" in response.json()


class TestItRidesTheBoard:
    async def test_the_board_payload_carries_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Computed once per recompute and shared, rather than a query each."""
        web = await zone(db_session, "Web")
        challenge = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)
        solver = await make_user(db_session, display_name="Rin")
        await record_solve(db_session, solver, challenge)
        await viewer(db_session, client, sign_in, display_name="Watcher")

        payload = await scoreboard_cache.refresh(db_session, get_redis(_settings()), force=True)

        assert any(item["display_name"] == "Rin" for item in payload["activity"])

    async def test_the_public_view_leaves_it_alone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """There is no XP in it, so nothing to strip."""
        web = await zone(db_session, "Web")
        challenge = await make_challenge(db_session, category=web, scoring=ScoringMode.STATIC)
        solver = await make_user(db_session, display_name="Rin")
        await record_solve(db_session, solver, challenge)

        payload = await scoreboard_cache.refresh(db_session, get_redis(_settings()), force=True)
        public = scoreboard_cache.public_view(payload)

        assert public["activity"] == payload["activity"]
        for item in public["activity"]:
            assert not any("xp" in key for key in item)


def _settings() -> Settings:
    from app.config import get_settings

    return get_settings()
