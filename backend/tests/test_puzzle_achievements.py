"""The six game-show achievements (spec 044 §8).

Puzzles pay flat XP, so skill is recognised here instead — which makes these
predicates the *only* thing that distinguishes a three-guess Wordle from a
six-guess one. Worth pinning down precisely.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState
from app.models.puzzle import PuzzleKind, PuzzleSession, PuzzleStatus
from app.models.user import UserStatus
from app.services import achievements as engine
from tests.factories import make_challenge, make_puzzle, make_user

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session):
    return await make_user(db_session, status=UserStatus.ACTIVE)


async def puzzle(db_session, kind=PuzzleKind.WORDLE, state=ChallengeState.PUBLISHED):
    challenge = await make_challenge(db_session, state=state, answers=[])
    await make_puzzle(db_session, challenge, kind=kind)
    return challenge


async def session(
    db_session,
    user,
    challenge,
    *,
    status=PuzzleStatus.SOLVED,
    moves=1,
    state: dict | None = None,
):
    row = PuzzleSession(
        user_id=user.id,
        challenge_id=challenge.id,
        status=status,
        state=state or {},
        moves_used=moves,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC) if status != PuzzleStatus.IN_PROGRESS else None,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def check(db_session, code: str, user) -> bool:
    trigger = engine.resolve(code)
    assert trigger is not None, f"{code} has no registered trigger"
    return await trigger.check(db_session, user.id)


class TestPuzzleFirst:
    async def test_a_session_still_in_progress_is_not_a_finished_one(
        self, db_session: AsyncSession
    ) -> None:
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session), status=PuzzleStatus.IN_PROGRESS)

        assert await check(db_session, "puzzle_first", user) is False

    async def test_no_sessions_at_all_earns_nothing(self, db_session: AsyncSession) -> None:
        user = await player(db_session)

        assert await check(db_session, "puzzle_first", user) is False

    async def test_a_solved_puzzle_earns_it(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session))

        assert await check(db_session, "puzzle_first", user) is True

    async def test_a_failed_one_does_not(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session), status=PuzzleStatus.FAILED)

        assert await check(db_session, "puzzle_first", user) is False


class TestWordleSharp:
    async def test_three_guesses_earns_it_and_four_does_not(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        slow = await session(db_session, user, await puzzle(db_session), moves=4)
        assert await check(db_session, "wordle_sharp", user) is False

        await db_session.delete(slow)
        await session(db_session, user, await puzzle(db_session), moves=3)
        assert await check(db_session, "wordle_sharp", user) is True

    async def test_a_quick_crossword_is_not_a_quick_wordle(self, db_session: AsyncSession) -> None:
        # The kind has to be checked, not just the move count.
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session, PuzzleKind.CROSSWORD), moves=1)

        assert await check(db_session, "wordle_sharp", user) is False


class TestConnectionsFlawless:
    async def test_no_mistakes_earns_it(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(
            db_session,
            user,
            await puzzle(db_session, PuzzleKind.CONNECTIONS),
            state={"mistakes": 0, "solved": [1, 2, 3, 4]},
        )

        assert await check(db_session, "connections_flawless", user) is True

    async def test_one_mistake_does_not(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(
            db_session,
            user,
            await puzzle(db_session, PuzzleKind.CONNECTIONS),
            state={"mistakes": 1, "solved": [1, 2, 3, 4]},
        )

        assert await check(db_session, "connections_flawless", user) is False


class TestCrosswordClean:
    async def test_the_first_check_being_right_earns_it(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session, PuzzleKind.CROSSWORD), moves=1)

        assert await check(db_session, "crossword_clean", user) is True

    async def test_a_second_check_does_not(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session, PuzzleKind.CROSSWORD), moves=2)

        assert await check(db_session, "crossword_clean", user) is False


class TestGameShowRegular:
    async def test_it_needs_all_three_kinds(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        for kind in (PuzzleKind.WORDLE, PuzzleKind.CONNECTIONS):
            await session(db_session, user, await puzzle(db_session, kind))
        assert await check(db_session, "game_show_regular", user) is False

        await session(db_session, user, await puzzle(db_session, PuzzleKind.CROSSWORD))
        assert await check(db_session, "game_show_regular", user) is True

    async def test_three_of_the_same_kind_is_not_three_kinds(
        self, db_session: AsyncSession
    ) -> None:
        user = await player(db_session)
        for _ in range(3):
            await session(db_session, user, await puzzle(db_session, PuzzleKind.WORDLE))

        assert await check(db_session, "game_show_regular", user) is False


class TestGameShowSweep:
    async def test_every_published_puzzle_solved_earns_it(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        for kind in PuzzleKind:
            await session(db_session, user, await puzzle(db_session, kind))

        assert await check(db_session, "game_show_sweep", user) is True

    async def test_one_left_unplayed_does_not(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session))
        await puzzle(db_session, PuzzleKind.CONNECTIONS)

        assert await check(db_session, "game_show_sweep", user) is False

    async def test_a_failed_one_blocks_it(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session))
        await session(
            db_session,
            user,
            await puzzle(db_session, PuzzleKind.CONNECTIONS),
            status=PuzzleStatus.FAILED,
        )

        assert await check(db_session, "game_show_sweep", user) is False

    async def test_an_unreleased_puzzle_does_not_hold_it_back(
        self, db_session: AsyncSession
    ) -> None:
        # Counted against what is visible, so it is earnable before the last day
        # releases rather than only in the final hour.
        user = await player(db_session)
        await session(db_session, user, await puzzle(db_session))
        await puzzle(db_session, PuzzleKind.CONNECTIONS, state=ChallengeState.HIDDEN)

        assert await check(db_session, "game_show_sweep", user) is True

    async def test_a_board_with_no_puzzles_earns_nobody_anything(
        self, db_session: AsyncSession
    ) -> None:
        # Otherwise the empty set is a subset of everything and every player
        # holds the sweep before a single puzzle is written.
        user = await player(db_session)

        assert await check(db_session, "game_show_sweep", user) is False


class TestTheyFireOnAMove:
    async def test_a_solving_move_awards_the_first_puzzle_achievement(
        self, client, db_session: AsyncSession, sign_in
    ) -> None:
        # End to end: the trigger listens on SUBMIT, and `apply_move` evaluates
        # on every counted move.
        from sqlalchemy import select

        from app.models.notification import Achievement, AchievementAward

        user = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, user)
        # `puzzle_first` is seeded by migration 0044 — nothing to insert here.
        challenge = await puzzle(db_session)
        await db_session.flush()

        await client.post(
            f"/api/challenges/{challenge.id}/puzzle/move", json={"move": {"guess": "PROXY"}}
        )

        award = (
            await db_session.execute(
                select(AchievementAward)
                .join(Achievement, Achievement.id == AchievementAward.achievement_id)
                .where(AchievementAward.user_id == user.id, Achievement.code == "puzzle_first")
            )
        ).scalar_one_or_none()
        assert award is not None
