"""Scoreboard aggregation, and the fairness property it exists to guarantee."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ScoringMode
from app.models.hint import Hint, HintUnlock
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


class TestHintsAtPartyLevel:
    async def test_a_hint_is_charged_to_the_party_once(self, db_session: AsyncSession) -> None:
        """Otherwise a party could buy every hint and still reach the ceiling."""
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        hint = Hint(challenge_id=challenge.id, title="Nudge", body="Look here", cost=50)
        db_session.add(hint)
        await db_session.flush()

        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Hinters")
        second = await make_user(db_session)
        await add_member(db_session, team, second)
        await record_solve(db_session, leader, challenge, team=team)

        for member in (leader, second):
            db_session.add(
                HintUnlock(user_id=member.id, hint_id=hint.id, cost_charged=50, unlocked_at=NOW)
            )
        await db_session.flush()

        # 300 for the solve, 50 for the hint — charged once, not twice.
        assert team_named(await boards(db_session), "Hinters").score == 250

    async def test_the_party_pays_the_lowest_price_any_member_paid(
        self, db_session: AsyncSession
    ) -> None:
        """If one member got it free after solving, the party is not charged."""
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        hint = Hint(challenge_id=challenge.id, title="Nudge", body="Look here", cost=50)
        db_session.add(hint)
        await db_session.flush()

        leader = await make_user(db_session)
        team = await make_team(db_session, leader, name="Mixed Payers")
        second = await make_user(db_session)
        await add_member(db_session, team, second)
        await record_solve(db_session, leader, challenge, team=team)

        db_session.add(
            HintUnlock(user_id=second.id, hint_id=hint.id, cost_charged=50, unlocked_at=NOW)
        )
        db_session.add(
            HintUnlock(user_id=leader.id, hint_id=hint.id, cost_charged=0, unlocked_at=NOW)
        )
        await db_session.flush()

        assert team_named(await boards(db_session), "Mixed Payers").score == 300


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
        challenge = await make_challenge(db_session)
        hint = Hint(challenge_id=challenge.id, title="Costly", body="…", cost=120)
        db_session.add(hint)
        await db_session.flush()
        player = await make_user(db_session, display_name="In The Red")
        db_session.add(
            HintUnlock(user_id=player.id, hint_id=hint.id, cost_charged=120, unlocked_at=NOW)
        )
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


class TestDecayInteraction:
    async def test_a_solve_lowers_everyone_elses_score_too(self, db_session: AsyncSession) -> None:
        """One flag moves every solver's total, which is why deltas are pointless."""
        challenge = await make_challenge(
            db_session, initial_points=500, minimum_points=100, decay_threshold=10
        )
        early = await make_user(db_session, display_name="Early Bird")
        await record_solve(db_session, early, challenge)

        before = next(
            p for p in (await boards(db_session)).players if p.display_name == "Early Bird"
        ).score

        for _ in range(4):
            await record_solve(db_session, await make_user(db_session), challenge)

        after = next(
            p for p in (await boards(db_session)).players if p.display_name == "Early Bird"
        ).score
        assert after < before
