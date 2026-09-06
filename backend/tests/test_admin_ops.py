"""Score overrides, broken-challenge reports and the dashboard (spec 006)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.challenge import ChallengeState, PreReleaseState, ScoringMode
from app.models.play import ScoreAdjustment, Submission
from app.models.report import ChallengeReport
from app.models.user import UserRole, UserStatus
from app.services import scoreboard
from app.services.scoring import user_score
from tests.factories import add_member, make_challenge, make_team, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


async def signed_in(db_session, client, sign_in, role: UserRole = UserRole.ADMIN):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


async def boards(db_session):
    return await scoreboard.compute(db_session, NOW)


class TestAdjustmentTargets:
    async def test_a_player_can_be_adjusted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        response = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 75, "reason": "Broken challenge"},
        )

        assert response.status_code == 201
        assert await user_score(db_session, player.id) == 75

    async def test_a_party_adjustment_moves_the_party_and_nobody_else(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The whole reason it is not attached to a person."""
        await signed_in(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Compensated")
        member = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, member)

        await client.post(
            "/api/admin/adjustments",
            json={"team_id": str(team.id), "points": 100, "reason": "Broken challenge"},
        )

        result = await boards(db_session)
        party = next(t for t in result.teams if t.name == "Compensated")
        assert party.score == 100
        # Neither member gained a personal point — including the leader.
        assert await user_score(db_session, leader.id) == 0
        assert await user_score(db_session, member.id) == 0

    async def test_it_counts_once_not_once_per_member(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Once")
        for _ in range(4):
            await add_member(
                db_session, team, await make_user(db_session, status=UserStatus.ACTIVE)
            )

        await client.post(
            "/api/admin/adjustments",
            json={"team_id": str(team.id), "points": 100, "reason": "One award"},
        )

        party = next(t for t in (await boards(db_session)).teams if t.name == "Once")
        assert party.score == 100

    async def test_it_survives_a_leadership_transfer_and_the_leader_leaving(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Attaching it to a person would have walked it out of the party."""
        from app.models.team import MembershipRole, RemovalReason, TeamMembership

        await signed_in(db_session, client, sign_in)
        leader = await make_user(db_session, status=UserStatus.ACTIVE)
        team = await make_team(db_session, leader, name="Persistent")
        successor = await make_user(db_session, status=UserStatus.ACTIVE)
        await add_member(db_session, team, successor)

        await client.post(
            "/api/admin/adjustments",
            json={"team_id": str(team.id), "points": 100, "reason": "Compensation"},
        )

        # Hand over, then the original leader walks.
        team.leader_user_id = successor.id
        membership = (
            await db_session.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team.id,
                    TeamMembership.user_id == leader.id,
                    TeamMembership.removed_at.is_(None),
                )
            )
        ).scalar_one()
        membership.removed_at = datetime.now(UTC)
        membership.removal_reason = RemovalReason.LEFT
        successor_row = (
            await db_session.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == team.id, TeamMembership.user_id == successor.id
                )
            )
        ).scalar_one()
        successor_row.role = MembershipRole.LEADER
        await db_session.flush()

        party = next(t for t in (await boards(db_session)).teams if t.name == "Persistent")
        assert party.score == 100

    async def test_targeting_both_a_player_and_a_party_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session)
        team = await make_team(db_session, await make_user(db_session))

        response = await client.post(
            "/api/admin/adjustments",
            json={
                "user_id": str(player.id),
                "team_id": str(team.id),
                "points": 10,
                "reason": "Confused",
            },
        )

        assert response.status_code == 422

    async def test_targeting_neither_is_rejected(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)

        response = await client.post(
            "/api/admin/adjustments", json={"points": 10, "reason": "Nobody"}
        )

        assert response.status_code == 422

    async def test_the_database_refuses_a_two_target_row(self, db_session: AsyncSession) -> None:
        """Enforced below the API too, not only in the request model."""
        player = await make_user(db_session)
        team = await make_team(db_session, await make_user(db_session))
        db_session.add(ScoreAdjustment(user_id=player.id, team_id=team.id, points=1, reason="Bad"))

        with pytest.raises(IntegrityError):
            await db_session.flush()

    async def test_a_reason_is_required(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session)

        response = await client.post(
            "/api/admin/adjustments", json={"user_id": str(player.id), "points": 50}
        )

        assert response.status_code == 422

    async def test_an_organizer_cannot_adjust_scores(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        player = await make_user(db_session)

        response = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 50, "reason": "Nope"},
        )

        assert response.status_code == 403

    async def test_a_self_adjustment_is_flagged_in_the_audit_log(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Allowed, but it should never be quiet."""
        admin = await signed_in(db_session, client, sign_in)

        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(admin.id), "points": 500, "reason": "Testing"},
        )

        entry = (
            await db_session.execute(select(AuditLog).where(AuditLog.action == "score.adjust"))
        ).scalar_one()
        assert entry.meta["self_adjustment"] is True


class TestReversal:
    async def test_a_reversal_cancels_the_original_exactly(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        created = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 200, "reason": "Mistake"},
        )

        response = await client.post(
            f"/api/admin/adjustments/{created.json()['id']}/reverse",
            json={"reason": "Wrong player"},
        )

        assert response.status_code == 200
        assert await user_score(db_session, player.id) == 0

    async def test_both_rows_survive(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Deleting would erase the record of a decision people may argue about."""
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session)
        created = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 200, "reason": "Mistake"},
        )
        await client.post(
            f"/api/admin/adjustments/{created.json()['id']}/reverse",
            json={"reason": "Wrong player"},
        )

        rows = (
            (
                await db_session.execute(
                    select(ScoreAdjustment).where(ScoreAdjustment.user_id == player.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 2

    async def test_a_reversal_cannot_be_reversed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session)
        created = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 50, "reason": "First"},
        )
        reversal = await client.post(
            f"/api/admin/adjustments/{created.json()['id']}/reverse",
            json={"reason": "Undo"},
        )

        again = await client.post(
            f"/api/admin/adjustments/{reversal.json()['id']}/reverse",
            json={"reason": "Undo the undo"},
        )

        assert again.status_code == 409
        assert again.json()["error"]["code"] == "adjustment_is_reversal"

    async def test_reversing_twice_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session)
        created = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 50, "reason": "First"},
        )
        payload = {"reason": "Undo"}

        await client.post(f"/api/admin/adjustments/{created.json()['id']}/reverse", json=payload)
        second = await client.post(
            f"/api/admin/adjustments/{created.json()['id']}/reverse", json=payload
        )

        assert second.status_code == 409
        assert second.json()["error"]["code"] == "already_reversed"

    async def test_there_is_no_delete_endpoint(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session)
        created = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 50, "reason": "First"},
        )

        response = await client.delete(f"/api/admin/adjustments/{created.json()['id']}")

        assert response.status_code in (404, 405)

    async def test_the_listing_marks_a_reversed_entry(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Subject")
        created = await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 50, "reason": "First"},
        )
        await client.post(
            f"/api/admin/adjustments/{created.json()['id']}/reverse", json={"reason": "Undo"}
        )

        rows = (await client.get("/api/admin/adjustments")).json()
        original = next(r for r in rows if r["id"] == created.json()["id"])

        assert original["reversed_by_id"] is not None
        # Names are resolved so the console is not a wall of uuids.
        assert original["subject_name"] == "Subject"


class TestReports:
    async def test_a_player_can_report_a_challenge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.PLAYER)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/challenges/{challenge.id}/report",
            json={"message": "The download is corrupt."},
        )

        assert response.status_code == 201
        assert response.json()["status"] == "open"

    async def test_reporting_twice_is_a_no_op(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A frustrated player clicking twice is not two problems."""
        user = await signed_in(db_session, client, sign_in, role=UserRole.PLAYER)
        challenge = await make_challenge(db_session)
        payload = {"message": "Still broken."}

        first = await client.post(f"/api/challenges/{challenge.id}/report", json=payload)
        second = await client.post(f"/api/challenges/{challenge.id}/report", json=payload)

        assert first.json()["id"] == second.json()["id"]
        rows = (
            (
                await db_session.execute(
                    select(ChallengeReport).where(ChallengeReport.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_a_hidden_challenge_can_still_be_reported(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """They may have been mid-attempt when it was pulled."""
        await signed_in(db_session, client, sign_in, role=UserRole.PLAYER)
        challenge = await make_challenge(db_session, state=ChallengeState.HIDDEN)

        response = await client.post(
            f"/api/challenges/{challenge.id}/report", json={"message": "It vanished."}
        )

        assert response.status_code == 201

    async def test_staff_can_read_the_queue_and_admins_triage_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        reporter = await make_user(db_session, status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, title="Suspect")
        db_session.add(
            ChallengeReport(challenge_id=challenge.id, user_id=reporter.id, message="Broken")
        )
        await db_session.flush()

        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        listed = await client.get("/api/admin/reports?status=open")
        assert listed.status_code == 200
        assert listed.json()[0]["challenge_title"] == "Suspect"

        triage = await client.post(
            f"/api/admin/reports/{listed.json()[0]['id']}/status",
            json={"status": "resolved", "note": "Answer rule fixed"},
        )
        # Organizers read; only admins change things.
        assert triage.status_code == 403

        await signed_in(db_session, client, sign_in, role=UserRole.ADMIN)
        assert (
            await client.post(
                f"/api/admin/reports/{listed.json()[0]['id']}/status",
                json={"status": "resolved", "note": "Answer rule fixed"},
            )
        ).status_code == 200

    async def test_resolving_frees_the_player_to_report_again(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The unique index only covers open reports."""
        admin = await signed_in(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        first = await client.post(
            f"/api/challenges/{challenge.id}/report", json={"message": "Broken"}
        )
        await client.post(
            f"/api/admin/reports/{first.json()['id']}/status",
            json={"status": "resolved", "note": "Fixed"},
        )

        second = await client.post(
            f"/api/challenges/{challenge.id}/report", json={"message": "Broken again"}
        )

        assert second.status_code == 201
        assert second.json()["id"] != first.json()["id"]
        assert admin.id is not None


class TestChallengeHealth:
    async def test_many_attempts_and_no_solves_is_flagged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Eighty attempts and no solves means the answer rule is wrong."""
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        challenge = await make_challenge(db_session, title="Impossible")
        for _ in range(20):
            db_session.add(
                Submission(
                    user_id=(await make_user(db_session)).id,
                    challenge_id=challenge.id,
                    is_correct=False,
                    submitted_value="guess",
                )
            )
        await db_session.flush()

        rows = (await client.get("/api/admin/challenge-health")).json()
        row = next(r for r in rows if r["title"] == "Impossible")

        assert row["suspected_broken"] is True

    async def test_an_untouched_challenge_is_not_flagged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Reported as untouched, not as a 0% success rate or a divide by zero."""
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        await make_challenge(db_session, title="Nobody Tried")

        rows = (await client.get("/api/admin/challenge-health")).json()
        row = next(r for r in rows if r["title"] == "Nobody Tried")

        assert row["attempt_count"] == 0
        assert row["suspected_broken"] is False

    async def test_a_few_wrong_guesses_do_not_flag_a_hard_challenge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        challenge = await make_challenge(db_session, title="Merely Hard")
        for _ in range(3):
            db_session.add(
                Submission(
                    user_id=(await make_user(db_session)).id,
                    challenge_id=challenge.id,
                    is_correct=False,
                    submitted_value="guess",
                )
            )
        await db_session.flush()

        rows = (await client.get("/api/admin/challenge-health")).json()
        row = next(r for r in rows if r["title"] == "Merely Hard")

        assert row["suspected_broken"] is False


class TestDashboard:
    async def test_staff_can_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)

        response = await client.get("/api/admin/dashboard")

        assert response.status_code == 200
        assert {"event", "pulse", "attention", "containers"} <= set(response.json())

    async def test_a_player_cannot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.PLAYER)

        assert (await client.get("/api/admin/dashboard")).status_code == 403

    async def test_it_flags_a_published_challenge_with_no_answers(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Unsolvable by construction, and nobody notices until players complain."""
        from app.models.challenge import ChallengeAnswer

        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        challenge = await make_challenge(db_session, title="Answerless")
        await db_session.execute(
            ChallengeAnswer.__table__.delete().where(ChallengeAnswer.challenge_id == challenge.id)
        )
        await db_session.flush()

        attention = (await client.get("/api/admin/dashboard")).json()["attention"]

        assert any(c["title"] == "Answerless" for c in attention["published_without_answers"])

    async def test_it_counts_pending_approvals_and_open_reports(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        challenge = await make_challenge(db_session)
        db_session.add(
            ChallengeReport(
                challenge_id=challenge.id,
                user_id=(await make_user(db_session)).id,
                message="Broken",
            )
        )
        await db_session.flush()

        attention = (await client.get("/api/admin/dashboard")).json()["attention"]

        assert attention["pending_approvals"] >= 1
        assert attention["open_reports"] >= 1

    async def test_recent_solves_appear_in_the_pulse(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC)
        await record_solve(db_session, await make_user(db_session), challenge)

        pulse = (await client.get("/api/admin/dashboard")).json()["pulse"]

        assert pulse["solves_15m"] >= 1

    async def test_the_container_panel_is_an_honest_placeholder(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)

        containers = (await client.get("/api/admin/dashboard")).json()["containers"]

        assert containers["available"] is False


class TestBulkRelease:
    async def test_a_wave_can_be_scheduled_in_one_action(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        first = await make_challenge(db_session, state=ChallengeState.PUBLISHED)
        second = await make_challenge(db_session, state=ChallengeState.PUBLISHED)
        when = datetime.now(UTC) + timedelta(hours=6)

        response = await client.post(
            "/api/admin/challenges/release",
            json={
                "challenge_ids": [str(first.id), str(second.id)],
                "release_at": when.isoformat(),
                "pre_release_state": "locked",
            },
        )

        assert response.status_code == 200
        for challenge in (first, second):
            await db_session.refresh(challenge)
            assert challenge.release_at is not None
            assert challenge.pre_release_state == PreReleaseState.LOCKED

    async def test_an_unknown_id_fails_the_whole_batch(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await signed_in(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        response = await client.post(
            "/api/admin/challenges/release",
            json={"challenge_ids": [str(challenge.id), str(uuid.uuid4())]},
        )

        assert response.status_code == 404

    async def test_scheduling_is_audit_logged_per_challenge(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        await client.post(
            "/api/admin/challenges/release",
            json={"challenge_ids": [str(challenge.id)], "release_at": None},
        )

        entry = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "challenge.schedule",
                    AuditLog.target_id == challenge.id,
                )
            )
        ).scalar_one()
        assert entry.actor_user_id is not None


class TestAuditReading:
    async def test_actor_names_are_resolved(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await make_user(
            db_session, display_name="Dungeon Master", role=UserRole.ADMIN, status=UserStatus.ACTIVE
        )
        await sign_in(client, admin)
        player = await make_user(db_session)
        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 10, "reason": "Nice work"},
        )

        rows = (await client.get("/api/admin/audit-log")).json()

        assert rows[0]["actor_name"] == "Dungeon Master"
        assert rows[0]["reason"] == "Nice work"

    async def test_entries_can_be_filtered_by_action(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in)
        player = await make_user(db_session)
        await client.post(
            "/api/admin/adjustments",
            json={"user_id": str(player.id), "points": 10, "reason": "One"},
        )

        rows = (await client.get("/api/admin/audit-log?action=score.")).json()

        assert rows
        assert all(row["action"].startswith("score.") for row in rows)

    async def test_a_player_cannot_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.PLAYER)

        assert (await client.get("/api/admin/audit-log")).status_code == 403


class TestEmptyDatabase:
    async def test_the_dashboard_answers_with_nothing_to_report(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)

        response = await client.get("/api/admin/dashboard")

        assert response.status_code == 200
        assert response.json()["pulse"]["solves_5m"] == 0

    async def test_challenge_health_is_empty_not_broken(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await signed_in(db_session, client, sign_in, role=UserRole.ORGANIZER)

        assert (await client.get("/api/admin/challenge-health")).status_code == 200
