"""Admin approval, roles and event configuration (spec 002)."""

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.auth import AuthSession
from app.models.event import EVENT_CONFIG_ID, EventConfig
from app.models.user import UserRole, UserStatus
from tests.factories import make_user


async def as_role(db_session, client, sign_in, role: UserRole):
    user = await make_user(db_session, role=role, status=UserStatus.ACTIVE)
    await sign_in(client, user)
    return user


class TestAccessControl:
    async def test_a_player_cannot_read_the_user_list(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.get("/api/admin/users")).status_code == 403

    async def test_an_organizer_can_read_but_not_approve(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Staff watching for broken challenges must not be able to change state."""
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)
        guest = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)

        assert (await client.get("/api/admin/users")).status_code == 200
        response = await client.post("/api/admin/users/approve", json={"user_ids": [str(guest.id)]})
        assert response.status_code == 403

    async def test_an_admin_can_do_both(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        guest = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)

        assert (await client.get("/api/admin/users")).status_code == 200
        assert (
            await client.post("/api/admin/users/approve", json={"user_ids": [str(guest.id)]})
        ).status_code == 200

    async def test_an_anonymous_caller_gets_401_not_403(self, client: AsyncClient) -> None:
        assert (await client.get("/api/admin/users")).status_code == 401


class TestApprovalQueue:
    async def test_the_queue_can_be_filtered_to_pending_guests(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        pending = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        await make_user(db_session, status=UserStatus.ACTIVE)

        body = (await client.get("/api/admin/users?status=pending_approval")).json()

        assert [u["id"] for u in body["users"]] == [str(pending.id)]

    async def test_the_queue_is_oldest_first(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Someone who signed up last night should not be buried by today's."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        first = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        second = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)

        body = (await client.get("/api/admin/users?status=pending_approval")).json()

        assert [u["id"] for u in body["users"]] == [str(first.id), str(second.id)]

    async def test_users_can_be_searched(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        await make_user(db_session, email="findme@example.com", display_name="Findable")

        body = (await client.get("/api/admin/users?search=findme")).json()

        assert body["total"] == 1


class TestApproval:
    async def test_approving_activates_the_account(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)
        guest = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)

        response = await client.post(
            "/api/admin/users/approve", json={"user_ids": [str(guest.id)], "notify": False}
        )

        assert response.status_code == 200
        await db_session.refresh(guest)
        assert guest.status == UserStatus.ACTIVE
        assert guest.approved_by_user_id == admin.id

    async def test_many_guests_can_be_approved_at_once(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """200 guests approved one click at a time is not a plan."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        guests = [await make_user(db_session, status=UserStatus.PENDING_APPROVAL) for _ in range(5)]

        response = await client.post(
            "/api/admin/users/approve",
            json={"user_ids": [str(g.id) for g in guests], "notify": False},
        )

        assert response.json()["total"] == 5
        for guest in guests:
            await db_session.refresh(guest)
            assert guest.status == UserStatus.ACTIVE

    async def test_approving_twice_is_harmless(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        guest = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)
        payload = {"user_ids": [str(guest.id)], "notify": False}

        await client.post("/api/admin/users/approve", json=payload)
        second = await client.post("/api/admin/users/approve", json=payload)

        # Already active, so nothing to do and nobody to re-notify.
        assert second.json()["total"] == 0

    async def test_an_unknown_id_fails_the_whole_batch(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        import uuid

        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        guest = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)

        response = await client.post(
            "/api/admin/users/approve",
            json={"user_ids": [str(guest.id), str(uuid.uuid4())]},
        )

        assert response.status_code == 404
        await db_session.refresh(guest)
        assert guest.status == UserStatus.PENDING_APPROVAL

    async def test_approval_is_audit_logged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)
        guest = await make_user(db_session, status=UserStatus.PENDING_APPROVAL)

        await client.post(
            "/api/admin/users/approve",
            json={"user_ids": [str(guest.id)], "reason": "Known attendee", "notify": False},
        )

        entry = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.approve", AuditLog.target_id == guest.id
                )
            )
        ).scalar_one()
        assert entry.actor_user_id == admin.id
        assert entry.reason == "Known attendee"


class TestDisabling:
    async def test_disabling_ends_every_session(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """Not at the next token expiry — the account must stop acting now."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        victim = await make_user(db_session, status=UserStatus.ACTIVE)
        from app.config import Settings
        from app.services.sessions import issue_session

        await issue_session(db_session, Settings(), victim.id)

        response = await client.post(
            f"/api/admin/users/{victim.id}/disable", json={"reason": "Sharing flags"}
        )

        assert response.status_code == 200
        live = (
            (
                await db_session.execute(
                    select(AuthSession).where(
                        AuthSession.user_id == victim.id, AuthSession.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert live == []

    async def test_a_reason_is_required(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """This is the most contested action an admin can take."""
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        victim = await make_user(db_session)

        response = await client.post(f"/api/admin/users/{victim.id}/disable", json={})

        assert response.status_code == 422

    async def test_an_admin_cannot_disable_themselves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)

        response = await client.post(
            f"/api/admin/users/{admin.id}/disable", json={"reason": "oops"}
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cannot_disable_self"


class TestRoles:
    async def test_an_admin_can_promote_someone(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        player = await make_user(db_session)

        response = await client.post(
            f"/api/admin/users/{player.id}/role", json={"role": "organizer"}
        )

        assert response.status_code == 200
        await db_session.refresh(player)
        assert player.role == UserRole.ORGANIZER

    async def test_an_admin_cannot_demote_themselves(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The last admin locking themselves out mid-event is unrecoverable."""
        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)

        response = await client.post(f"/api/admin/users/{admin.id}/role", json={"role": "player"})

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "cannot_demote_self"

    async def test_role_changes_are_audit_logged_with_before_and_after(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        player = await make_user(db_session)

        await client.post(f"/api/admin/users/{player.id}/role", json={"role": "admin"})

        entry = (
            await db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "user.set_role", AuditLog.target_id == player.id
                )
            )
        ).scalar_one()
        assert entry.meta == {"from": "player", "to": "admin"}


class TestEventConfig:
    async def test_an_admin_can_schedule_the_event(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        start = datetime.now(UTC) + timedelta(days=1)
        end = start + timedelta(days=2)

        response = await client.patch(
            "/api/admin/event-config",
            json={
                "name": "Autumn Crawl",
                "starts_at": start.isoformat(),
                "ends_at": end.isoformat(),
            },
        )

        assert response.status_code == 200
        config = await db_session.get(EventConfig, EVENT_CONFIG_ID)
        assert config is not None and config.name == "Autumn Crawl"

    async def test_an_event_cannot_end_before_it_starts(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)
        start = datetime.now(UTC) + timedelta(days=1)

        response = await client.patch(
            "/api/admin/event-config",
            json={
                "starts_at": start.isoformat(),
                "ends_at": (start - timedelta(hours=1)).isoformat(),
            },
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invalid_event_window"

    async def test_an_organizer_can_read_but_not_change_the_schedule(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)

        assert (await client.get("/api/admin/event-config")).status_code == 200
        assert (
            await client.patch("/api/admin/event-config", json={"name": "Nope"})
        ).status_code == 403

    async def test_scheduling_opens_the_gameplay_gate(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        """The whole point of the config: it is what the gate reads."""
        admin = await as_role(db_session, client, sign_in, UserRole.ADMIN)
        player = await make_user(db_session, status=UserStatus.ACTIVE)

        await client.patch(
            "/api/admin/event-config",
            json={
                "starts_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "ends_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            },
        )

        await sign_in(client, player)
        caps = (await client.get("/api/auth/me")).json()["capabilities"]
        assert caps["play"] is True
        assert admin.id != player.id

    async def test_config_changes_are_audit_logged(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ADMIN)

        await client.patch("/api/admin/event-config", json={"name": "Renamed Crawl"})

        entry = (
            await db_session.execute(
                select(AuditLog).where(AuditLog.action == "event_config.update")
            )
        ).scalar_one()
        assert entry.meta["name"] == "Renamed Crawl"


class TestAuditLogAccess:
    async def test_staff_can_read_the_audit_log(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.ORGANIZER)

        assert (await client.get("/api/admin/audit-log")).status_code == 200

    async def test_players_cannot(
        self, client: AsyncClient, db_session: AsyncSession, sign_in
    ) -> None:
        await as_role(db_session, client, sign_in, UserRole.PLAYER)

        assert (await client.get("/api/admin/audit-log")).status_code == 403
