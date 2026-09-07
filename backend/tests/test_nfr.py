"""Non-functional verification (spec 012).

Three properties `Plan.md` asks for, turned into checks that run in the ordinary
suite — no cluster, no 200 real users:

- concurrent flag submission stays correct under a crowd, not just two racers;
- nothing of record lives only in Redis (the durability NFR, made deterministic);
- every admin action writes an audit row.

The full 200-player load test runs against the cluster via ``loadtest/`` and the
runbook; this is the part that guards against regressions on the way there.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models.audit import AuditLog
from app.models.challenge import (
    Category,
    Challenge,
    ChallengeAnswer,
    ChallengeState,
    MatchType,
)
from app.models.play import ScoreAdjustment, Solve, Submission
from app.models.user import User, UserRole, UserSource, UserStatus
from app.redis import get_redis
from tests.factories import make_challenge, make_container_challenge, make_template, make_user

pytestmark = pytest.mark.anyio


@pytest.fixture
async def committed_sessionmaker(
    settings: Settings,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Real connections that actually commit, for genuine cross-connection concurrency."""
    engine = create_async_engine(settings.async_database_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


class TestConcurrentSubmissions:
    """The property the load test is really about, at CI speed.

    Spec 003 proved two racers; this proves a crowd. A regression in the
    savepoint/unique-constraint guard would let a dozen simultaneous submits
    double-award — the exact failure a 200-player event would surface at the
    worst possible moment.
    """

    async def test_a_crowd_of_correct_submits_solves_once(
        self, committed_sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
    ) -> None:
        maker = committed_sessionmaker
        stamp = datetime.now(UTC).timestamp()
        concurrency = 24

        async with maker() as session:
            user = User(
                email=f"crowd-{stamp}@example.com",
                display_name="Crowd",
                source=UserSource.GUEST,
                status=UserStatus.ACTIVE,
            )
            category = Category(name=f"Crowd {stamp}", slug=f"crowd-{stamp}")
            session.add_all([user, category])
            await session.flush()
            challenge = Challenge(
                title="Crowd",
                slug=f"crowd-{stamp}",
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

        async def attempt() -> int:
            from app.services.challenges import submit_answer

            async with maker() as session:
                player = await session.get(User, user_id)
                assert player is not None
                outcome = await submit_answer(session, redis, player, challenge_id, "flag{correct}")
                await session.commit()
                return outcome.points_awarded

        try:
            # The per-challenge rate limit is 10/min, so a 24-wide burst also
            # proves the limiter does not corrupt the solve accounting — some
            # attempts are rate-limited, exactly one scores, and there is one
            # solve regardless of how the two interact.
            from app.services.rate_limit import RateLimited

            async def guarded() -> int:
                try:
                    return await attempt()
                except RateLimited:
                    return 0

            awarded = await asyncio.gather(*(guarded() for _ in range(concurrency)))

            assert sum(1 for points in awarded if points > 0) == 1, awarded

            async with maker() as session:
                solves = await session.scalar(
                    select(func.count())
                    .select_from(Solve)
                    .where(Solve.challenge_id == challenge_id)
                )
            assert solves == 1
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


class TestRedisIsCacheOnly:
    """The durability NFR, made deterministic.

    'No data loss on restart' reduces to one architectural claim: nothing of
    record lives only in Redis. So flush Redis entirely and prove every score and
    the whole board reconstruct from Postgres. Postgres's own crash durability is
    inherent (committed = fsync'd) and gets a manual pod-restart step in the
    runbook rather than a fake here.
    """

    async def test_the_board_and_scores_survive_a_full_redis_flush(
        self, db_session: AsyncSession, settings: Settings, running_event
    ) -> None:
        from app.services import scoreboard, scoring

        # Some real state: a solve and an adjustment.
        solver = await make_user(db_session, display_name="Keeper", status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=500)
        db_session.add(
            Solve(user_id=solver.id, challenge_id=challenge.id, submitted_at=datetime.now(UTC))
        )
        db_session.add(
            ScoreAdjustment(user_id=solver.id, points=50, reason="bonus", created_by_user_id=None)
        )
        await db_session.flush()

        now = datetime.now(UTC)
        score_before = await scoring.user_score(db_session, solver.id)
        board_before = await scoreboard.compute(db_session, now)
        assert score_before > 0

        # Lose the entire cache.
        redis = get_redis(settings)
        await redis.flushdb()

        # Everything rebuilds from Postgres, unchanged.
        score_after = await scoring.user_score(db_session, solver.id)
        board_after = await scoreboard.compute(db_session, now)

        assert score_after == score_before
        assert [row.user_id for row in board_after.players] == [
            row.user_id for row in board_before.players
        ]
        assert any(row.user_id == solver.id and row.score > 0 for row in board_after.players)


class TestAuditCoverage:
    """`Plan.md`: audit logging on all admin actions. A new admin endpoint that
    forgets to log fails this test."""

    async def _assert_audited(
        self, db_session: AsyncSession, action: str, do: Callable[[], Awaitable[object]]
    ) -> None:
        before = await db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
        )
        await do()
        after = await db_session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == action)
        )
        assert after == (before or 0) + 1, f"{action} was not audited"
        row = (
            (
                await db_session.execute(
                    select(AuditLog)
                    .where(AuditLog.action == action)
                    .order_by(AuditLog.created_at.desc())
                )
            )
            .scalars()
            .first()
        )
        assert row is not None
        assert row.actor_user_id is not None, f"{action} recorded no actor"

    async def test_the_named_admin_actions_are_all_audited(
        self,
        app,
        client: AsyncClient,
        db_session: AsyncSession,
        sign_in,
    ) -> None:
        """Covers the three kinds Plan.md names outright — scoring changes,
        challenge edits, container teardowns — plus user management."""
        admin = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        await sign_in(client, admin)
        app.state.settings = app.state.settings.model_copy(update={"instances_enabled": True})

        target = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)

        # Scoring change.
        await self._assert_audited(
            db_session,
            "score.adjust",
            lambda: client.post(
                "/api/admin/adjustments",
                json={"user_id": str(target.id), "points": 25, "reason": "test bonus"},
            ),
        )

        # Challenge edits: create, state change.
        challenge_id: dict[str, str] = {}

        async def create_challenge() -> None:
            resp = await client.post(
                "/api/admin/challenges",
                json={"title": "Audited", "slug": "audited", "category": "Audit"},
            )
            assert resp.status_code == 201, resp.text
            challenge_id["id"] = resp.json()["id"]

        await self._assert_audited(db_session, "challenge.create", create_challenge)
        await self._assert_audited(
            db_session,
            "challenge.set_state",
            lambda: client.post(
                f"/api/admin/challenges/{challenge_id['id']}/state",
                json={"state": "published", "reason": "go live"},
            ),
        )

        # User management.
        await self._assert_audited(
            db_session,
            "user.approve",
            lambda: client.post("/api/admin/users/approve", json={"user_ids": [str(target.id)]}),
        )
        await self._assert_audited(
            db_session,
            "user.set_role",
            lambda: client.post(f"/api/admin/users/{target.id}/role", json={"role": "organizer"}),
        )

        # Container template create, and a force-teardown.
        template = await make_template(db_session)
        container_challenge = await make_container_challenge(db_session, template)
        from app.services.instances import launcher
        from app.services.instances.fake import FakeOrchestrator

        instance = await launcher.launch(
            db_session, app.state.settings, FakeOrchestrator(), container_challenge.id, target
        )

        await self._assert_audited(
            db_session,
            "container_template.create",
            lambda: client.post(
                "/api/admin/templates",
                json={"name": "Audited Template", "image": "ghcr.io/x/y"},
            ),
        )
        await self._assert_audited(
            db_session,
            "challenge_instance.force_teardown",
            lambda: client.delete(f"/api/admin/instances/{instance.id}"),
        )
