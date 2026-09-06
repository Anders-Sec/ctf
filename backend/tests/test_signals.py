"""Anti-cheat signals (spec 007).

Every signal is tested twice: once on a case that should fire, and once on its
innocent twin — the same shape of data with the participants in one party, or
the value typed by twenty people rather than two. A signal that cannot stay
quiet is worse than no signal, because a console crying wolf gets ignored by
hour two.
"""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models.event import EventConfig
from app.models.play import Submission
from app.models.user import UserRole, UserStatus
from app.services import signals
from tests.factories import add_member, make_challenge, make_team, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


async def attempt(
    db_session, user, challenge, value: str, *, correct: bool = False, at=None, team=None, ip=None
) -> Submission:
    row = Submission(
        user_id=user.id,
        challenge_id=challenge.id,
        team_id_at_submit=team.id if team else None,
        is_correct=correct,
        submitted_value=value,
        ip=ip,
    )
    db_session.add(row)
    await db_session.flush()
    if at is not None:
        row.created_at = at
        await db_session.flush()
    return row


async def find(db_session, settings: Settings, signal_type: str):
    results = await signals.compute(db_session, settings, only=signal_type)
    return results[signal_type]


async def two_players_in_separate_parties(db_session):
    first = await make_user(db_session, status=UserStatus.ACTIVE)
    second = await make_user(db_session, status=UserStatus.ACTIVE)
    await make_team(db_session, first)
    await make_team(db_session, second)
    return first, second


class TestSharedWrongAnswer:
    async def test_the_same_unusual_string_from_two_parties_fires(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Sharing an answer usually means sharing the typo too."""
        first, second = await two_players_in_separate_parties(db_session)
        challenge = await make_challenge(db_session)
        await attempt(db_session, first, challenge, "flag{tpyo-in-both}")
        await attempt(db_session, second, challenge, "flag{tpyo-in-both}")

        rows = await find(db_session, settings, signals.SHARED_ANSWER)

        assert len(rows) == 1
        assert rows[0].evidence["value"] == "flag{tpyo-in-both}"

    async def test_the_same_string_inside_one_party_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Working together is what a party is for."""
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader)
        member = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, member)
        challenge = await make_challenge(db_session)

        await attempt(db_session, leader, challenge, "flag{same-guess-here}", team=team)
        await attempt(db_session, member, challenge, "flag{same-guess-here}", team=team)

        assert await find(db_session, settings, signals.SHARED_ANSWER) == []

    async def test_a_popular_wrong_guess_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Twenty people typing the same thing is a guess, not a conspiracy."""
        challenge = await make_challenge(db_session)
        for _ in range(20):
            player = await make_user(db_session, status=UserStatus.ACTIVE)
            await attempt(db_session, player, challenge, "flag{obvious-guess}")

        assert await find(db_session, settings, signals.SHARED_ANSWER) == []

    async def test_a_short_string_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        challenge = await make_challenge(db_session)
        for _ in range(2):
            player = await make_user(db_session, status=UserStatus.ACTIVE)
            await attempt(db_session, player, challenge, "abc")

        assert await find(db_session, settings, signals.SHARED_ANSWER) == []

    async def test_an_obvious_word_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        challenge = await make_challenge(db_session)
        for _ in range(2):
            player = await make_user(db_session, status=UserStatus.ACTIVE)
            await attempt(db_session, player, challenge, "password")

        assert await find(db_session, settings, signals.SHARED_ANSWER) == []

    async def test_a_correct_answer_is_not_a_signal(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Everyone who solves submits the same right string. That is solving."""
        challenge = await make_challenge(db_session)
        for _ in range(2):
            player = await make_user(db_session, status=UserStatus.ACTIVE)
            await attempt(db_session, player, challenge, "flag{the-real-answer}", correct=True)

        assert await find(db_session, settings, signals.SHARED_ANSWER) == []

    async def test_a_finding_carries_its_innocent_explanation(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """These are colleagues, and the console must say so."""
        first, second = await two_players_in_separate_parties(db_session)
        challenge = await make_challenge(db_session)
        await attempt(db_session, first, challenge, "flag{shared-string}")
        await attempt(db_session, second, challenge, "flag{shared-string}")

        rows = await find(db_session, settings, signals.SHARED_ANSWER)

        assert rows[0].innocent_explanation


class TestCloseBehindSolve:
    async def test_a_first_try_solve_just_behind_another_party_fires(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        challenge = await make_challenge(db_session)
        first = await make_user(db_session, status=UserStatus.ACTIVE)
        first_team = await make_team(db_session, first)
        second = await make_user(db_session, status=UserStatus.ACTIVE)
        second_team = await make_team(db_session, second)

        a = await record_solve(db_session, first, challenge, team=first_team)
        a.submitted_at = NOW
        b = await record_solve(db_session, second, challenge, team=second_team)
        b.submitted_at = NOW + timedelta(seconds=30)
        await db_session.flush()

        rows = await find(db_session, settings, signals.CLOSE_SOLVE)

        assert len(rows) == 1
        assert rows[0].evidence["seconds_apart"] == 30

    async def test_a_solve_after_wrong_attempts_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Someone who worked at it and got there is just a solver."""
        challenge = await make_challenge(db_session)
        first = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_team(db_session, first)
        second = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_team(db_session, second)

        a = await record_solve(db_session, first, challenge)
        a.submitted_at = NOW
        await attempt(db_session, second, challenge, "an earlier wrong guess")
        b = await record_solve(db_session, second, challenge)
        b.submitted_at = NOW + timedelta(seconds=30)
        await db_session.flush()

        assert await find(db_session, settings, signals.CLOSE_SOLVE) == []

    async def test_solves_inside_one_party_stay_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        challenge = await make_challenge(db_session)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader)
        member = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, member)

        a = await record_solve(db_session, leader, challenge, team=team)
        a.submitted_at = NOW
        b = await record_solve(db_session, member, challenge, team=team)
        b.submitted_at = NOW + timedelta(seconds=20)
        await db_session.flush()

        assert await find(db_session, settings, signals.CLOSE_SOLVE) == []

    async def test_a_distant_solve_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        challenge = await make_challenge(db_session)
        first, second = await two_players_in_separate_parties(db_session)

        a = await record_solve(db_session, first, challenge)
        a.submitted_at = NOW
        b = await record_solve(db_session, second, challenge)
        b.submitted_at = NOW + timedelta(hours=3)
        await db_session.flush()

        assert await find(db_session, settings, signals.CLOSE_SOLVE) == []

    async def test_a_stampede_is_visible_as_a_stampede(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """A wave unlocking is not a conspiracy, and the count says so."""
        challenge = await make_challenge(db_session)
        for index in range(5):
            player = await make_user(db_session, status=UserStatus.ACTIVE)
            await make_team(db_session, player)
            solve = await record_solve(db_session, player, challenge)
            solve.submitted_at = NOW + timedelta(seconds=index * 10)
        await db_session.flush()

        rows = await find(db_session, settings, signals.CLOSE_SOLVE)

        assert rows
        assert max(row.evidence["solves_in_window"] for row in rows) >= 5


class TestFirstTrySolver:
    async def test_a_perfect_record_over_many_solves_fires(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        for _ in range(6):
            await record_solve(db_session, player, await make_challenge(db_session))

        rows = await find(db_session, settings, signals.FIRST_TRY)

        assert len(rows) == 1
        assert rows[0].evidence["ratio"] == 1.0

    async def test_too_few_solves_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        """Three lucky first tries is a Tuesday."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        for _ in range(3):
            await record_solve(db_session, player, await make_challenge(db_session))

        assert await find(db_session, settings, signals.FIRST_TRY) == []

    async def test_someone_who_struggles_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        for _ in range(6):
            challenge = await make_challenge(db_session)
            await attempt(db_session, player, challenge, "a wrong guess here")
            await record_solve(db_session, player, challenge)

        assert await find(db_session, settings, signals.FIRST_TRY) == []


class TestLateRecruitment:
    async def test_a_late_joiner_bringing_solves_fires(
        self, db_session: AsyncSession, settings: Settings, running_event: EventConfig
    ) -> None:
        running_event.ends_at = datetime.now(UTC) + timedelta(minutes=30)
        await db_session.flush()

        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader)
        recruit = await make_user(db_session, status=UserStatus.ACTIVE)
        for _ in range(6):
            await record_solve(db_session, recruit, await make_challenge(db_session))
        await add_member(db_session, team, recruit)

        rows = await find(db_session, settings, signals.LATE_RECRUIT)

        assert len(rows) == 1
        assert rows[0].evidence["solves_brought"] == 6

    async def test_a_late_joiner_with_nothing_to_bring_stays_quiet(
        self, db_session: AsyncSession, settings: Settings, running_event: EventConfig
    ) -> None:
        running_event.ends_at = datetime.now(UTC) + timedelta(minutes=30)
        await db_session.flush()

        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader)
        await add_member(db_session, team, await make_user(db_session, status=UserStatus.ACTIVE))

        assert await find(db_session, settings, signals.LATE_RECRUIT) == []

    async def test_an_unscheduled_event_produces_nothing(
        self, db_session: AsyncSession, settings: Settings, running_event: EventConfig
    ) -> None:
        running_event.ends_at = None
        await db_session.flush()

        assert await find(db_session, settings, signals.LATE_RECRUIT) == []


class TestCadence:
    async def test_machine_regular_timing_fires(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session)
        for index in range(15):
            await attempt(
                db_session,
                player,
                challenge,
                f"guess-{index}",
                at=NOW + timedelta(seconds=index * 6),
            )

        rows = await find(db_session, settings, signals.CADENCE)

        assert len(rows) == 1
        assert rows[0].evidence["gap_stdev_seconds"] == 0.0

    async def test_human_irregular_timing_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session)
        offsets = [0, 7, 19, 46, 51, 90, 143, 150, 220, 260, 340, 380, 500, 640, 700]
        for index, offset in enumerate(offsets):
            await attempt(
                db_session, player, challenge, f"guess-{index}", at=NOW + timedelta(seconds=offset)
            )

        assert await find(db_session, settings, signals.CADENCE) == []

    async def test_too_few_attempts_stays_quiet(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session)
        for index in range(5):
            await attempt(
                db_session, player, challenge, f"g-{index}", at=NOW + timedelta(seconds=index * 6)
            )

        assert await find(db_session, settings, signals.CADENCE) == []


class TestSharedAddress:
    async def test_it_is_off_by_default(self, db_session: AsyncSession, settings: Settings) -> None:
        """A shared corporate NAT puts the whole field behind one address."""
        challenge = await make_challenge(db_session)
        for _ in range(2):
            player = await make_user(db_session, status=UserStatus.ACTIVE)
            await attempt(db_session, player, challenge, "some guess", ip="10.0.0.1")

        assert await find(db_session, settings, signals.SHARED_IP) == []

    async def test_it_reports_when_switched_on(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        enabled = settings.model_copy(update={"signal_shared_ip_enabled": True})
        challenge = await make_challenge(db_session)
        for _ in range(2):
            player = await make_user(db_session, status=UserStatus.ACTIVE)
            await attempt(db_session, player, challenge, "some guess", ip="10.0.0.9")

        rows = (await signals.compute(db_session, enabled, only=signals.SHARED_IP))[
            signals.SHARED_IP
        ]

        assert rows
        # And says so, so nobody reads it as damning.
        assert "corporate" in rows[0].innocent_explanation.lower()


class TestExclusions:
    async def test_staff_never_appear(self, db_session: AsyncSession, settings: Settings) -> None:
        """They are not competing."""
        challenge = await make_challenge(db_session)
        for role in (UserRole.ADMIN, UserRole.ORGANIZER):
            staff = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
            await attempt(db_session, staff, challenge, "flag{staff-guessing}")

        assert await find(db_session, settings, signals.SHARED_ANSWER) == []

    async def test_everything_is_empty_on_an_empty_database(
        self, db_session: AsyncSession, settings: Settings
    ) -> None:
        results = await signals.compute(db_session, settings)

        assert all(findings == [] for findings in results.values())


class TestDismissal:
    async def test_a_dismissal_hides_exactly_its_own_finding(
        self, client: AsyncClient, db_session: AsyncSession, settings: Settings, sign_in
    ) -> None:
        first, second = await two_players_in_separate_parties(db_session)
        one = await make_challenge(db_session)
        two = await make_challenge(db_session)
        await attempt(db_session, first, one, "flag{first-shared-value}")
        await attempt(db_session, second, one, "flag{first-shared-value}")
        await attempt(db_session, first, two, "flag{second-shared-value}")
        await attempt(db_session, second, two, "flag{second-shared-value}")

        before = await find(db_session, settings, signals.SHARED_ANSWER)
        assert len(before) == 2

        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)
        response = await client.post(
            "/api/admin/signals/dismiss",
            json={
                "signal_type": signals.SHARED_ANSWER,
                "subject_key": before[0].subject_key,
                "note": "They sit together",
            },
        )

        assert response.status_code == 200
        after = await find(db_session, settings, signals.SHARED_ANSWER)
        assert len(after) == 1
        assert after[0].subject_key == before[1].subject_key

    async def test_dismissing_twice_is_harmless(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)
        payload = {"signal_type": "x", "subject_key": "y", "note": "fine"}

        assert (await client.post("/api/admin/signals/dismiss", json=payload)).status_code == 200
        assert (await client.post("/api/admin/signals/dismiss", json=payload)).status_code == 200


class TestAccess:
    async def test_a_player_cannot_see_signals(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Telling someone they were flagged turns a coincidence into an accusation."""
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, player)

        assert (await client.get("/api/admin/signals")).status_code == 403

    async def test_an_organizer_can(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        response = await client.get("/api/admin/signals")

        assert response.status_code == 200
        assert set(response.json()["counts"]) >= {signals.SHARED_ANSWER, signals.CLOSE_SOLVE}

    async def test_an_anonymous_visitor_cannot(self, client: AsyncClient) -> None:
        assert (await client.get("/api/admin/signals")).status_code == 401


class TestTimeline:
    async def test_it_orders_everything_a_player_did(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, player, name="Timeline Party")
        challenge = await make_challenge(db_session)
        await attempt(db_session, player, challenge, "a wrong guess", at=NOW)
        await attempt(
            db_session,
            player,
            challenge,
            "the right one",
            correct=True,
            at=NOW + timedelta(minutes=1),
        )
        await sign_in(client, organizer)

        events = (await client.get(f"/api/admin/players/{player.id}/timeline")).json()["events"]

        kinds = [event["kind"] for event in events]
        assert "attempt" in kinds and "solve" in kinds and "party_join" in kinds
        assert events == sorted(events, key=lambda event: event["at"])
        assert team.id is not None

    async def test_a_new_player_has_an_empty_timeline(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        response = await client.get(f"/api/admin/players/{player.id}/timeline")

        assert response.status_code == 200
        assert response.json()["events"] == []

    async def test_an_unknown_player_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)

        assert (await client.get(f"/api/admin/players/{uuid.uuid4()}/timeline")).status_code == 404
