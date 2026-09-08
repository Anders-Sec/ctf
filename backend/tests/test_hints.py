"""Hints: cost, gating, and the score arithmetic (spec 004)."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeState, ScoringMode
from app.models.hint import Hint, HintUnlock
from app.models.play import ScoreAdjustment
from app.models.user import UserRole, UserStatus
from app.services.scoring import user_score
from tests.factories import make_challenge, make_user, record_solve

pytestmark = pytest.mark.usefixtures("running_event")


async def player(db_session, client, sign_in, **kwargs):
    kwargs.setdefault("status", UserStatus.ACTIVE)
    user = await make_user(db_session, **kwargs)
    await sign_in(client, user)
    return user


async def add_hint(
    db_session,
    challenge,
    *,
    title: str = "Where to look",
    body: str = "Check the packet comments.",
    cost: int = 50,
    order: int = 0,
    prerequisite: Hint | None = None,
    available_after: datetime | None = None,
) -> Hint:
    hint = Hint(
        challenge_id=challenge.id,
        title=title,
        body=body,
        cost=cost,
        display_order=order,
        prerequisite_hint_id=prerequisite.id if prerequisite else None,
        available_after=available_after,
    )
    db_session.add(hint)
    await db_session.flush()
    return hint


class TestListing:
    async def test_a_hint_is_advertised_without_its_body(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The player sees what they would buy, never the thing itself."""
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        await add_hint(db_session, challenge, body="THE ACTUAL HINT", cost=75)

        response = await client.get(f"/api/challenges/{challenge.id}")

        hint = response.json()["hints"][0]
        assert hint["title"] == "Where to look"
        assert hint["cost"] == 75
        assert hint["unlocked"] is False
        assert hint["body"] is None
        assert "THE ACTUAL HINT" not in response.text

    async def test_a_locked_challenge_lists_no_hints_at_all(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, state=ChallengeState.LOCKED)
        await add_hint(db_session, challenge)

        assert (await client.get(f"/api/challenges/{challenge.id}")).json()["hints"] == []

    async def test_hints_come_back_in_order(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        await add_hint(db_session, challenge, title="Second", order=2)
        await add_hint(db_session, challenge, title="First", order=1)

        titles = [
            h["title"]
            for h in (await client.get(f"/api/challenges/{challenge.id}")).json()["hints"]
        ]

        assert titles == ["First", "Second"]


class TestUnlocking:
    async def test_unlocking_reveals_the_body_and_records_the_deferred_cost(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Unlocking hands over the body and snapshots what it will cost, but the
        cost is deferred to the solve (spec 015) — the score does not move yet."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge, body="Look at frame 42.", cost=50)

        response = await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")

        assert response.status_code == 200
        body = response.json()
        assert body["body"] == "Look at frame 42."
        assert body["cost_charged"] == 50
        # Free in the moment: a hint on an unsolved challenge costs nothing.
        assert await user_score(db_session, user.id) == 0

    async def test_unlocking_twice_charges_once(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Players double-click."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge, cost=50)
        url = f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock"

        first = await client.post(url)
        second = await client.post(url)

        assert first.json()["cost_charged"] == 50
        assert second.status_code == 200
        assert second.json()["cost_charged"] == 0
        assert second.json()["already_unlocked"] is True
        # No solve yet, so no charge — and the second click adds nothing.
        assert await user_score(db_session, user.id) == 0

        rows = (
            (await db_session.execute(select(HintUnlock).where(HintUnlock.user_id == user.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1

    async def test_a_hint_is_free_once_the_challenge_is_solved(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Reading the hint afterwards is learning, and should not be taxed."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        hint = await add_hint(db_session, challenge, cost=50)
        await record_solve(db_session, user, challenge)

        response = await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")

        assert response.json()["cost_charged"] == 0
        assert await user_score(db_session, user.id) == 300

    async def test_the_advertised_cost_drops_to_zero_after_solving(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """So the UI can say "free" rather than surprising them at the till."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        await add_hint(db_session, challenge, cost=50)
        await record_solve(db_session, user, challenge)

        hint = (await client.get(f"/api/challenges/{challenge.id}")).json()["hints"][0]

        assert hint["cost"] == 0

    async def test_a_hint_on_a_locked_challenge_cannot_be_unlocked(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge)
        challenge.state = ChallengeState.LOCKED
        await db_session.flush()

        response = await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "challenge_locked"

    async def test_a_hint_id_from_another_challenge_is_refused(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        owner = await make_challenge(db_session)
        other = await make_challenge(db_session)
        hint = await add_hint(db_session, owner)

        response = await client.post(f"/api/challenges/{other.id}/hints/{hint.id}/unlock")

        assert response.status_code == 404


class TestGating:
    async def test_a_prerequisite_must_be_bought_first(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        first = await add_hint(db_session, challenge, title="First", order=1)
        second = await add_hint(db_session, challenge, title="Second", order=2, prerequisite=first)

        blocked = await client.post(f"/api/challenges/{challenge.id}/hints/{second.id}/unlock")
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "hint_locked"

        await client.post(f"/api/challenges/{challenge.id}/hints/{first.id}/unlock")
        allowed = await client.post(f"/api/challenges/{challenge.id}/hints/{second.id}/unlock")
        assert allowed.status_code == 200

    async def test_availability_is_reported_before_the_prerequisite_is_met(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        first = await add_hint(db_session, challenge, title="First", order=1)
        await add_hint(db_session, challenge, title="Second", order=2, prerequisite=first)

        hints = (await client.get(f"/api/challenges/{challenge.id}")).json()["hints"]

        assert hints[0]["available"] is True
        assert hints[1]["available"] is False

    async def test_a_scheduled_hint_is_visible_but_not_yet_buyable(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A player can see something is coming without reading it."""
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        hint = await add_hint(
            db_session,
            challenge,
            title="Tomorrow's nudge",
            available_after=datetime.now(UTC) + timedelta(hours=2),
        )

        listed = (await client.get(f"/api/challenges/{challenge.id}")).json()["hints"][0]
        attempt = await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")

        assert listed["title"] == "Tomorrow's nudge"
        assert listed["available"] is False
        assert listed["body"] is None
        assert attempt.status_code == 403

    async def test_a_past_availability_time_opens_the_hint(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        hint = await add_hint(
            db_session, challenge, available_after=datetime.now(UTC) - timedelta(minutes=1)
        )

        assert (
            await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")
        ).status_code == 200


class TestScoreArithmetic:
    async def test_solve_banks_value_minus_hints_plus_adjustments(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """A solve banks the challenge's value minus the hints taken on it; admin
        adjustments still move the total (spec 015)."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=300)
        hint = await add_hint(db_session, challenge, cost=50)
        await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")
        solve = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )
        db_session.add(ScoreAdjustment(user_id=user.id, points=25, reason="Goodwill"))
        await db_session.flush()

        assert solve.json()["points_awarded"] == 300 - 50
        assert await user_score(db_session, user.id) == 300 - 50 + 25

    async def test_hints_never_go_negative_but_an_adjustment_can(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Hints only shrink a solve's reward (floored at zero), so buying hints
        and solving nothing costs nothing; a negative total is a deliberate admin
        correction (spec 015)."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge, cost=120)

        await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")
        assert await user_score(db_session, user.id) == 0

        db_session.add(ScoreAdjustment(user_id=user.id, points=-120, reason="Penalty"))
        await db_session.flush()

        assert await user_score(db_session, user.id) == -120
        assert (await client.get("/api/me/score")).json()["total"] == -120

    async def test_editing_a_cost_does_not_rewrite_what_was_paid(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The penalty is the cost snapshotted when the hint was taken, not the
        hint's price at solve time (spec 015)."""
        user = await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session, scoring=ScoringMode.STATIC, initial_points=500)
        hint = await add_hint(db_session, challenge, cost=50)
        await client.post(f"/api/challenges/{challenge.id}/hints/{hint.id}/unlock")

        hint.cost = 500
        await db_session.flush()

        solve = await client.post(
            f"/api/challenges/{challenge.id}/submit", json={"answer": "flag{correct}"}
        )

        assert solve.json()["points_awarded"] == 500 - 50
        assert await user_score(db_session, user.id) == 500 - 50


class TestAdminHints:
    async def test_an_admin_can_add_a_hint(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, role=UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/hints",
            json={"title": "Nudge", "body": "Look closer.", "cost": 25},
        )

        assert response.status_code == 201
        assert response.json()["cost"] == 25

    async def test_a_player_cannot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in)
        challenge = await make_challenge(db_session)

        response = await client.post(
            f"/api/admin/challenges/{challenge.id}/hints",
            json={"title": "Nudge", "body": "Look closer."},
        )

        assert response.status_code == 403

    async def test_an_organizer_can_read_hints_but_not_write_them(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, role=UserRole.ORGANIZER)
        challenge = await make_challenge(db_session)
        await add_hint(db_session, challenge)

        assert (await client.get(f"/api/admin/challenges/{challenge.id}/hints")).status_code == 200
        assert (
            await client.post(
                f"/api/admin/challenges/{challenge.id}/hints",
                json={"title": "No", "body": "No"},
            )
        ).status_code == 403

    async def test_a_paid_for_hint_cannot_be_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Refunding is a deliberate score adjustment, not a side effect."""
        admin = await player(db_session, client, sign_in, role=UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge)
        db_session.add(
            HintUnlock(
                user_id=admin.id,
                hint_id=hint.id,
                cost_charged=hint.cost,
                unlocked_at=datetime.now(UTC),
            )
        )
        await db_session.flush()

        response = await client.delete(f"/api/admin/challenges/{challenge.id}/hints/{hint.id}")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "hint_has_unlocks"

    async def test_an_unbought_hint_can_be_deleted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, role=UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge)

        assert (
            await client.delete(f"/api/admin/challenges/{challenge.id}/hints/{hint.id}")
        ).status_code == 200

    async def test_a_hint_cannot_require_itself(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await player(db_session, client, sign_in, role=UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge)

        response = await client.patch(
            f"/api/admin/challenges/{challenge.id}/hints/{hint.id}",
            json={"prerequisite_hint_id": str(hint.id)},
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "hint_prerequisite_cycle"

    async def test_hint_text_stays_out_of_the_audit_log(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Organizers can read that log; it is not a place to reproduce hints."""
        from app.models.audit import AuditLog

        await player(db_session, client, sign_in, role=UserRole.ADMIN)
        challenge = await make_challenge(db_session)

        await client.post(
            f"/api/admin/challenges/{challenge.id}/hints",
            json={"title": "Nudge", "body": "THE ACTUAL HINT TEXT", "cost": 10},
        )

        entry = (
            await db_session.execute(select(AuditLog).where(AuditLog.action == "hint.create"))
        ).scalar_one()
        assert "THE ACTUAL HINT TEXT" not in str(entry.meta)

    async def test_the_unlock_count_is_reported(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await player(db_session, client, sign_in, role=UserRole.ADMIN)
        challenge = await make_challenge(db_session)
        hint = await add_hint(db_session, challenge)
        db_session.add(
            HintUnlock(
                user_id=admin.id,
                hint_id=hint.id,
                cost_charged=0,
                unlocked_at=datetime.now(UTC),
            )
        )
        await db_session.flush()

        rows = (await client.get(f"/api/admin/challenges/{challenge.id}/hints")).json()

        assert rows[0]["unlock_count"] == 1
