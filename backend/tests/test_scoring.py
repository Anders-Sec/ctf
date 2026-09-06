"""The decay curve and a player's total (spec 003)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import Challenge, DecayBasis, ScoringMode
from app.models.play import ScoreAdjustment
from app.models.team import RemovalReason, TeamMembership
from app.services.scoring import challenge_value, solve_count, user_score
from tests.factories import add_member, make_challenge, make_team, make_user, record_solve


def curve(
    initial: int = 500,
    minimum: int = 100,
    threshold: int = 40,
    scoring: ScoringMode = ScoringMode.DYNAMIC,
) -> Challenge:
    return Challenge(
        title="t",
        slug="s",
        initial_points=initial,
        minimum_points=minimum,
        decay_threshold=threshold,
        scoring=scoring,
    )


class TestCurve:
    def test_the_first_solver_gets_full_value(self) -> None:
        assert challenge_value(curve(), 0) == 500

    def test_value_decays_as_more_solve(self) -> None:
        values = [challenge_value(curve(), n) for n in (0, 5, 10, 20, 30, 40)]

        assert values == sorted(values, reverse=True)
        assert len(set(values)) > 1

    def test_the_floor_is_reached_exactly_at_the_threshold(self) -> None:
        assert challenge_value(curve(threshold=40), 39) > 100
        assert challenge_value(curve(threshold=40), 40) == 100

    def test_the_floor_holds_beyond_the_threshold(self) -> None:
        """A wildly popular challenge must not go to zero or negative."""
        assert challenge_value(curve(threshold=40), 400) == 100

    def test_decay_is_gentle_early_and_steep_later(self) -> None:
        """Quadratic: early solvers keep most of the value."""
        early_drop = challenge_value(curve(), 0) - challenge_value(curve(), 10)
        late_drop = challenge_value(curve(), 30) - challenge_value(curve(), 40)

        assert late_drop > early_drop

    def test_static_scoring_never_decays(self) -> None:
        static = curve(scoring=ScoringMode.STATIC)

        assert challenge_value(static, 0) == 500
        assert challenge_value(static, 1000) == 500

    def test_a_negative_count_cannot_inflate_the_value(self) -> None:
        assert challenge_value(curve(), -5) == 500

    @pytest.mark.parametrize("count", [0, 1, 7, 39, 40, 41, 100])
    def test_value_always_sits_between_floor_and_ceiling(self, count: int) -> None:
        value = challenge_value(curve(), count)

        assert 100 <= value <= 500

    def test_the_floor_defaults_to_one_hundred(self) -> None:
        assert challenge_value(curve(minimum=100), 999) == 100


class TestSolveCounting:
    async def test_players_basis_counts_distinct_solvers(self, db_session: AsyncSession) -> None:
        challenge = await make_challenge(db_session, decay_basis=DecayBasis.PLAYERS)
        for _ in range(3):
            await record_solve(db_session, await make_user(db_session), challenge)

        assert await solve_count(db_session, challenge) == 3

    async def test_teams_basis_counts_a_whole_party_once(self, db_session: AsyncSession) -> None:
        """Eight teammates solving should move the curve once, not eight times."""
        challenge = await make_challenge(db_session, decay_basis=DecayBasis.TEAMS)
        leader = await make_user(db_session)
        team = await make_team(db_session, leader)
        await record_solve(db_session, leader, challenge, team=team)
        for _ in range(3):
            member = await make_user(db_session)
            await add_member(db_session, team, member)
            await record_solve(db_session, member, challenge, team=team)

        assert await solve_count(db_session, challenge) == 1

    async def test_teams_basis_counts_separate_parties_separately(
        self, db_session: AsyncSession
    ) -> None:
        challenge = await make_challenge(db_session, decay_basis=DecayBasis.TEAMS)
        for _ in range(3):
            leader = await make_user(db_session)
            team = await make_team(db_session, leader)
            await record_solve(db_session, leader, challenge, team=team)

        assert await solve_count(db_session, challenge) == 3

    async def test_a_partyless_solver_still_counts_on_the_team_basis(
        self, db_session: AsyncSession
    ) -> None:
        """Otherwise their solve would be invisible to the curve entirely."""
        challenge = await make_challenge(db_session, decay_basis=DecayBasis.TEAMS)
        leader = await make_user(db_session)
        team = await make_team(db_session, leader)
        await record_solve(db_session, leader, challenge, team=team)
        await record_solve(db_session, await make_user(db_session), challenge, team=None)

        assert await solve_count(db_session, challenge) == 2

    async def test_an_unsolved_challenge_counts_zero(self, db_session: AsyncSession) -> None:
        challenge = await make_challenge(db_session)

        assert await solve_count(db_session, challenge) == 0


class TestPlayerTotal:
    async def test_a_total_is_the_sum_of_solved_challenge_values(
        self, db_session: AsyncSession
    ) -> None:
        player = await make_user(db_session)
        first = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        second = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=200)
        await record_solve(db_session, player, first)
        await record_solve(db_session, player, second)

        assert await user_score(db_session, player.id) == 500

    async def test_an_unsolved_challenge_contributes_nothing(
        self, db_session: AsyncSession
    ) -> None:
        player = await make_user(db_session)
        await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)

        assert await user_score(db_session, player.id) == 0

    async def test_someone_elses_solve_lowers_an_earlier_solvers_total(
        self, db_session: AsyncSession
    ) -> None:
        """The whole point of decay: everyone holds the current value, always."""
        challenge = await make_challenge(db_session, initial_points=500, decay_threshold=10)
        early = await make_user(db_session)
        await record_solve(db_session, early, challenge)
        before = await user_score(db_session, early.id)

        for _ in range(5):
            await record_solve(db_session, await make_user(db_session), challenge)

        assert await user_score(db_session, early.id) < before

    async def test_adjustments_are_added_to_the_total(self, db_session: AsyncSession) -> None:
        player = await make_user(db_session)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        await record_solve(db_session, player, challenge)
        db_session.add(
            ScoreAdjustment(user_id=player.id, points=50, reason="Broken challenge compensation")
        )
        await db_session.flush()

        assert await user_score(db_session, player.id) == 150

    async def test_adjustments_can_be_negative(self, db_session: AsyncSession) -> None:
        player = await make_user(db_session)
        db_session.add(ScoreAdjustment(user_id=player.id, points=-25, reason="Penalty"))
        await db_session.flush()

        assert await user_score(db_session, player.id) == -25

    async def test_a_players_score_survives_leaving_their_party(
        self, db_session: AsyncSession
    ) -> None:
        """Solves belong to the player; the party never held the points."""
        player = await make_user(db_session)
        team = await make_team(db_session, player)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=250)
        await record_solve(db_session, player, challenge, team=team)

        membership = (
            await db_session.execute(
                select(TeamMembership).where(
                    TeamMembership.user_id == player.id, TeamMembership.removed_at.is_(None)
                )
            )
        ).scalar_one()
        membership.removed_at = datetime.now(UTC)
        membership.removal_reason = RemovalReason.LEFT
        await db_session.flush()

        assert await user_score(db_session, player.id) == 250
