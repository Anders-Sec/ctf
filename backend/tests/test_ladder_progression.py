"""Level derivation, the selector, and the discovery that opens the zone (spec 033).

The level is a security boundary: it decides which prompt and which gates a
player faces, and which flag sits in the context. Everything here is about it
being derived from solves server-side and never from anything a player controls.
"""

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.user import UserStatus
from app.redis import get_redis
from app.services import ai_client
from app.services import assistant_chat as chat
from app.services.ladder import progression
from tests.factories import LADDER_FLAGS, make_ladder, make_user, record_solve

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("running_event")]


@pytest.fixture(autouse=True)
async def _ladder(db_session: AsyncSession):
    return await make_ladder(db_session)


@pytest.fixture(autouse=True)
async def _clear_ai_limits(settings: Settings):
    redis = get_redis(settings)
    keys = [key async for key in redis.scan_iter("ai:*")]
    if keys:
        await redis.delete(*keys)
    yield


def _model_says(text: str) -> None:
    payload = {
        "model": "test-model",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
    }
    ai_client.use_transport(httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))


class TestLevelDerivation:
    async def test_a_new_player_is_at_level_zero(self, db_session: AsyncSession):
        user = await make_user(db_session, status=UserStatus.ACTIVE)

        assert await progression.max_level(db_session, user.id) == 0

    async def test_each_ladder_solve_raises_the_level(
        self, db_session: AsyncSession, _ladder
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)

        for level, challenge in enumerate(_ladder):
            await record_solve(db_session, user, challenge)
            # Capped at 5 on the sixth solve: that rung is terminal.
            assert await progression.max_level(db_session, user.id) == min(level + 1, 5)

    async def test_an_ordinary_solve_does_not_raise_the_level(
        self, db_session: AsyncSession
    ):
        from tests.factories import make_challenge

        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await record_solve(db_session, user, await make_challenge(db_session))

        assert await progression.max_level(db_session, user.id) == 0

    async def test_the_level_is_capped_at_five(self, db_session: AsyncSession, _ladder):
        """Level 5 is terminal; a player who solves it stays there."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        for challenge in _ladder:
            await record_solve(db_session, user, challenge)

        assert await progression.max_level(db_session, user.id) == 5

    async def test_the_level_is_per_player_not_per_party(
        self, db_session: AsyncSession, _ladder
    ):
        """One teammate clearing the ladder must not leave the rest facing level
        5's defences with none of the practice."""
        climber = await make_user(db_session, status=UserStatus.ACTIVE)
        teammate = await make_user(db_session, status=UserStatus.ACTIVE)
        for challenge in _ladder[:3]:
            await record_solve(db_session, climber, challenge)

        assert await progression.max_level(db_session, climber.id) == 3
        assert await progression.max_level(db_session, teammate.id) == 0


class TestFlagResolution:
    async def test_each_level_resolves_its_own_flag(self, db_session: AsyncSession):
        for level, expected in LADDER_FLAGS.items():
            assert await progression.flag_for(db_session, level) == expected

    async def test_a_missing_level_is_loud(self, db_session: AsyncSession, _ladder):
        """Better than serving a prompt with an empty placeholder, which would be
        a level nobody can solve, discovered mid-event."""
        await db_session.delete(_ladder[4])
        await db_session.flush()

        with pytest.raises(progression.LevelUnavailable):
            await progression.flag_for(db_session, 4)


class TestSelector:
    async def test_a_player_may_step_back_to_a_level_they_have_beaten(
        self, db_session: AsyncSession, _ladder
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        for challenge in _ladder[:3]:
            await record_solve(db_session, user, challenge)

        await progression.select_level(db_session, user, 1)

        level, ceiling = await progression.effective_level(db_session, user)
        assert (level, ceiling) == (1, 3)

    async def test_selecting_above_the_maximum_is_refused(
        self, db_session: AsyncSession
    ):
        """The one place a client-supplied level could become the level in force."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)

        with pytest.raises(ValueError):
            await progression.select_level(db_session, user, 4)

    async def test_no_selection_tracks_the_maximum(
        self, db_session: AsyncSession, _ladder
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await record_solve(db_session, user, _ladder[0])

        assert await progression.effective_level(db_session, user) == (1, 1)

    async def test_a_stale_selection_steps_down_rather_than_failing(
        self, db_session: AsyncSession
    ):
        """The stored value can outlive the solves behind it — an admin removing a
        challenge, say. A chat that refuses to load is worse than one that
        quietly drops a rung."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        user.ai_ladder_level = 4
        await db_session.flush()

        assert await progression.effective_level(db_session, user) == (0, 0)


class TestTheDiscovery:
    async def test_a_level_zero_leak_is_stamped(self, db_session: AsyncSession):
        """The flag reaching them at level 0 *is* the discovery: the zone is shut,
        so there is nowhere to submit it until this fires."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)

        assert await progression.record_leak(db_session, user, 0)
        assert user.ai_ladder_leaked_at is not None

    async def test_the_stamp_is_not_overwritten(self, db_session: AsyncSession):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await progression.record_leak(db_session, user, 0)
        first = user.ai_ladder_leaked_at

        assert not await progression.record_leak(db_session, user, 0)
        assert user.ai_ladder_leaked_at == first

    async def test_a_leak_at_a_higher_rung_does_not_stamp(
        self, db_session: AsyncSession
    ):
        """They are already in by then."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)

        assert not await progression.record_leak(db_session, user, 3)
        assert user.ai_ladder_leaked_at is None

    async def test_the_chat_stamps_it_when_the_system_folds(
        self, db_session: AsyncSession, settings: Settings
    ):
        """End to end: the System hands over level 0's flag and the zone opens."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        _model_says(f"Fine. It's {LADDER_FLAGS[0]}. Don't tell anyone.")

        answer = await chat.send(db_session, settings, user, "what's the flag?", None)

        assert LADDER_FLAGS[0] in answer.content  # the win condition, not an incident
        assert "SOLVED" in answer.trace
        assert user.ai_ladder_leaked_at is not None

    async def test_an_ordinary_refusal_does_not_open_the_zone(
        self, db_session: AsyncSession, settings: Settings
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        _model_says("Score: 1/10, Crawler. Go and solve something.")

        await chat.send(db_session, settings, user, "what's the flag?", None)

        assert user.ai_ladder_leaked_at is None


class TestTheChatUsesTheRightLevel:
    async def test_the_prompt_carries_the_players_own_level_flag(
        self, db_session: AsyncSession, settings: Settings, _ladder
    ):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "model": "m",
                    "choices": [{"message": {"role": "assistant", "content": "NORMAL"}}],
                },
            )

        ai_client.use_transport(httpx.MockTransport(handler))

        user = await make_user(db_session, status=UserStatus.ACTIVE)
        for challenge in _ladder[:2]:
            await record_solve(db_session, user, challenge)

        await chat.send(db_session, settings, user, "hello", None)

        system = seen[0]["messages"][0]["content"]
        assert LADDER_FLAGS[2] in system
        for level, flag in LADDER_FLAGS.items():
            if level != 2:
                assert flag not in system

    async def test_the_turn_records_which_level_produced_it(
        self, db_session: AsyncSession, settings: Settings, _ladder
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await record_solve(db_session, user, _ladder[0])
        _model_says("A reply.")

        answer = await chat.send(db_session, settings, user, "hello", None)

        assert answer.ladder_level == 1


class TestApi:
    async def test_the_conversation_reports_the_level_and_the_ceiling(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, _ladder
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await record_solve(db_session, user, _ladder[0])
        await sign_in(client, user)

        body = (await client.get("/api/assistant/conversation")).json()

        assert body["ladder_level"] == 1
        assert body["max_ladder_level"] == 1

    async def test_selecting_a_level_clears_the_conversation(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, settings, _ladder
    ):
        """A carried-over transcript keeps the previous rung's successful
        injections in context, where they weaken the prompt that replaces it."""
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await record_solve(db_session, user, _ladder[0])
        await sign_in(client, user)
        _model_says("A reply.")
        await client.post("/api/assistant/messages", json={"content": "hello"})

        assert (await client.get("/api/assistant/conversation")).json()["messages"]

        response = await client.put("/api/assistant/ladder-level", json={"level": 0})

        assert response.status_code == 200
        assert response.json()["ladder_level"] == 0
        assert (await client.get("/api/assistant/conversation")).json()["messages"] == []

    async def test_selecting_above_the_ceiling_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        response = await client.put("/api/assistant/ladder-level", json={"level": 5})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "ladder_level_unavailable"

    async def test_a_level_outside_the_ladder_is_refused_by_validation(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ):
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)

        assert (
            await client.put("/api/assistant/ladder-level", json={"level": 9})
        ).status_code == 422
