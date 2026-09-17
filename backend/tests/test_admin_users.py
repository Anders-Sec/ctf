"""The roster the approval queue was standing in for (spec 052)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserRole, UserSource, UserStatus
from tests.factories import make_challenge, make_team, make_user, record_solve


async def admin(db_session: AsyncSession, client: AsyncClient, sign_in):
    user = await make_user(db_session, role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestRosterColumns:
    async def test_the_list_carries_party_solves_and_xp(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Enough to tell a real player from a dormant account without opening
        anything."""
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Rin", status=UserStatus.ACTIVE)
        # make_team enrols the leader; a second add_member would trip the
        # one-active-membership index.
        await make_team(db_session, player, name="The Bold")
        challenge = await make_challenge(db_session, initial_points=120)
        await record_solve(db_session, player, challenge)

        body = (await client.get("/api/admin/users?search=Rin")).json()
        row = next(u for u in body["users"] if u["display_name"] == "Rin")

        assert row["party_name"] == "The Bold"
        assert row["solve_count"] == 1
        assert row["xp"] == 120

    async def test_a_player_in_no_party_reports_none(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        await make_user(db_session, display_name="Solo", status=UserStatus.ACTIVE)

        body = (await client.get("/api/admin/users?search=Solo")).json()
        row = next(u for u in body["users"] if u["display_name"] == "Solo")

        assert row["party_name"] is None
        assert row["solve_count"] == 0


class TestDetail:
    async def test_it_reports_identity_and_play_state(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Vex", status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=100)
        await record_solve(db_session, player, challenge)

        body = (await client.get(f"/api/admin/users/{player.id}")).json()

        assert body["user"]["display_name"] == "Vex"
        assert body["user"]["solve_count"] == 1
        assert body["level"] >= 1
        assert body["assistant_blocked"] is False

    async def test_its_totals_match_the_roster_for_the_same_user(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """One number, two places. They must not drift."""
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, display_name="Same", status=UserStatus.ACTIVE)
        challenge = await make_challenge(db_session, initial_points=250)
        await record_solve(db_session, player, challenge)

        listed = (await client.get("/api/admin/users?search=Same")).json()["users"][0]
        detail = (await client.get(f"/api/admin/users/{player.id}")).json()["user"]

        assert listed["xp"] == detail["xp"]
        assert listed["solve_count"] == detail["solve_count"]

    async def test_it_shows_party_history_including_ended_memberships(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Never hard-deleted (spec 002), and exactly what is needed when
        adjudicating a complaint about a kick."""
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await make_team(db_session, player, name="Old Guard")

        body = (await client.get(f"/api/admin/users/{player.id}")).json()

        assert any(spell["team_name"] == "Old Guard" for spell in body["parties"])

    async def test_the_activity_feed_never_carries_what_was_typed(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Read during a support conversation, often with the player watching.
        It has no business showing anyone's flag attempts verbatim."""
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        body = (await client.get(f"/api/admin/users/{player.id}")).json()

        assert "submitted_value" not in str(body)

    async def test_an_unknown_user_is_a_404(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        missing = "00000000-0000-0000-0000-0000000000ff"

        assert (await client.get(f"/api/admin/users/{missing}")).status_code == 404

    async def test_staff_may_read_it(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        assert (await client.get(f"/api/admin/users/{player.id}")).status_code == 200


class TestEnable:
    async def test_it_restores_access_and_clears_the_reason(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Disable had no inverse, so a disable made in error was permanent
        short of database access."""
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await client.post(f"/api/admin/users/{player.id}/disable", json={"reason": "Mistake"})

        response = await client.post(
            f"/api/admin/users/{player.id}/enable", json={"reason": "My mistake"}
        )

        assert response.status_code == 200
        await db_session.refresh(player)
        assert player.status == UserStatus.ACTIVE
        assert player.disabled_reason is None

    async def test_it_is_audited(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.DISABLED)

        await client.post(f"/api/admin/users/{player.id}/enable", json={"reason": "Cleared"})

        log = (await client.get("/api/admin/audit-log?action=user.enable")).json()
        assert log["entries"]
        assert log["entries"][0]["reason"] == "Cleared"

    async def test_a_reason_is_required(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.DISABLED)

        response = await client.post(f"/api/admin/users/{player.id}/enable", json={})

        assert response.status_code == 422

    async def test_an_organizer_cannot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)
        player = await make_user(db_session, status=UserStatus.DISABLED)

        response = await client.post(
            f"/api/admin/users/{player.id}/enable", json={"reason": "Nope"}
        )

        assert response.status_code == 403


class TestAssistantBlock:
    async def test_it_sets_the_column_that_had_no_ui(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        await client.post(
            f"/api/admin/users/{player.id}/assistant-block",
            json={"blocked": True, "reason": "Kept trying to extract flags"},
        )

        await db_session.refresh(player)
        assert player.assistant_blocked is True

    async def test_it_can_be_lifted(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await admin(db_session, client, sign_in)
        player = await make_user(db_session, status=UserStatus.ACTIVE)
        await client.post(f"/api/admin/users/{player.id}/assistant-block", json={"blocked": True})

        await client.post(f"/api/admin/users/{player.id}/assistant-block", json={"blocked": False})

        await db_session.refresh(player)
        assert player.assistant_blocked is False

    async def test_it_affects_nobody_else(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """One player misbehaving should not cost the other 199 the feature —
        which is what the event-wide switch would do."""
        await admin(db_session, client, sign_in)
        blocked = await make_user(db_session, status=UserStatus.ACTIVE)
        bystander = await make_user(db_session, status=UserStatus.ACTIVE)

        await client.post(f"/api/admin/users/{blocked.id}/assistant-block", json={"blocked": True})

        await db_session.refresh(bystander)
        assert bystander.assistant_blocked is False


class TestResendMagicLink:
    async def test_it_is_refused_for_an_entra_account(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """There is no link to send; they sign in through the provider."""
        await admin(db_session, client, sign_in)
        employee = await make_user(db_session, source=UserSource.ENTRA, status=UserStatus.ACTIVE)

        response = await client.post(f"/api/admin/users/{employee.id}/resend-magic-link")

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "not_a_guest"

    async def test_an_organizer_cannot_send_one(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        organizer = await make_user(db_session, role=UserRole.ORGANIZER, status=UserStatus.ACTIVE)
        await sign_in(client, organizer)
        guest = await make_user(db_session, status=UserStatus.ACTIVE)

        response = await client.post(f"/api/admin/users/{guest.id}/resend-magic-link")

        assert response.status_code == 403


class TestSelfProtection:
    """There is one admin. Locking themselves out ends the event."""

    async def test_an_admin_cannot_disable_themselves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        me = await admin(db_session, client, sign_in)

        response = await client.post(f"/api/admin/users/{me.id}/disable", json={"reason": "Oops"})

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "cannot_disable_self"

    @pytest.mark.parametrize("role", ["player", "organizer"])
    async def test_an_admin_cannot_demote_themselves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in, role: str
    ) -> None:
        me = await admin(db_session, client, sign_in)

        response = await client.post(f"/api/admin/users/{me.id}/role", json={"role": role})

        assert response.status_code >= 400
        assert response.json()["error"]["code"] == "cannot_demote_self"
