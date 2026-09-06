"""Submission rate limiting, and the solve race (spec 003)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models.challenge import (
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    MatchType,
)
from app.models.play import Solve, Submission
from app.models.user import User, UserSource, UserStatus
from app.redis import get_redis
from app.services.rate_limit import (
    ATTEMPTS_PER_CHALLENGE_PER_MINUTE,
    RateLimited,
    check_submission_limits,
)
from tests.factories import make_challenge, make_user


@pytest.fixture(autouse=True)
async def clear_submission_limits(settings: Settings) -> AsyncIterator[None]:
    """Counters live in Redis and outlive a rolled-back transaction."""
    redis = get_redis(settings)

    async def flush() -> None:
        keys = [key async for key in redis.scan_iter("submit:*")]
        if keys:
            await redis.delete(*keys)

    await flush()
    yield
    await flush()


async def signed_in(db_session, client, sign_in):
    user = await make_user(db_session, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestRateLimiting:
    async def test_rapid_guessing_is_cut_off(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        await signed_in(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        statuses = []
        for attempt in range(ATTEMPTS_PER_CHALLENGE_PER_MINUTE + 3):
            response = await client.post(
                f"/api/challenges/{challenge.id}/submit", json={"answer": f"guess-{attempt}"}
            )
            statuses.append(response.status_code)

        assert (
            statuses[:ATTEMPTS_PER_CHALLENGE_PER_MINUTE]
            == [200] * ATTEMPTS_PER_CHALLENGE_PER_MINUTE
        )
        assert statuses[ATTEMPTS_PER_CHALLENGE_PER_MINUTE] == 429

    async def test_the_player_is_told_how_long_to_wait(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        await signed_in(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        response = None
        for attempt in range(ATTEMPTS_PER_CHALLENGE_PER_MINUTE + 1):
            response = await client.post(
                f"/api/challenges/{challenge.id}/submit", json={"answer": f"g{attempt}"}
            )

        assert response is not None
        body = response.json()["error"]
        assert body["code"] == "rate_limited"
        assert body["details"]["retry_after_seconds"] > 0

    async def test_the_limit_is_per_challenge_not_global(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, running_event
    ) -> None:
        """Exhausting one challenge must not lock a player out of the whole event."""
        await signed_in(db_session, client, sign_in)
        first = await make_challenge(db_session)
        second = await make_challenge(db_session)

        for attempt in range(ATTEMPTS_PER_CHALLENGE_PER_MINUTE + 1):
            await client.post(f"/api/challenges/{first.id}/submit", json={"answer": f"g{attempt}"})

        response = await client.post(
            f"/api/challenges/{second.id}/submit", json={"answer": "still allowed"}
        )

        assert response.status_code == 200

    async def test_the_limiter_fails_closed(self, settings: Settings) -> None:
        """The opposite of the magic-link limiter, and deliberately so.

        That one guards against nuisance; this one guards the scoreboard. An
        event running with brute-force protection silently off is worse than one
        that briefly refuses submissions.
        """
        import uuid

        class _DeadRedis:
            async def incr(self, *_args: object) -> int:
                raise ConnectionError("redis is gone")

        with pytest.raises(RateLimited) as caught:
            await check_submission_limits(_DeadRedis(), uuid.uuid4(), uuid.uuid4())

        assert caught.value.code == "rate_limiter_unavailable"
        assert caught.value.status_code == 503


class TestSolveRace:
    """Two correct submissions arriving at once, in real parallel transactions.

    The rest of the suite runs inside one rolled-back transaction, which cannot
    express two clients racing. These commit and clean up after themselves.
    """

    @pytest.fixture
    async def committed_sessionmaker(
        self, settings: Settings
    ) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
        engine = create_async_engine(settings.async_database_url)
        try:
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            await engine.dispose()

    async def test_the_unique_constraint_rejects_a_duplicate_solve(
        self, committed_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        """The constraint itself, on real parallel connections.

        The service-level test below passes whether or not the two coroutines
        genuinely interleave, so this one pins the guarantee it depends on: two
        connections inserting the same (user, challenge) produce one row and one
        rejection, whichever order they land in.
        """
        from sqlalchemy.exc import IntegrityError

        maker = committed_sessionmaker
        stamp = datetime.now(UTC).timestamp()

        async with maker() as session:
            user = User(
                email=f"dup-{stamp}@example.com",
                display_name="Dup",
                source=UserSource.GUEST,
                status=UserStatus.ACTIVE,
            )
            category = Category(name=f"Dup {stamp}", slug=f"dup-{stamp}")
            session.add_all([user, category])
            await session.flush()
            challenge = Challenge(
                title="Dup",
                slug=f"dup-{stamp}",
                category_id=category.id,
                state=ChallengeState.PUBLISHED,
                initial_points=100,
                minimum_points=100,
                decay_threshold=10,
            )
            session.add(challenge)
            await session.commit()
            user_id, challenge_id, category_id = user.id, challenge.id, category.id

        async def insert() -> str:
            async with maker() as session:
                session.add(
                    Solve(
                        user_id=user_id,
                        challenge_id=challenge_id,
                        submitted_at=datetime.now(UTC),
                    )
                )
                try:
                    await session.commit()
                    return "inserted"
                except IntegrityError:
                    await session.rollback()
                    return "rejected"

        try:
            results = await asyncio.gather(insert(), insert())

            assert sorted(results) == ["inserted", "rejected"], results
        finally:
            async with maker() as session:
                await session.execute(delete(Solve).where(Solve.challenge_id == challenge_id))
                await session.execute(delete(Challenge).where(Challenge.id == challenge_id))
                await session.execute(delete(Category).where(Category.id == category_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()

    async def test_two_correct_submissions_award_points_once(
        self, committed_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        maker = committed_sessionmaker
        stamp = datetime.now(UTC).timestamp()

        async with maker() as session:
            user = User(
                email=f"racer-{stamp}@example.com",
                display_name="Racer",
                source=UserSource.GUEST,
                status=UserStatus.ACTIVE,
            )
            category = Category(name=f"Race {stamp}", slug=f"race-{stamp}")
            session.add_all([user, category])
            await session.flush()
            challenge = Challenge(
                title="Race",
                slug=f"race-{stamp}",
                category_id=category.id,
                state=ChallengeState.PUBLISHED,
                initial_points=500,
                minimum_points=100,
                decay_threshold=10,
            )
            session.add(challenge)
            await session.flush()
            session.add(
                ChallengeAnswer(
                    challenge_id=challenge.id,
                    match_type=MatchType.EXACT,
                    value="flag{correct}",
                    options={},
                )
            )
            await session.commit()
            user_id, challenge_id, category_id = user.id, challenge.id, category.id

        redis = get_redis(settings)
        for key in [k async for k in redis.scan_iter("submit:*")]:
            await redis.delete(key)

        async def attempt() -> bool:
            from app.services.challenges import submit_answer

            async with maker() as session:
                player = await session.get(User, user_id)
                assert player is not None
                outcome = await submit_answer(session, redis, player, challenge_id, "flag{correct}")
                await session.commit()
                return outcome.points_awarded > 0

        try:
            awarded = await asyncio.gather(attempt(), attempt())

            # Exactly one of them scored. Whether these two genuinely interleaved
            # or ran back to back, the outcome must be the same — the test above
            # pins the constraint that makes the interleaved case safe.
            assert sum(awarded) == 1, awarded

            async with maker() as session:
                solves = (
                    (await session.execute(select(Solve).where(Solve.challenge_id == challenge_id)))
                    .scalars()
                    .all()
                )
                submissions = (
                    (
                        await session.execute(
                            select(Submission).where(Submission.challenge_id == challenge_id)
                        )
                    )
                    .scalars()
                    .all()
                )

            assert len(solves) == 1
            # Both attempts are still in the log: losing the race must not erase
            # the evidence that it happened.
            assert len(submissions) == 2
        finally:
            async with maker() as session:
                await session.execute(delete(Solve).where(Solve.challenge_id == challenge_id))
                await session.execute(
                    delete(Submission).where(Submission.challenge_id == challenge_id)
                )
                await session.execute(
                    delete(ChallengeAnswer).where(ChallengeAnswer.challenge_id == challenge_id)
                )
                await session.execute(delete(Challenge).where(Challenge.id == challenge_id))
                await session.execute(delete(Category).where(Category.id == category_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
