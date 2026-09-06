"""Scoreboard endpoints, caching, and the live WebSocket (spec 005)."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.challenge import ScoringMode
from app.models.user import UserRole, UserStatus
from app.redis import get_redis
from app.services import scoreboard_cache
from tests.factories import make_challenge, make_team, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


@pytest.fixture(autouse=True)
async def clear_scoreboard_cache(settings: Settings):
    """The cache outlives a rolled-back transaction, so it must be cleared."""
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


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


class TestAccess:
    async def test_an_anonymous_visitor_cannot_read_the_board(self, client: AsyncClient) -> None:
        assert (await client.get("/api/scoreboard/players")).status_code == 401

    async def test_a_pending_guest_cannot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, status=UserStatus.PENDING_APPROVAL)

        response = await client.get("/api/scoreboard/players")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "account_pending_approval"

    async def test_the_board_is_closed_before_the_event_starts(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        running_event.starts_at = datetime.now(UTC) + timedelta(hours=1)
        await db_session.flush()
        await player(db_session, client, sign_in)

        response = await client.get("/api/scoreboard/players")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "event_not_started"

    async def test_the_board_stays_open_after_the_event_ends(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        """The final standings are the point. They must not vanish at the buzzer."""
        running_event.starts_at = datetime.now(UTC) - timedelta(days=2)
        running_event.ends_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.flush()
        await player(db_session, client, sign_in)

        assert (await client.get("/api/scoreboard/players")).status_code == 200

    async def test_a_player_cannot_read_the_admin_board(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        assert (await client.get("/api/admin/scoreboard")).status_code == 403

    async def test_staff_can(self, client: AsyncClient, db_session: AsyncSession, sign_in) -> None:
        await player(db_session, client, sign_in, role=UserRole.ORGANIZER)

        assert (await client.get("/api/admin/scoreboard")).status_code == 200


class TestBoards:
    async def test_the_player_board_ranks(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        big = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        small = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        leader = await make_user(db_session, display_name="Leader", status=UserStatus.ACTIVE)
        trailer = await make_user(db_session, display_name="Trailer", status=UserStatus.ACTIVE)
        await record_solve(db_session, leader, big)
        await record_solve(db_session, trailer, small)
        await player(db_session, client, sign_in)

        entries = (await client.get("/api/scoreboard/players")).json()["entries"]

        assert entries[0]["display_name"] == "Leader"
        assert entries[0]["rank"] == 1
        assert entries[0]["score"] == 300

    async def test_the_party_board_uses_the_union_rule(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Same ceiling for a party of one and a party of two."""
        first = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        second = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)

        solo = await make_user(db_session, status=UserStatus.ACTIVE)
        solo_team = await make_team(db_session, solo, name="Alone")
        await record_solve(db_session, solo, first, team=solo_team)
        await record_solve(db_session, solo, second, team=solo_team)

        from tests.factories import add_member

        a = await make_user(db_session, status=UserStatus.ACTIVE)
        pair = await make_team(db_session, a, name="Pair")
        b = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, pair, b)
        await record_solve(db_session, a, first, team=pair)
        await record_solve(db_session, b, second, team=pair)

        await player(db_session, client, sign_in)
        entries = {
            e["name"]: e["score"]
            for e in (await client.get("/api/scoreboard/teams")).json()["entries"]
        }

        assert entries["Alone"] == 200
        assert entries["Pair"] == 200

    async def test_my_standing_reports_both_ranks(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=250)
        user = await player(db_session, client, sign_in)
        team = await make_team(db_session, user, name="Mine")
        await record_solve(db_session, user, challenge, team=team)

        body = (await client.get("/api/scoreboard/me")).json()

        assert body["rank"] == 1
        assert body["score"] == 250
        assert body["team_rank"] == 1
        assert body["team_score"] == 250

    async def test_a_partyless_player_has_no_party_rank(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)

        body = (await client.get("/api/scoreboard/me")).json()

        assert body["team_rank"] is None
        assert body["team_score"] is None


class TestCaching:
    async def test_a_solve_marks_the_board_dirty(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        redis = get_redis(settings)
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        await redis.delete(scoreboard_cache.DIRTY_KEY)

        await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        assert await redis.get(scoreboard_cache.DIRTY_KEY) is not None
        assert user.id is not None

    async def test_a_wrong_answer_does_not(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings: Settings
    ) -> None:
        """Nothing scored, so nothing to recompute."""
        redis = get_redis(settings)
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        await redis.delete(scoreboard_cache.DIRTY_KEY)

        await client.post(f"/api/challenges/{challenge.id}/submit", json={"answer": "nope"})

        assert await redis.get(scoreboard_cache.DIRTY_KEY) is None

    async def test_a_refresh_caches_and_publishes(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        redis = get_redis(settings)

        payload = await scoreboard_cache.refresh(db_session, redis, force=True)

        assert "players" in payload and "teams" in payload
        cached = json.loads(await redis.get(scoreboard_cache.CACHE_KEY))
        assert cached["generated_at"] == payload["generated_at"]
        # The dirty flag is cleared by the recompute that consumed it.
        assert await redis.get(scoreboard_cache.DIRTY_KEY) is None

    async def test_the_lock_is_released_so_the_next_change_is_not_throttled(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Left to expire, the lock would throttle recomputes to one per TTL.

        A change made just after a refresh would then sit unreflected for ten
        seconds, which is exactly how a score override appears not to work.
        """
        redis = get_redis(settings)

        await scoreboard_cache.refresh(db_session, redis, force=True)

        assert await redis.get(scoreboard_cache.LOCK_KEY) is None

    async def test_a_second_change_recomputes_immediately(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        redis = get_redis(settings)
        player = await make_user(db_session, display_name="Mover", status=UserStatus.ACTIVE)
        await scoreboard_cache.refresh(db_session, redis, force=True)

        from app.models.play import ScoreAdjustment

        db_session.add(ScoreAdjustment(user_id=player.id, points=42, reason="Award"))
        await db_session.flush()
        await scoreboard_cache.mark_dirty(redis)

        payload = await scoreboard_cache.refresh(db_session, redis)
        entry = next(p for p in payload["players"] if p["display_name"] == "Mover")
        assert entry["score"] == 42

    async def test_the_board_still_answers_when_redis_is_unavailable(
        self, db_session: AsyncSession
    ) -> None:
        """Degraded, not broken: straight from Postgres, no cache, no push."""

        class _DeadRedis:
            async def get(self, *_args: object) -> None:
                raise ConnectionError("redis is gone")

            async def set(self, *_args: object, **_kwargs: object) -> None:
                raise ConnectionError("redis is gone")

        payload = await scoreboard_cache.refresh(db_session, _DeadRedis())

        assert "players" in payload

    async def test_marking_dirty_never_raises(self) -> None:
        """A solve must not fail because the scoreboard cache is unreachable."""

        class _DeadRedis:
            async def set(self, *_args: object, **_kwargs: object) -> None:
                raise ConnectionError("redis is gone")

        await scoreboard_cache.mark_dirty(_DeadRedis())


class TestBroadcaster:
    async def test_a_slow_client_is_dropped_rather_than_growing_a_queue(self) -> None:
        broadcaster = scoreboard_cache.ScoreboardBroadcaster()
        queue = broadcaster.subscribe()

        # Push well past the bound without anyone reading.
        for index in range(50):
            broadcaster._fan_out(f"payload-{index}")

        assert broadcaster.client_count == 0
        assert queue.full()

    async def test_a_keeping_up_client_receives_every_board(self) -> None:
        broadcaster = scoreboard_cache.ScoreboardBroadcaster()
        queue = broadcaster.subscribe()

        broadcaster._fan_out("first")
        broadcaster._fan_out("second")

        assert await queue.get() == "first"
        assert await queue.get() == "second"
        assert broadcaster.client_count == 1

    async def test_unsubscribing_stops_delivery(self) -> None:
        broadcaster = scoreboard_cache.ScoreboardBroadcaster()
        queue = broadcaster.subscribe()
        broadcaster.unsubscribe(queue)

        broadcaster._fan_out("ignored")

        assert queue.empty()
