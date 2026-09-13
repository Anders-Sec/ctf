"""Any-of unlock requirements, and the secret route into the ladder's zone (spec 033).

The Prompt Injection zone opens by **either** clearing half of the AI/LLM
Security zone **or** catching the System AI handing over level 0's flag. Until
this spec, requirements only ever ANDed.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, RequirementType, UnlockRequirement
from app.services import unlocks
from app.services.ladder import progression
from tests.factories import make_category, make_challenge, make_user, record_solve

pytestmark = pytest.mark.anyio


async def _zone_gate(
    db: AsyncSession, zone, *, trivia, percent: int = 50, group: int | None = 1
) -> None:
    """The two routes in, as an any-of pair."""
    db.add(
        UnlockRequirement(
            category_id=zone.id,
            requirement_type=RequirementType.PERCENT_IN_CATEGORY,
            required_category_id=trivia.id,
            threshold=percent,
            alternative_group=group,
        )
    )
    db.add(
        UnlockRequirement(
            category_id=zone.id,
            requirement_type=RequirementType.AI_LADDER_LEAK,
            alternative_group=group,
        )
    )
    await db.flush()


async def _status(db: AsyncSession, user, zone) -> unlocks.GateStatus:
    """This zone's gate, as the player experiences it."""
    requirements = list(
        (
            await db.execute(
                select(UnlockRequirement).where(UnlockRequirement.category_id == zone.id)
            )
        )
        .scalars()
        .all()
    )
    result = await unlocks.evaluate_groups(
        db, user.id, requirements, datetime.now(UTC), key="category_id"
    )
    return result[zone.id]


class TestAnyOfGrouping:
    async def test_neither_route_leaves_the_zone_shut(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        trivia = await make_category(db_session)
        zone = await make_category(db_session)
        for _ in range(4):
            await make_challenge(db_session, category=trivia, state=ChallengeState.PUBLISHED)
        await _zone_gate(db_session, zone, trivia=trivia)

        assert (await _status(db_session, user, zone)).locked

    async def test_clearing_half_the_trivia_zone_opens_it(self, db_session: AsyncSession) -> None:
        user = await make_user(db_session)
        trivia = await make_category(db_session)
        zone = await make_category(db_session)
        challenges = [
            await make_challenge(db_session, category=trivia, state=ChallengeState.PUBLISHED)
            for _ in range(4)
        ]
        await _zone_gate(db_session, zone, trivia=trivia)

        for challenge in challenges[:2]:
            await record_solve(db_session, user, challenge)

        assert not (await _status(db_session, user, zone)).locked

    async def test_the_leak_alone_opens_it(self, db_session: AsyncSession) -> None:
        """The discovery: the System folds at level 0 and the zone appears, with
        no trivia solved at all."""
        user = await make_user(db_session)
        trivia = await make_category(db_session)
        zone = await make_category(db_session)
        for _ in range(4):
            await make_challenge(db_session, category=trivia, state=ChallengeState.PUBLISHED)
        await _zone_gate(db_session, zone, trivia=trivia)

        await progression.record_leak(db_session, user, 0)

        assert not (await _status(db_session, user, zone)).locked

    async def test_the_leak_route_is_never_shown_to_the_player(
        self, db_session: AsyncSession
    ) -> None:
        """Naming it in a requirement list would hand the trick to everyone
        arriving by the ordinary route."""
        user = await make_user(db_session)
        trivia = await make_category(db_session)
        zone = await make_category(db_session)
        await make_challenge(db_session, category=trivia, state=ChallengeState.PUBLISHED)
        await _zone_gate(db_session, zone, trivia=trivia)

        status = await _status(db_session, user, zone)

        shown = {view.type for view in status.visible_requirements}
        assert RequirementType.PERCENT_IN_CATEGORY in shown
        assert RequirementType.AI_LADDER_LEAK not in shown

    async def test_ungrouped_requirements_still_all_have_to_be_met(
        self, db_session: AsyncSession
    ) -> None:
        """The behaviour every existing requirement row relies on."""
        user = await make_user(db_session)
        zone = await make_category(db_session)
        first = await make_challenge(db_session)
        second = await make_challenge(db_session)
        for challenge in (first, second):
            db_session.add(
                UnlockRequirement(
                    category_id=zone.id,
                    requirement_type=RequirementType.CHALLENGE_SOLVED,
                    required_challenge_id=challenge.id,
                )
            )
        await db_session.flush()

        await record_solve(db_session, user, first)
        assert (await _status(db_session, user, zone)).locked

        await record_solve(db_session, user, second)
        assert not (await _status(db_session, user, zone)).locked

    async def test_a_group_ands_with_an_ungrouped_requirement(
        self, db_session: AsyncSession
    ) -> None:
        """ "A, and either B or C" — the shape a flag on the target could not express."""
        user = await make_user(db_session)
        zone = await make_category(db_session)
        mandatory = await make_challenge(db_session)
        either = await make_challenge(db_session)
        db_session.add(
            UnlockRequirement(
                category_id=zone.id,
                requirement_type=RequirementType.CHALLENGE_SOLVED,
                required_challenge_id=mandatory.id,
            )
        )
        db_session.add(
            UnlockRequirement(
                category_id=zone.id,
                requirement_type=RequirementType.CHALLENGE_SOLVED,
                required_challenge_id=either.id,
                alternative_group=1,
            )
        )
        db_session.add(
            UnlockRequirement(
                category_id=zone.id,
                requirement_type=RequirementType.AI_LADDER_LEAK,
                alternative_group=1,
            )
        )
        await db_session.flush()

        # The group is satisfied, but the mandatory requirement is not.
        await progression.record_leak(db_session, user, 0)
        assert (await _status(db_session, user, zone)).locked

        await record_solve(db_session, user, mandatory)
        assert not (await _status(db_session, user, zone)).locked
