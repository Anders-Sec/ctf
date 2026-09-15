"""Where puzzles meet the rest of the platform (spec 044 §8, §10).

Deletion, prerequisite gates, hint costs, the anti-cheat exemption, the reset
group, and two completing moves racing. Each of these is a place where the
puzzle path had to reuse something rather than reimplement it, which is exactly
where a second implementation would have hidden.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models.challenge import Category, Challenge, ChallengeState, ScoringMode
from app.models.hint import Hint
from app.models.play import Solve
from app.models.puzzle import ChallengePuzzle, PuzzleKind, PuzzleSession, PuzzleStatus
from app.models.user import User, UserRole, UserSource, UserStatus
from app.services import event_reset, signals
from tests.factories import make_challenge, make_puzzle, make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def puzzle_challenge(db_session, kind=PuzzleKind.WORDLE, **kwargs):
    kwargs.setdefault("scoring", ScoringMode.STATIC)
    kwargs.setdefault("initial_points", 150)
    kwargs.setdefault("answers", [])
    challenge = await make_challenge(db_session, **kwargs)
    await make_puzzle(db_session, challenge, kind=kind)
    return challenge


async def move(client: AsyncClient, challenge_id, **payload):
    return await client.post(f"/api/challenges/{challenge_id}/puzzle/move", json={"move": payload})


class TestDeletingAChallenge:
    async def test_it_takes_the_puzzle_and_the_sessions(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
        challenge = await puzzle_challenge(db_session)
        other = await make_user(db_session, status=UserStatus.ACTIVE)
        db_session.add(
            PuzzleSession(
                user_id=other.id,
                challenge_id=challenge.id,
                state={},
                started_at=datetime.now(UTC),
            )
        )
        await db_session.flush()
        await sign_in(client, admin)

        assert (await client.delete(f"/api/admin/challenges/{challenge.id}")).status_code == 200

        assert (
            await db_session.execute(
                select(ChallengePuzzle).where(ChallengePuzzle.challenge_id == challenge.id)
            )
        ).scalar_one_or_none() is None
        assert (
            await db_session.execute(
                select(PuzzleSession).where(PuzzleSession.challenge_id == challenge.id)
            )
        ).scalars().all() == []

    async def test_a_solved_puzzle_challenge_still_cannot_be_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # The existing protection has to keep working through the new route in:
        # a puzzle solve is a solve.
        user = await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)
        await move(client, challenge.id, guess="PROXY")

        user.role = UserRole.ADMIN
        await db_session.flush()

        response = await client.delete(f"/api/admin/challenges/{challenge.id}")

        assert response.status_code == 409


class TestPrerequisites:
    async def test_a_gated_puzzle_refuses_a_move_and_logs_the_probe(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        from app.models.challenge import RequirementType, UnlockRequirement
        from app.models.play import Submission

        user = await player(db_session, client, sign_in)
        gate = await make_challenge(db_session)
        challenge = await puzzle_challenge(db_session)
        db_session.add(
            UnlockRequirement(
                challenge_id=challenge.id,
                requirement_type=RequirementType.CHALLENGE_SOLVED,
                required_challenge_id=gate.id,
            )
        )
        await db_session.flush()

        response = await move(client, challenge.id, guess="PROXY")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "challenge_locked"
        # Logged: somebody probing a gated challenge is worth seeing in 007.
        assert (
            await db_session.execute(
                select(Submission).where(
                    Submission.user_id == user.id, Submission.challenge_id == challenge.id
                )
            )
        ).scalar_one() is not None
        # And no session was started by a move that never landed.
        assert (
            await db_session.execute(
                select(PuzzleSession).where(PuzzleSession.challenge_id == challenge.id)
            )
        ).scalars().all() == []


class TestHintsComeOutOfTheReward:
    async def test_a_bought_hint_reduces_the_puzzle_xp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        # The puzzle path banks XP through `award_solve`, so it inherits this
        # rather than reimplementing it — which is the whole reason it was
        # extracted.
        await player(db_session, client, sign_in)
        challenge = await puzzle_challenge(db_session)
        hint = Hint(
            challenge_id=challenge.id,
            title="A nudge",
            body="It runs against a subnet.",
            cost=40,
            display_order=0,
        )
        db_session.add(hint)
        await db_session.flush()

        await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")
        body = (await move(client, challenge.id, guess="PROXY")).json()

        assert body["xp_awarded"] == 110  # 150 minus the hint


class TestAntiCheatExemption:
    async def test_identical_puzzle_guesses_are_not_collusion(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        # Two hundred people guessing AUDIT at the same Wordle is the expected
        # shape of play. Without the exemption `shared_wrong_answers` would be
        # unreadable during the game show.
        from app.models.play import Submission

        challenge = await puzzle_challenge(db_session, title="Wordle Day One")
        ordinary = await make_challenge(db_session, title="An Ordinary Room")

        for _ in range(2):
            user = await make_user(db_session, status=UserStatus.ACTIVE)
            for target in (challenge, ordinary):
                db_session.add(
                    Submission(
                        user_id=user.id,
                        challenge_id=target.id,
                        is_correct=False,
                        submitted_value="a-long-identical-wrong-answer",
                    )
                )
        await db_session.flush()

        findings = await signals.compute(db_session, settings)
        # A finding names the challenge by title, so that is what to look for —
        # asserting on the id would pass whether or not the exemption worked.
        flagged = {f.challenge_title for f in findings[signals.SHARED_ANSWER]}

        assert challenge.title not in flagged
        # The ordinary challenge is still watched, so the exemption is narrow
        # rather than a hole in the signal.
        assert ordinary.title in flagged


class TestTheResetGroup:
    async def test_puzzle_play_is_its_own_group_and_spares_the_authored_puzzle(
        self, db_session: AsyncSession
    ) -> None:
        user = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await puzzle_challenge(db_session)
        db_session.add(
            PuzzleSession(
                user_id=user.id,
                challenge_id=challenge.id,
                status=PuzzleStatus.FAILED,
                state={},
                started_at=datetime.now(UTC),
            )
        )
        await db_session.flush()

        counts = await event_reset.counts(db_session)
        assert any(
            row.group == event_reset.ResetGroup.PUZZLE_SESSIONS and row.rows >= 1 for row in counts
        )

        await event_reset.reset(db_session, [event_reset.ResetGroup.PUZZLE_SESSIONS])

        assert (
            await db_session.execute(
                select(PuzzleSession).where(PuzzleSession.challenge_id == challenge.id)
            )
        ).scalars().all() == []
        # The authored puzzle is content, not play — the same distinction as the
        # loot catalogue.
        assert (
            await db_session.execute(
                select(ChallengePuzzle).where(ChallengePuzzle.challenge_id == challenge.id)
            )
        ).scalar_one_or_none() is not None


class TestTwoCompletingMovesRace:
    @pytest.fixture
    async def committed_sessionmaker(self, settings: Settings):
        engine = create_async_engine(settings.async_database_url)
        try:
            yield async_sessionmaker(engine, expire_on_commit=False)
        finally:
            await engine.dispose()

    async def test_only_one_solve_survives(
        self, committed_sessionmaker, settings: Settings
    ) -> None:
        """On real parallel connections, not two coroutines that may not interleave.

        Two moves that both finish the puzzle would both reach `award_solve`.
        The savepoint and the solve constraint decide it, exactly as they do for
        two correct flags.
        """
        from sqlalchemy.exc import IntegrityError

        maker = committed_sessionmaker
        stamp = datetime.now(UTC).timestamp()

        async with maker() as session:
            user = User(
                email=f"race-{stamp}@example.com",
                display_name="Race",
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
                initial_points=100,
                minimum_points=100,
                decay_threshold=10,
            )
            session.add(challenge)
            await session.flush()
            session.add(
                ChallengePuzzle(
                    challenge_id=challenge.id,
                    kind=PuzzleKind.WORDLE,
                    config={
                        "answer": "PROXY",
                        "length": 5,
                        "max_guesses": 6,
                        "extra_words": [],
                        "reveal_on_fail": True,
                    },
                )
            )
            await session.commit()
            user_id, challenge_id, category_id = user.id, challenge.id, category.id

        async def award() -> str:
            async with maker() as session:
                session.add(
                    Solve(
                        user_id=user_id,
                        challenge_id=challenge_id,
                        submitted_at=datetime.now(UTC),
                        xp_awarded=100,
                    )
                )
                try:
                    await session.commit()
                    return "awarded"
                except IntegrityError:
                    await session.rollback()
                    return "rejected"

        try:
            assert sorted(await asyncio.gather(award(), award())) == ["awarded", "rejected"]
        finally:
            async with maker() as session:
                await session.execute(delete(Solve).where(Solve.challenge_id == challenge_id))
                await session.execute(
                    delete(ChallengePuzzle).where(ChallengePuzzle.challenge_id == challenge_id)
                )
                await session.execute(delete(Challenge).where(Challenge.id == challenge_id))
                await session.execute(delete(Category).where(Category.id == category_id))
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
