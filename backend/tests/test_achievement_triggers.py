"""The trigger predicates behind the roster (spec 029).

Each is a query over stored history, so each is tested by building that history
and asking. The point of these tests is less "does the SQL run" than "does it
mean what the achievement says" — several of them are easy to write in a way
that is subtly wrong about ordering or about who did what.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assistant import AssistantConversation, AssistantMessage, MessageRole
from app.models.challenge import Difficulty, ScoringMode
from app.models.guardrail import (
    AssistantFinding,
    FindingAction,
    GuardrailLayer,
    Severity,
)
from app.models.play import ScoreAdjustment, Submission
from app.models.user import UserStatus
from app.services import achievements as engine
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session):
    return await make_user(db_session, status=UserStatus.ACTIVE)


async def attempt(db_session, user, challenge, *, correct: bool, value="wrong", at=None):
    db_session.add(
        Submission(
            user_id=user.id,
            challenge_id=challenge.id,
            is_correct=correct,
            submitted_value=value,
            created_at=at or datetime.now(UTC),
        )
    )
    await db_session.flush()


async def at_difficulty(db_session, title: str, difficulty: Difficulty):
    """make_challenge does not take a difficulty, so set it on the row."""
    challenge = await make_challenge(db_session, title=title)
    challenge.difficulty = difficulty
    await db_session.flush()
    return challenge


async def fires(db_session, code: str, user) -> bool:
    return await engine.REGISTRY[code].check(db_session, user.id)


class TestSolveShape:
    async def test_backwards_needs_the_hard_one_first(self, db_session: AsyncSession) -> None:
        """Order is the whole achievement, so a set-based version would be wrong."""
        user = await player(db_session)
        easy = await at_difficulty(db_session, "Trig Easy", Difficulty.VERY_EASY)
        brutal = await at_difficulty(db_session, "Trig Brutal", Difficulty.NEARLY_IMPOSSIBLE)

        start = datetime.now(UTC)
        await record_solve(db_session, user, easy, submitted_at=start)
        await record_solve(db_session, user, brutal, submitted_at=start + timedelta(minutes=1))
        assert await fires(db_session, "backwards", user) is False

        other = await player(db_session)
        await record_solve(db_session, other, brutal, submitted_at=start)
        await record_solve(db_session, other, easy, submitted_at=start + timedelta(minutes=1))
        assert await fires(db_session, "backwards", other) is True

    async def test_clean_hands_counts_only_untainted_solves(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        category = await make_category(db_session, name="Trig Clean")
        for index in range(10):
            challenge = await make_challenge(
                db_session, category=category, title=f"Trig Clean {index}"
            )
            if index == 0:
                # One wrong answer disqualifies that challenge, not the player.
                await attempt(db_session, user, challenge, correct=False)
            await record_solve(db_session, user, challenge)

        assert await fires(db_session, "clean_hands", user) is False

    async def test_first_through_is_about_being_first(self, db_session: AsyncSession) -> None:
        early = await player(db_session)
        late = await player(db_session)
        challenge = await make_challenge(db_session, title="Trig Race")

        await record_solve(db_session, early, challenge)
        await record_solve(db_session, late, challenge)

        assert await fires(db_session, "first_through", early) is True
        # The second solver did the same work and is not first.
        assert await fires(db_session, "first_through", late) is False

    async def test_flawless_ignores_wrong_answers_after_the_clear(
        self, db_session: AsyncSession
    ) -> None:
        """A wrong flag typed after the zone was finished must not retroactively
        spoil it."""
        user = await player(db_session)
        category = await make_category(db_session, name="Trig Flawless")
        challenge = await make_challenge(db_session, category=category, title="Trig Flawless One")
        await record_solve(db_session, user, challenge)
        await attempt(
            db_session,
            user,
            challenge,
            correct=False,
            at=datetime.now(UTC) + timedelta(hours=1),
        )

        assert await fires(db_session, "flawless", user) is True

    async def test_fast_start_declines_to_guess_without_a_start_time(
        self, db_session: AsyncSession, running_event
    ) -> None:
        user = await player(db_session)
        running_event.starts_at = None
        await db_session.flush()

        assert await fires(db_session, "fast_start", user) is False


class TestGettingItWrong:
    async def test_cold_streak_resets_on_a_correct_answer(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        challenge = await make_challenge(db_session, title="Trig Streak")

        for _ in range(9):
            await attempt(db_session, user, challenge, correct=False)
        await attempt(db_session, user, challenge, correct=True)
        for _ in range(9):
            await attempt(db_session, user, challenge, correct=False)

        # Nine, then nine — never ten in a row.
        assert await fires(db_session, "cold_streak", user) is False

    async def test_no_variation_wants_the_same_string(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        challenge = await make_challenge(db_session, title="Trig Same")

        for index in range(5):
            await attempt(db_session, user, challenge, correct=False, value=f"try-{index}")
        assert await fires(db_session, "no_variation", user) is False

        for _ in range(5):
            await attempt(db_session, user, challenge, correct=False, value="identical")
        assert await fires(db_session, "no_variation", user) is True

    async def test_warming_up_stops_at_the_first_solve(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        category = await make_category(db_session, name="Trig Warm")
        for index in range(10):
            challenge = await make_challenge(
                db_session, category=category, title=f"Trig Warm {index}"
            )
            if index == 5:
                await attempt(db_session, user, challenge, correct=True)
            else:
                await attempt(db_session, user, challenge, correct=False)

        assert await fires(db_session, "warming_up", user) is False

    async def test_reading_comprehension_matches_the_title(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        challenge = await make_challenge(db_session, title="Trig Obvious")

        await attempt(db_session, user, challenge, correct=False, value="  trig obvious ")

        assert await fires(db_session, "reading_comprehension", user) is True


class TestTheSystemAI:
    async def _say(self, db_session, user, content: str):
        conversation = (
            await db_session.execute(
                __import__("sqlalchemy")
                .select(AssistantConversation)
                .where(AssistantConversation.user_id == user.id)
            )
        ).scalar_one_or_none()
        if conversation is None:
            conversation = AssistantConversation(user_id=user.id, message_count=0)
            db_session.add(conversation)
            await db_session.flush()
        conversation.message_count += 1
        db_session.add(
            AssistantMessage(
                conversation_id=conversation.id,
                role=MessageRole.USER,
                sequence=conversation.message_count,
                content=content,
            )
        )
        await db_session.flush()

    async def test_manners_and_noted_read_the_message(self, db_session: AsyncSession) -> None:
        polite = await player(db_session)
        rude = await player(db_session)
        await self._say(db_session, polite, "thanks, that helped")
        await self._say(db_session, rude, "you are useless")

        assert await fires(db_session, "manners", polite) is True
        assert await fires(db_session, "noted", polite) is False
        assert await fires(db_session, "noted", rude) is True

    async def test_guardrail_layers_are_distinguished(self, db_session: AsyncSession) -> None:
        """The two layers are independent by design (spec 011), so the two
        achievements must not collapse into one."""
        user = await player(db_session)
        db_session.add(
            AssistantFinding(
                user_id=user.id,
                layer=GuardrailLayer.INTEGRITY,
                rule="flag_request",
                severity=Severity.MEDIUM,
                action=FindingAction.DEFLECTED,
                detail={},
            )
        )
        await db_session.flush()

        assert await fires(db_session, "nice_try", user) is True
        assert await fires(db_session, "also_nice_try", user) is False
        assert await fires(db_session, "thorough", user) is False

        db_session.add(
            AssistantFinding(
                user_id=user.id,
                layer=GuardrailLayer.SAFETY,
                rule="exploit_request",
                severity=Severity.HIGH,
                action=FindingAction.DEFLECTED,
                detail={},
            )
        )
        await db_session.flush()

        assert await fires(db_session, "thorough", user) is True

    async def test_the_essay_needs_a_long_one(self, db_session: AsyncSession) -> None:
        user = await player(db_session)
        await self._say(db_session, user, "x" * 500)
        assert await fires(db_session, "the_essay", user) is False

        await self._say(db_session, user, "y" * 1001)
        assert await fires(db_session, "the_essay", user) is True


class TestScoreAdjustments:
    async def test_a_penalty_is_distinguished_from_any_adjustment(
        self, db_session: AsyncSession
    ) -> None:
        credited = await player(db_session)
        penalised = await player(db_session)
        db_session.add(ScoreAdjustment(user_id=credited.id, points=100, reason="Broken challenge."))
        db_session.add(ScoreAdjustment(user_id=penalised.id, points=-50, reason="Cheating."))
        await db_session.flush()

        assert await fires(db_session, "manual_intervention", credited) is True
        assert await fires(db_session, "that_is_a_penalty", credited) is False
        assert await fires(db_session, "that_is_a_penalty", penalised) is True


class TestCoverage:
    async def test_every_trigger_answers_for_a_player_with_no_history(
        self, db_session: AsyncSession
    ) -> None:
        """A brand-new player must not make any trigger raise. This is the cheap
        check that catches a query with a bad join or a null it did not expect."""
        user = await player(db_session)

        for code, registered in engine.REGISTRY.items():
            result = await registered.check(db_session, user.id)
            assert result in (True, False), f"{code} returned {result!r}"

    async def test_a_fresh_player_earns_almost_nothing(self, db_session: AsyncSession) -> None:
        user = await player(db_session)

        earned = {
            code
            for code, registered in engine.REGISTRY.items()
            if await registered.check(db_session, user.id)
        }

        # "Every ability at 12+" and friends must not be vacuously true, and
        # neither must anything phrased as a negative.
        assert earned == set(), f"unexpectedly earned: {sorted(earned)}"

    async def test_solving_one_challenge_earns_the_opening_set(
        self, db_session: AsyncSession
    ) -> None:
        user = await player(db_session)
        challenge = await make_challenge(
            db_session, title="Trig First", scoring=ScoringMode.STATIC, initial_points=50
        )
        await record_solve(db_session, user, challenge)

        earned = {
            code
            for code, registered in engine.REGISTRY.items()
            if await registered.check(db_session, user.id)
        }

        assert "first_blood" in earned
        assert "first_through" in earned
        # Volume and depth achievements must not fire off a single solve.
        assert "centurion" not in earned
        assert "maximum" not in earned
