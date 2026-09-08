"""Scoreboard aggregation, and the fairness property it exists to guarantee."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ScoringMode
from app.models.play import ScoreAdjustment
from app.models.team import RemovalReason
from app.models.user import UserRole
from app.services import scoreboard
from tests.factories import add_member, make_challenge, make_team, make_user, record_solve

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


async def boards(db_session: AsyncSession) -> scoreboard.Boards:
    return await scoreboard.compute(db_session, NOW)


def team_named(result: scoreboard.Boards, name: str) -> scoreboard.TeamEntry:
    return next(entry for entry in result.teams if entry.name == name)


class TestTheCeilingProperty:
    """The reason this scoring model was chosen.

    A party of one and a party of eight must have the same attainable maximum.
    Size buys speed and coverage, never a higher score.
    """

    async def test_a_solo_party_and_an_eight_person_party_score_identically(
        self, db_session: AsyncSession
    ) -> None:
        challenges = [
            await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
            for _ in range(8)
        ]

        # One player solves all eight.
        solo = await make_user(db_session)
        solo_team = await make_team(db_session, solo, name="Party Of One")
        for challenge in challenges:
            await record_solve(db_session, solo, challenge, team=solo_team)

        # Eight players split the same eight challenges, one each.
        leader = await make_user(db_session)
        big_team = await make_team(db_session, leader, name="Party Of Eight")
        members = [leader]
        for _ in range(7):
            member = await make_user(db_session)
            await add_member(db_session, big_team, member)
            members.append(member)
        for member, challenge in zip(members, challenges, strict=True):
            await record_solve(db_session, member, challenge, team=big_team)

        result = await boards(db_session)

        assert team_named(result, "Party Of One").score == 800
        assert team_named(result, "Party Of Eight").score == 800

    async def test_duplicated_effort_inside_a_party_adds_nothing(
        self, db_session: AsyncSession
    ) -> None:
        """Two members solving the same thing is wasted effort, and scores as such."""
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Doublers")
        second = await make_user(db_session)
        await add_member(db_session, team, second)

        await record_solve(db_session, leader, challenge, team=team)
        await record_solve(db_session, second, challenge, team=team)

        assert team_named(await boards(db_session), "Doublers").score == 100

    async def test_a_bigger_party_cannot_exceed_the_board_total(
        self, db_session: AsyncSession
    ) -> None:
        challenges = [
            await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=50)
            for _ in range(4)
        ]
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Everyone")
        members = [leader]
        for _ in range(5):
            member = await make_user(db_session)
            await add_member(db_session, team, member)
            members.append(member)
        # Every member solves every challenge.
        for member in members:
            for challenge in challenges:
                await record_solve(db_session, member, challenge, team=team)

        assert team_named(await boards(db_session), "Everyone").score == 200


class TestPartyXp:
    async def test_a_partys_xp_is_the_sum_of_banked_solves(self, db_session: AsyncSession) -> None:
        """Hints are netted out of each solve's banked XP at solve time (spec 015),
        so the party board just sums banked XP over its distinct challenges."""
        a = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        b = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Bankers")
        second = await make_user(db_session)
        await add_member(db_session, team, second)

        # One clean solve (300) and one where the solver had used a 50-cost hint (250).
        await record_solve(db_session, leader, a, team=team, xp=300)
        await record_solve(db_session, second, b, team=team, xp=250)

        assert team_named(await boards(db_session), "Bankers").score == 550

    async def test_a_shared_challenge_counts_the_earliest_banked_xp(
        self, db_session: AsyncSession
    ) -> None:
        """The union counts a shared challenge once, at the earliest party solve."""
        from datetime import timedelta

        shared = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Sharers")
        second = await make_user(db_session)
        await add_member(db_session, team, second)

        early = datetime.now(UTC) - timedelta(minutes=10)
        # The earliest solver used a hint (250); the later one did not (300).
        await record_solve(db_session, leader, shared, team=team, xp=250, submitted_at=early)
        await record_solve(db_session, second, shared, team=team, xp=300)

        assert team_named(await boards(db_session), "Sharers").score == 250


class TestRosterChanges:
    async def test_a_leaver_takes_only_their_unique_contribution(
        self, db_session: AsyncSession
    ) -> None:
        shared = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        theirs = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Departures")
        leaver = await make_user(db_session)
        membership = await add_member(db_session, team, leaver)

        await record_solve(db_session, leader, shared, team=team)
        await record_solve(db_session, leaver, shared, team=team)
        await record_solve(db_session, leaver, theirs, team=team)

        assert team_named(await boards(db_session), "Departures").score == 200

        membership.removed_at = NOW
        membership.removal_reason = RemovalReason.LEFT
        await db_session.flush()

        # The shared challenge stays; the one only they had goes with them.
        assert team_named(await boards(db_session), "Departures").score == 100

    async def test_a_disbanded_party_is_off_the_board(self, db_session: AsyncSession) -> None:
        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Gone")
        team.disbanded_at = NOW
        await db_session.flush()

        assert all(entry.name != "Gone" for entry in (await boards(db_session)).teams)


class TestPlayerBoard:
    async def test_players_are_ranked_by_score(self, db_session: AsyncSession) -> None:
        big = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        small = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        ahead = await make_user(db_session, display_name="Ahead")
        behind = await make_user(db_session, display_name="Behind")
        await record_solve(db_session, ahead, big)
        await record_solve(db_session, behind, small)

        players = (await boards(db_session)).players

        assert players[0].display_name == "Ahead"
        assert players[0].rank == 1
        assert players[1].display_name == "Behind"

    async def test_staff_are_not_ranked(self, db_session: AsyncSession) -> None:
        """Staff accounts exist to run the event, not to win it."""
        challenge = await make_challenge(db_session)
        admin = await make_user(db_session, display_name="Admin", role=UserRole.ADMIN)
        await record_solve(db_session, admin, challenge)

        assert all(p.display_name != "Admin" for p in (await boards(db_session)).players)

    async def test_a_negative_score_is_shown_not_clamped(self, db_session: AsyncSession) -> None:
        """Hints can no longer push a score below zero (spec 015 floors banked XP
        at 0), but a negative admin adjustment still can — and it is shown, not
        clamped."""
        player = await make_user(db_session, display_name="In The Red")
        db_session.add(ScoreAdjustment(user_id=player.id, points=-120, reason="Penalty"))
        await db_session.flush()

        entry = next(
            p for p in (await boards(db_session)).players if p.display_name == "In The Red"
        )
        assert entry.score == -120

    async def test_adjustments_count(self, db_session: AsyncSession) -> None:
        player = await make_user(db_session, display_name="Compensated")
        db_session.add(ScoreAdjustment(user_id=player.id, points=75, reason="Broken challenge"))
        await db_session.flush()

        entry = next(
            p for p in (await boards(db_session)).players if p.display_name == "Compensated"
        )
        assert entry.score == 75


class TestOrdering:
    async def test_a_tie_is_broken_by_who_got_there_first(self, db_session: AsyncSession) -> None:
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=100)
        early = await make_user(db_session, display_name="Zeta Early")
        late = await make_user(db_session, display_name="Alpha Late")

        first = await record_solve(db_session, early, challenge)
        first.submitted_at = NOW - timedelta(hours=2)
        second = await record_solve(db_session, late, challenge)
        second.submitted_at = NOW - timedelta(minutes=5)
        await db_session.flush()

        players = [p.display_name for p in (await boards(db_session)).players]

        # Same score, so the earlier arrival wins — despite the later name
        # sorting first alphabetically.
        assert players.index("Zeta Early") < players.index("Alpha Late")

    async def test_everyone_at_zero_is_ordered_stably_by_name(
        self, db_session: AsyncSession
    ) -> None:
        """Before the first flag lands the board must not shuffle on refresh."""
        await make_user(db_session, display_name="Bravo")
        await make_user(db_session, display_name="Alpha")

        first = [p.display_name for p in (await boards(db_session)).players]
        second = [p.display_name for p in (await boards(db_session)).players]

        assert first == second
        assert first.index("Alpha") < first.index("Bravo")


class TestMonotonicBoard:
    async def test_a_later_solve_does_not_move_an_earlier_solvers_score(
        self, db_session: AsyncSession
    ) -> None:
        """Spec 015: banked XP means the board no longer retroactively re-ranks as
        challenges are solved by others."""
        challenge = await make_challenge(
            db_session, initial_points=500, minimum_points=100, decay_threshold=10
        )
        early = await make_user(db_session, display_name="Early Bird")
        await record_solve(db_session, early, challenge, xp=500)

        before = next(
            p for p in (await boards(db_session)).players if p.display_name == "Early Bird"
        ).score

        for _ in range(4):
            await record_solve(db_session, await make_user(db_session), challenge, xp=200)

        after = next(
            p for p in (await boards(db_session)).players if p.display_name == "Early Bird"
        ).score
        assert after == before
